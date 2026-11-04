"""Replays recorded frame folders over /ws and prints every service message.

  python tests/replay.py <frames_folder>                       stream one folder, print messages
  python tests/replay.py --teach wave <take1> <take2> <query>  teach from two folders, then recognise
  python tests/replay.py --room ABCD <frames_folder>           same, as the signer of room ABCD
  python tests/replay.py --participant Bob --room ABCD         join ABCD as a participant, say --speech
"""
import argparse
import asyncio
import base64
import json
import re
import time
from urllib.parse import quote
from pathlib import Path

import websockets

FPS = 10


def frames(folder):
    files = sorted(Path(folder).glob("*.jpg"), key=lambda p: int(re.search(r"\d+", p.stem).group()))
    if not files:
        raise SystemExit(f"no .jpg frames in {folder}")
    return files


async def send(ws, **m):
    await ws.send(json.dumps({"ts": int(time.time() * 1000), **m}))


async def printer(ws, seen):
    try:
        async for raw in ws:
            m = json.loads(raw)
            seen.append(m)
            if m["type"] == "landmarks":
                print(f"landmarks hands={len(m['hands'])}")
            else:
                print(json.dumps(m))
    except websockets.ConnectionClosed:
        pass
    print(f"--- closed {ws.close_code} {ws.close_reason or ''}".rstrip())


async def stream(ws, folder, w=504, h=896):
    files = frames(folder)
    print(f"--- streaming {len(files)} frames from {folder}")
    t0 = int(re.search(r"\d+", files[0].stem).group())
    for f in files:
        ts = int(re.search(r"\d+", f.stem).group())
        await send(ws, type="frame", jpeg=base64.b64encode(f.read_bytes()).decode(), w=w, h=h)
        await asyncio.sleep(1 / FPS)
    await asyncio.sleep(1.5)   # let the pause / idle rule close the last sign


async def wait_for(seen, type_, since=0, timeout=5):
    """First message of type_ received after index `since` (messages may already have arrived)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for m in seen[since:]:
            if m["type"] == type_:
                return m
        await asyncio.sleep(0.05)
    return None


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("folders", nargs="*")
    p.add_argument("--url", default="ws://localhost:8000/ws")
    p.add_argument("--teach", metavar="LABEL", help="teach LABEL from the first two folders, query with the third")
    p.add_argument("--language", default="nsl")
    p.add_argument("--speech", default="hello can you help me")
    p.add_argument("--room", metavar="CODE", help="join this room (signer creates it if unknown)")
    p.add_argument("--participant", metavar="NAME", help="join --room as a participant instead of streaming frames")
    p.add_argument("--seconds", type=float, default=5, help="participant mode: how long to listen")
    a = p.parse_args()

    if a.participant:
        if not a.room:
            raise SystemExit("--participant needs --room")
        return await participant(a)
    if not a.folders:
        raise SystemExit("give at least one frames folder")
    url = f"{a.url}?room={a.room}&role=signer" if a.room else a.url
    async with websockets.connect(url, max_size=None) as ws:
        seen = []
        task = asyncio.create_task(printer(ws, seen))
        await send(ws, type="ui_ready", view="phone")
        await send(ws, type="settings", language=a.language, voice="default")

        if a.teach:
            if len(a.folders) < 3:
                raise SystemExit("--teach needs two take folders and one query folder")
            for folder in a.folders[:2]:
                since = len(seen)
                await send(ws, type="teach_start", label=a.teach)
                await stream(ws, folder)
                print("teach_progress:", "ok" if await wait_for(seen, "teach_progress", since) else "MISSING")
            since = len(seen)
            await send(ws, type="teach_stop", label=a.teach)
            print("sign_learned:", "ok" if await wait_for(seen, "sign_learned", since) else "MISSING")
            since = len(seen)
            await stream(ws, a.folders[2])
            m = await wait_for(seen, "sign_recognized", since)
            print("RESULT:", f"sign_recognized {m['label']} {m['confidence']}" if m else "no sign_recognized")
        else:
            for folder in a.folders:
                await stream(ws, folder)

        since = len(seen)
        await send(ws, type="speech_text", text=a.speech)
        m = await wait_for(seen, "avatar_play", since)
        print("RESULT:", json.dumps(m) if m else "no avatar_play")
        await asyncio.sleep(2.5)
        task.cancel()


async def participant(a):
    url = f"{a.url}?room={a.room}&role=participant&name={quote(a.participant)}"
    async with websockets.connect(url, max_size=None) as ws:
        seen = []
        task = asyncio.create_task(printer(ws, seen))
        await asyncio.sleep(0.5)
        if ws.close_code is not None:
            return
        await send(ws, type="speech_text", text=a.speech)
        await asyncio.sleep(a.seconds)
        task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
