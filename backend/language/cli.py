"""Cluster C standalone test: the CLI loop.

    python -m language.cli                       # interactive
    python -m language.cli --script language/eval/demo_script.txt --log out.jsonl
    python -m language.cli --offline             # no Claude, rule-based fallbacks

Commands (interactive or in a script file, one per line):
  say <english>              Bob speaks (typed)           -> caption, avatar_play
  wav <file>                 Bob speaks (audio file)      -> VAD -> Whisper -> ...
  mic [seconds]              Bob speaks (microphone)      -> needs `pip install sounddevice`
  sign HELLO                 Alice signs, confident
  sign BOOK:.62 READ:.58     Alice signs, top-3 from recognition with confidences
  end                        end Alice's utterance now (otherwise auto after the pause)
  teach LABEL [english...]   simulate "teach it live" (teach_stop)
  voices [search]            list ElevenLabs voices in your account, e.g. `voices nigerian`
  voice <id>                 switch Alice's voice (ElevenLabs voice id, or edge voice name)
  speak <text>               say any text in the current voice (audition voices)
  wait <seconds>             pause (scripts)
  setting <text>             change the scene given to Claude
  history | vocab | reset | help | quit

Every emitted message is printed, checked against the contract, and (with --log)
written as JSONL in the exact shape the web UI receives, so mock.ts can replay it.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import shlex
import subprocess
import sys
import time
from pathlib import Path

from . import contract
from .config import Settings
from .module import LanguageModule

COLORS = {"caption": "36", "avatar_play": "35", "sign_recognized": "33", "sentence": "32",
          "unknown_sign": "31", "status": "90", "speech_audio": "34"}


class Printer:
    def __init__(self, log_path: str | None, color: bool):
        self.log = open(log_path, "a") if log_path else None
        self.color = color
        self.count: dict[str, int] = {}

    def __call__(self, msg: dict) -> None:
        contract.validate(msg)
        self.count[msg["type"]] = self.count.get(msg["type"], 0) + 1
        if self.log:
            self.log.write(json.dumps(msg) + "\n")
            self.log.flush()
        shown = {k: v for k, v in msg.items() if k not in ("type", "ts")}
        if msg["type"] == "speech_audio":
            shown["audio"] = f"<{len(msg['audio'])} b64 chars>"
        line = f"  <- {msg['type']:<16} {json.dumps(shown, ensure_ascii=False)}"
        c = COLORS.get(msg["type"])
        print(f"\033[{c}m{line}\033[0m" if self.color and c else line, flush=True)


def load_pcm(path: str) -> bytes:
    """Any audio file -> 16 kHz mono s16le via ffmpeg (or raw .pcm as-is)."""
    if path.endswith(".pcm"):
        return Path(path).read_bytes()
    return subprocess.run(["ffmpeg", "-loglevel", "error", "-i", path, "-ar", "16000", "-ac", "1",
                           "-f", "s16le", "-"], check=True, capture_output=True).stdout


async def stream_pcm(lm: LanguageModule, pcm: bytes, realtime: bool = False) -> None:
    """Feed audio exactly as the app does: 100 ms `audio` messages, then trailing silence."""
    pcm = pcm + b"\x00\x00" * 16000
    for i in range(0, len(pcm), 3200):
        await lm.handle({"type": "audio", "ts": contract.now_ms(),
                         "pcm": base64.b64encode(pcm[i:i + 3200]).decode(), "rate": 16000})
        await asyncio.sleep(0.1 if realtime else 0)
    await lm.flush_audio()
    await drain(lm)


async def drain(lm: LanguageModule) -> None:
    while lm._bg:
        await asyncio.sleep(0.05)


async def record_mic(seconds: float) -> bytes:
    import sounddevice as sd  # optional dependency
    print(f"  (recording {seconds:.0f}s... speak now)")
    audio = sd.rec(int(seconds * 16000), samplerate=16000, channels=1, dtype="int16")
    await asyncio.get_running_loop().run_in_executor(None, sd.wait)
    return audio.tobytes()


def parse_candidates(args: list[str]) -> list[dict]:
    items = []
    for a in args:
        label, _, conf = a.partition(":")
        items.append({"label": label, "confidence": float(conf) if conf else 0.95})
    return items


async def run_command(lm: LanguageModule, line: str) -> bool:
    line = line.strip()
    if not line or line.startswith("#"):
        return True
    cmd, _, rest = line.partition(" ")
    args = shlex.split(rest) if rest else []
    t0 = time.perf_counter()
    if cmd in ("quit", "exit", "q"):
        return False
    elif cmd == "say":
        await lm.on_text(rest)
    elif cmd == "wav":
        await stream_pcm(lm, load_pcm(args[0]))
    elif cmd == "mic":
        await stream_pcm(lm, await record_mic(float(args[0]) if args else 5))
    elif cmd == "sign":
        await lm.on_sign_candidates(parse_candidates(args))
        return True  # sentence comes later (pause timer), don't print timing yet
    elif cmd == "end":
        await lm.end_signing()
    elif cmd == "teach":
        await lm.on_teach_stop(args[0], " ".join(args[1:]) or None)
        print(f"  taught {args[0].upper()}; vocabulary now {len(lm.vocab.labels)} signs")
    elif cmd == "wait":
        await asyncio.sleep(float(args[0]))
        await drain(lm)
        return True
    elif cmd == "voices":
        el = lm.tts.get_engine("elevenlabs")
        if not el:
            print("  ElevenLabs isn't active: set ELEVENLABS_API_KEY (and --tts auto or elevenlabs)")
            return True
        try:
            voices = await el.list_voices(rest or None)
        except Exception as e:
            print(f"  {e}")
            return True
        if not voices:
            print("  no voices matched. Add one from the Voice Library on elevenlabs.io, then retry.")
        for v in voices:
            tag = " ".join(x for x in (v["accent"], v["gender"], v["category"]) if x)
            current = "  <- current" if v["voice_id"] == el.voice else ""
            print(f"  {v['voice_id']}  {v['name'][:28]:<28} {tag[:34]:<34} {v['description'][:40]}{current}")
    elif cmd == "voice":
        if not args:
            print(f"  current: {lm.tts.describe()}")
            return True
        engine = await lm.set_voice(args[0])
        print(f"  {engine} voice -> {args[0]}" if engine else "  no engine that supports voices is active")
    elif cmd == "speak":
        engine, ms = await lm.speak(rest)
        print(f"  ({engine or 'no TTS engine produced audio'}{f', {ms:.0f} ms to synthesise' if ms else ''})")
    elif cmd == "setting":
        lm.glosser.setting = lm.interp.setting = rest
        print("  setting updated")
    elif cmd == "history":
        for who, text in lm.convo.recent():
            print(f"  {who}: {text}")
    elif cmd == "vocab":
        print("  " + " ".join(lm.vocab.labels))
    elif cmd == "reset":
        lm.convo.clear()
        print("  conversation cleared")
    elif cmd == "help":
        print(__doc__)
    else:
        print(f"  unknown command {cmd!r} (try help)")
        return True
    if cmd in ("say", "wav", "mic", "end"):
        g = getattr(lm, "last_gloss", None)
        src = f" via {g.source}" if cmd != "end" and g else ""
        print(f"  ({(time.perf_counter() - t0) * 1000:.0f} ms{src})")
    return True


async def amain(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m language.cli", description="Almero language & voice CLI loop")
    ap.add_argument("--script", help="run commands from a file, then exit")
    ap.add_argument("--log", help="append every emitted message as JSONL (replayable by mock.ts)")
    ap.add_argument("--offline", action="store_true", help="no Claude; rule-based fallbacks")
    ap.add_argument("--stt", choices=["whisper", "none"], help="speech-to-text engine")
    ap.add_argument("--whisper-model", help="e.g. base.en, small.en")
    ap.add_argument("--tts", choices=["auto", "elevenlabs", "edge", "system", "none"],
                    help="TTS engine (auto = ElevenLabs if ELEVENLABS_API_KEY is set, else edge)")
    ap.add_argument("--el-voice", help="ElevenLabs voice id")
    ap.add_argument("--el-model", help="ElevenLabs model, e.g. eleven_flash_v2_5, eleven_v4_turbo")
    ap.add_argument("--voice", help="edge-tts voice, e.g. en-NG-AbeoNeural")
    ap.add_argument("--tts-mode", choices=["app", "service", "local"], default=None,
                    help="where Bob hears Alice (default for the CLI: local speakers)")
    ap.add_argument("--names", help="comma-separated participant names, e.g. Ada,Chidi")
    ap.add_argument("--pause", type=float, help="seconds of no signing that ends Alice's sentence")
    ap.add_argument("--no-color", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO if a.verbose else logging.WARNING,
                        format="  [%(name)s] %(message)s")
    for noisy in ("httpx", "httpx2", "huggingface_hub", "faster_whisper"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    s = Settings()
    s.offline = a.offline or s.offline
    s.tts_mode = a.tts_mode or "local"
    if a.stt: s.stt_engine = a.stt
    if a.whisper_model: s.whisper_model = a.whisper_model
    if a.tts: s.tts_engine = a.tts
    if a.voice: s.tts_voice = a.voice
    if a.el_voice: s.elevenlabs_voice_id = a.el_voice
    if a.el_model: s.elevenlabs_model = a.el_model
    if a.names: s.names = [n.strip() for n in a.names.split(",") if n.strip()]
    if a.pause: s.sign_pause_s = a.pause
    if a.script and s.stt_engine == "whisper":
        # don't load Whisper for scripts that never use audio
        text = Path(a.script).read_text()
        if not any(l.split(" ")[0] in ("wav", "mic") for l in text.splitlines()):
            s.stt_engine = "none"

    printer = Printer(a.log, color=not a.no_color and sys.stdout.isatty())
    lm = LanguageModule(printer, s)
    print(f"Almero language CLI: claude={'on (' + s.claude_model + ')' if lm.claude.enabled else 'OFF, rule-based fallback'}"
          f" stt={lm.stt.name} tts={lm.tts.describe() if s.tts_mode != 'app' else 'app'} ({s.tts_mode})"
          f" vocab={len(lm.vocab.labels)} signs pause={s.sign_pause_s}s")
    await lm.start()

    try:
        if a.script:
            for line in Path(a.script).read_text().splitlines():
                if line.strip() and not line.startswith("#"):
                    print(f"> {line}")
                if not await run_command(lm, line):
                    break
            await asyncio.sleep(s.sign_pause_s + 0.2)
            await drain(lm)
        else:
            print("Type `help` for commands.")
            loop = asyncio.get_running_loop()
            while True:
                try:
                    line = await loop.run_in_executor(None, input, "> ")
                except EOFError:
                    break
                if not await run_command(lm, line):
                    break
                await drain(lm)
    finally:
        await drain(lm)
        await lm.close()
    print("emitted: " + ", ".join(f"{k}={v}" for k, v in sorted(printer.count.items())))
    return 0


def main() -> None:
    sys.exit(asyncio.run(amain()))


if __name__ == "__main__":
    main()
