"""Meeting soak test: one signer + N participants against a running service, for a while.

  python tests/test_meeting.py --url wss://host/ws --http https://host --participants 4 --seconds 60

The signer streams the "wave" frames in a loop (recognition -> sentence -> captions + voice for
everyone); participants take turns sending "hello" / "yes" (captions for everyone, avatar for the
signer). Every socket must stay up and every message must arrive. Prints a summary and FAIL lines.
"""
import argparse
import asyncio
import json
import time
from pathlib import Path

import httpx
import websockets

from replay import frames, send

HERE = Path(__file__).parent


async def listener(ws, name, log):
    try:
        async for raw in ws:
            m = json.loads(raw)
            log.append((name, m))
    except Exception as e:
        log.append((name, {"type": "__closed__", "error": repr(e)}))


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="ws://localhost:8000/ws")
    p.add_argument("--http", default="http://localhost:8000")
    p.add_argument("--participants", type=int, default=4)
    p.add_argument("--seconds", type=int, default=60)
    p.add_argument("--frames", default="/tmp/wave3")
    a = p.parse_args()

    async with httpx.AsyncClient(timeout=10) as c:
        code = (await c.post(f"{a.http}/rooms")).json()["code"]
    print(f"room {code}")
    log = []
    signer = await websockets.connect(f"{a.url}?room={code}&role=signer&name=Ada", max_size=None)
    tasks = [asyncio.create_task(listener(signer, "signer", log))]
    await send(signer, type="ui_ready", view="phone")
    await send(signer, type="settings", language="nsl", voice="default")
    parts = []
    for i in range(a.participants):
        ws = await websockets.connect(f"{a.url}?room={code}&role=participant&name=P{i + 1}", max_size=None)
        parts.append(ws)
        tasks.append(asyncio.create_task(listener(ws, f"P{i + 1}", log)))

    files = frames(a.frames)
    t_end = time.monotonic() + a.seconds
    rounds, said = 0, 0
    phrases = ["hello", "yes", "can you help me", "thank you"]
    while time.monotonic() < t_end:
        # signer: one pass of the wave clip at 10 fps
        for f in files:
            if time.monotonic() >= t_end:
                break
            await send(signer, type="frame", jpeg=__import__("base64").b64encode(f.read_bytes()).decode(), w=504, h=896)
            await asyncio.sleep(0.1)
        rounds += 1
        # participants: one phrase each, in turn
        for i, ws in enumerate(parts):
            await send(ws, type="speech_text", text=phrases[(said + i) % len(phrases)])
            said += 1
            await asyncio.sleep(0.5)
        await asyncio.sleep(2.5)

    await asyncio.sleep(3)
    for ws in [signer, *parts]:
        await ws.close()
    for t in tasks:
        t.cancel()

    # --- summary ---
    by = {}
    for who, m in log:
        by.setdefault(who, {}).setdefault(m["type"], 0)
        by[who][m["type"]] += 1
    fails = []
    closed = [w for w, m in log if m["type"] == "__closed__"]
    if closed:
        fails.append(f"sockets dropped: {closed}")
    s = by.get("signer", {})
    if s.get("sign_recognized", 0) < max(1, rounds // 2):
        fails.append(f"signer recognised only {s.get('sign_recognized', 0)} signs in {rounds} rounds")
    if s.get("caption", 0) < said:
        fails.append(f"signer got {s.get('caption', 0)} captions, participants said {said}")
    if s.get("avatar_play", 0) < said:
        fails.append(f"signer got {s.get('avatar_play', 0)} avatar_play for {said} phrases")
    for i in range(a.participants):
        pc = by.get(f"P{i + 1}", {})
        if pc.get("caption", 0) < said:
            fails.append(f"P{i + 1} got {pc.get('caption', 0)} captions, expected >= {said}")
        if pc.get("speak", 0) < 1:
            fails.append(f"P{i + 1} never got a speak")
    print(f"rounds {rounds}, phrases {said}, duration {a.seconds}s")
    for who in sorted(by):
        print(f"  {who}: " + ", ".join(f"{k}={v}" for k, v in sorted(by[who].items()) if k != "landmarks"))
    for f in fails:
        print("FAIL ", f)
    print("PASS  meeting held" if not fails else f"{len(fails)} problem(s)")


if __name__ == "__main__":
    asyncio.run(main())
