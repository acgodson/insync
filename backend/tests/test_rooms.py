"""Room flow against a running service (start it with CONFIDENCE_THRESHOLD=0).

  python tests/test_rooms.py [--http http://localhost:8000] [--frames /tmp/wave1 /tmp/wave2 /tmp/wave3]
"""
import argparse
import asyncio
import json
import urllib.request
from pathlib import Path

import websockets

from replay import send, stream, wait_for

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))


async def collect(ws, seen):
    try:
        async for raw in ws:
            seen.append(json.loads(raw))
    except websockets.ConnectionClosed:
        pass


def http(method, url):
    with urllib.request.urlopen(urllib.request.Request(url, method=method)) as r:
        return json.loads(r.read())


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--http", default="http://localhost:8000")
    p.add_argument("--frames", nargs=3, default=["/tmp/wave1", "/tmp/wave2", "/tmp/wave3"])
    a = p.parse_args()
    wsbase = a.http.replace("http", "ws", 1) + "/ws"

    # Create a room
    room = http("POST", a.http + "/rooms")
    code = room["code"]
    check("POST /rooms", len(code) == 4 and room["link"].endswith(f"/join/{code}"), room)

    # Unknown room for a participant -> 4404
    async with websockets.connect(f"{wsbase}?room=ZZZZ&role=participant&name=X") as bad:
        try:
            await asyncio.wait_for(bad.recv(), 3)
        except websockets.ConnectionClosed:
            pass
        check("participant to unknown room closed 4404", bad.close_code == 4404, bad.close_code)

    sig_seen, par_seen = [], []
    async with websockets.connect(f"{wsbase}?room={code}&role=signer&name=Alice", max_size=None) as sig, \
               websockets.connect(f"{wsbase}?room={code}&role=participant&name=Bob", max_size=None) as par:
        tasks = [asyncio.create_task(collect(sig, sig_seen)), asyncio.create_task(collect(par, par_seen))]
        await send(sig, type="ui_ready", view="phone")
        await send(sig, type="settings", language="nsl", voice="default")
        await asyncio.sleep(0.5)

        state = http("GET", f"{a.http}/rooms/{code}")
        check("GET /rooms/{code} lists signer + participant",
              sorted((x["name"], x["role"]) for x in state["participants"]) == [("Alice", "signer"), ("Bob", "participant")], state)
        m = await wait_for(par_seen, "room")
        check("participant gets room", m is not None and m["code"] == code)
        last_room = [x for x in sig_seen if x["type"] == "room"][-1:]
        check("signer gets room with both", bool(last_room) and len(last_room[0]["participants"]) == 2, last_room)

        # Participant speech -> captions everywhere, avatar_play to the signer only
        s0, p0 = len(sig_seen), len(par_seen)
        await send(par, type="speech_text", text="hello can you help me")
        m = await wait_for(sig_seen, "caption", s0)
        check("signer gets caption from participant", m is not None and m["speaker"] == "Bob" and m["text"] == "hello can you help me", m)
        m = await wait_for(sig_seen, "avatar_play", s0)
        check("signer gets avatar_play", m is not None and "signs" in m, m)
        m = await wait_for(par_seen, "caption", p0)
        check("participant gets own caption", m is not None and m["speaker"] == "Bob", m)
        check("participant gets no avatar_play", await wait_for(par_seen, "avatar_play", p0, timeout=0.5) is None)

        # Signer-side mic speech -> caption reaches participants too
        p0 = len(par_seen)
        await send(sig, type="speech_text", text="nice to meet you")
        m = await wait_for(par_seen, "caption", p0)
        check("participant gets caption from signer-side mic", m is not None and m["text"] == "nice to meet you" and m["speaker"] == "Phone mic", m)

        # Bad message never breaks the room
        await par.send("not json")
        await par.send(json.dumps({"type": "frame", "jpeg": "xx"}))
        await sig.send(json.dumps({"type": "frame", "jpeg": "!!notbase64"}))

        # Signed sentence -> caption + speak for participants
        folders = [Path(f) for f in a.frames]
        if all(f.is_dir() for f in folders):
            for folder in folders[:2]:
                since = len(sig_seen)
                await send(sig, type="teach_start", label="wave")
                await stream(sig, folder)
                check(f"teach_progress after {folder}", await wait_for(sig_seen, "teach_progress", since) is not None)
            since = len(sig_seen)
            await send(sig, type="teach_stop", label="wave")
            check("sign_learned", await wait_for(sig_seen, "sign_learned", since) is not None)
            s0, p0 = len(sig_seen), len(par_seen)
            await stream(sig, folders[2])
            m = await wait_for(sig_seen, "sentence", s0, timeout=6)
            check("signer gets sentence from Alice", m is not None and m["speaker"] == "Alice", m)
            cap = await wait_for(par_seen, "caption", p0, timeout=3)
            spk = await wait_for(par_seen, "speak", p0, timeout=3)
            check("participant gets the signer's sentence as a caption from Alice", cap is not None and cap["text"].strip() and cap["speaker"] == "Alice", cap)
            check("participant gets speak for the sentence", spk is not None and spk["text"].strip(), spk)
        else:
            print("SKIP  sentence checks (frame folders missing)")

        # Participant leaves -> signer still fine, gets room update
        s0 = len(sig_seen)
        await par.close()
        m = await wait_for(sig_seen, "room", s0)
        check("signer gets room after participant leaves", m is not None and len(m["participants"]) == 1, m)
        await send(sig, type="speech_text", text="still here")
        check("signer still served after participant left", await wait_for(sig_seen, "avatar_play", s0) is not None)
        for t in tasks:
            t.cancel()

    await asyncio.sleep(0.5)
    try:
        http("GET", f"{a.http}/rooms/{code}")
        check("room removed when empty", False)
    except urllib.error.HTTPError as e:
        check("room removed when empty", e.code == 404, e.code)

    print(f"\n{sum(results)}/{len(results)} passed")
    raise SystemExit(0 if all(results) else 1)


if __name__ == "__main__":
    asyncio.run(main())
