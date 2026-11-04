"""Pretend to be the phone app (or a UI) over the real WebSocket.

    python -m language.fake_app                                  # ws://localhost:8000/ws
    python -m language.fake_app --url ws://192.168.1.20:8000/ws --play
    python -m language.fake_app --script language/eval/demo_script.txt

Same commands as the CLI loop (say, wav, sign, end, teach, voice, wait, quit), but
every one becomes a real contract message on the socket, and everything the server
sends back is printed. --play plays `speech_audio` on this machine, as the phone would.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import shlex
import sys
import time
from pathlib import Path

from .cli import load_pcm, parse_candidates
from .contract import now_ms


async def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m language.fake_app")
    ap.add_argument("--url", default="ws://localhost:8000/ws")
    ap.add_argument("--view", default=None, help="act as a UI (phone/projector) instead of the app")
    ap.add_argument("--voice", help="send profile.voice_id on connect (ElevenLabs voice id)")
    ap.add_argument("--play", action="store_true", help="play speech_audio on this machine")
    ap.add_argument("--script", help="run commands from a file, then exit")
    a = ap.parse_args(argv)

    import websockets
    try:
        ws = await websockets.connect(a.url, max_size=16 * 2**20)
    except OSError as e:
        print(f"Can't reach {a.url}: {e}\nIs the server running? Same network? Firewall open on the port?")
        return 1
    print(f"connected to {a.url}")
    if a.view:
        await ws.send(json.dumps({"type": "ui_ready", "ts": now_ms(), "view": a.view}))
    else:
        profile = {"type": "profile", "ts": now_ms(), "head": {}}
        if a.voice:
            profile["voice_id"] = a.voice
        await ws.send(json.dumps(profile))

    sent_at = {"t": None}
    counts: dict[str, int] = {}

    async def receiver():
        from .tts import play_local
        async for raw in ws:
            m = json.loads(raw)
            counts[m["type"]] = counts.get(m["type"], 0) + 1
            shown = {k: v for k, v in m.items() if k not in ("type", "ts")}
            if m["type"] == "speech_audio":
                shown["audio"] = f"<{len(m['audio']) * 3 // 4 // 1024} KB {m.get('format')}>"
            since = f"  +{(time.perf_counter() - sent_at['t']) * 1000:.0f} ms" if sent_at["t"] else ""
            print(f"  <- {m['type']:<16} {json.dumps(shown, ensure_ascii=False)}{since}", flush=True)
            if m["type"] == "speech_audio" and a.play:
                asyncio.ensure_future(play_local((base64.b64decode(m["audio"]), m["format"])))

    rx = asyncio.ensure_future(receiver())

    async def send(msg):
        msg.setdefault("ts", now_ms())
        sent_at["t"] = time.perf_counter()
        await ws.send(json.dumps(msg))

    async def run(line: str) -> bool:
        line = line.strip()
        if not line or line.startswith("#"):
            return True
        cmd, _, rest = line.partition(" ")
        args = shlex.split(rest) if rest else []
        if cmd in ("quit", "exit", "q"):
            return False
        if cmd == "say":
            await send({"type": "dev_say", "text": rest})
        elif cmd == "wav":  # real-time pace, 100 ms chunks, exactly like the app
            pcm = load_pcm(args[0]) + b"\x00\x00" * 16000
            for i in range(0, len(pcm), 3200):
                await send({"type": "audio", "pcm": base64.b64encode(pcm[i:i + 3200]).decode(), "rate": 16000})
                await asyncio.sleep(0.1)
        elif cmd == "sign":
            await send({"type": "sign_candidates", "items": parse_candidates(args)})
        elif cmd == "end":
            await send({"type": "dev_end"})
        elif cmd == "teach":
            await send({"type": "teach_stop", "label": args[0], **({"english": " ".join(args[1:])} if args[1:] else {})})
            print(f"  -> taught {args[0]}")
        elif cmd == "voice":
            await send({"type": "profile", "head": {}, "voice_id": args[0]})
            print(f"  -> voice {args[0]}")
        elif cmd == "wait":
            await asyncio.sleep(float(args[0]))
        else:
            print(f"  unknown command {cmd!r}: say, wav, sign, end, teach, voice, wait, quit")
        return True

    try:
        if a.script:
            for line in Path(a.script).read_text().splitlines():
                if line.strip() and not line.startswith("#"):
                    print(f"> {line}")
                if not await run(line):
                    break
                await asyncio.sleep(0.3)
            await asyncio.sleep(2.5)  # let the last sentence and its audio arrive
        else:
            loop = asyncio.get_running_loop()
            while True:
                try:
                    line = await loop.run_in_executor(None, input, "> ")
                except EOFError:
                    break
                if not await run(line):
                    break
    finally:
        rx.cancel()
        await ws.close()
    print("received: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
