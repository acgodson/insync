# InSync service

FastAPI service implementing the InSync message contract. Wraps `tools/` (feature builder,
segmenter, matcher) without copying it. Library lives in `tools/data/signs/<language>/`.

## Setup

```
cd backend
python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

The MediaPipe models must exist in `tools/models/` (`hand_landmarker.task`, `holistic_landmarker.task`;
see `tools/README.md`).

## Run the service

```
cd backend && .venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
```

Env: `CONFIDENCE_THRESHOLD` (default 0.6, set 0 for the skeleton), `TAKES_REQUIRED` (2),
`LIBRARY_DIR`, `MATCH_DTW=1` (DTW instead of cosine), `MATCH_K` (5).

## Rooms

A room has a 4-letter code, one signer (the app, owns the recognition session) and a handful of
browser participants (sized for about 4, not enforced). Rooms live in memory and disappear when the last person leaves.

```
curl -X POST http://<host>:8000/rooms      # {"code": "KMPX", "link": "http://<host>:8000/join/KMPX"}
curl http://<host>:8000/rooms/KMPX         # {"code", "participants": [{"name", "role"}]} or 404
```

WebSocket: `/ws?room=<code>&role=signer|participant&name=<name>`.

- Signer with an unknown code creates the room; a second signer replaces the first (closed with 4000).
- Participant with an unknown code is closed with 4404.
- No `room` param: a private room is created for the connection (old clients and `replay.py` work as before).

Routing:

| Event | Signer gets | Participants get |
|---|---|---|
| any join or leave | `room {code, participants}` | `room {code, participants}` |
| signer's recognised `sentence` | `sentence {speaker: signer name}` (and all other session messages) | `caption {speaker: signer name, text}`, `speak {text}` |
| signer-side `speech_text` (phone mic) | `caption {speaker: "Phone mic"}`, `avatar_play` | `caption {speaker: "Phone mic"}` |
| participant `speech_text {text}` | `caption {speaker: participant name}`, `avatar_play` | `caption {speaker: participant name}` |

`status`, `landmarks`, sign events and teaching stay signer-only.

## Join page

Participants open `http://<host>:8000/join/<code>` (`static/join.html`, single file). It asks for a name
(kept in localStorage), shows the room code, the people in the room (signer marked), whether the signer is
live, and the captions (newest at the bottom). It speaks the signer's sentences with the browser's
speech synthesis ("Speak captions aloud" toggle, on by default), and sends speech from the mic button (Chrome/Safari `webkitSpeechRecognition`) or the
text box. Reconnects every 2 s. Mic recognition needs `localhost` or https in most browsers; on a LAN IP
over plain http use the text box.

## Replay recorded frames

Frame folders come from the app's Record mode (`frame_<ms>.jpg`, 504x896).

```
.venv/bin/python tests/replay.py --teach wave <take1_folder> <take2_folder> <query_folder>
.venv/bin/python tests/replay.py <frames_folder>
.venv/bin/python tests/replay.py --room ABCD <frames_folder>                  # as the signer of room ABCD
.venv/bin/python tests/replay.py --participant Bob --room ABCD --speech "hi"  # join as a participant
```

## Room test

With the service running (`CONFIDENCE_THRESHOLD=0`):

```
.venv/bin/python tests/test_rooms.py    # uses /tmp/wave1 /tmp/wave2 /tmp/wave3 if present (--frames to change)
```

It teaches `wave` again each run (two more takes appended to the library).

## Upload a video as one take

```
curl -F label=wave -F language=nsl -F file=@wave.mp4 http://localhost:8000/teach/upload
curl http://localhost:8000/library?language=nsl
```

Uploaded videos are deleted after processing; frames are never stored.
