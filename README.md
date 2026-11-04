![InSync](web/brand/insync-lockup.svg#gh-dark-mode-only)
![InSync](web/brand/insync-lockup-light.svg#gh-light-mode-only)

# InSync

InSync is an accessibility meeting room. A Deaf signer joins from the phone app (Ray-Ban Meta glasses
or the phone camera) or from any browser with a webcam; hearing people join with a link. Signs become
captions and voice for the room. Speech becomes captions and an avatar signing back to the signer.

Live: https://insync.13-216-97-225.sslip.io (signer UI at `/app`, participants at `/join/<CODE>`,
where `<CODE>` is the 4-letter room code). Product spec: [PRD.md](https://github.com/acgodson/insync/blob/main/PRD.md).

## How it works

```
SIGNER -> ROOM
 Ray-Ban Meta glasses (Meta Wearables Device Access Toolkit)  ┐
 phone camera (Mock Device Kit) | browser webcam              ┴─> JPEG frames, ~10 fps, over /ws
   -> MediaPipe Hand Landmarker (2 hands x 21 points x 3)
   -> live segmenter (a sign ends when the hands leave or hold still > 0.5 s)
   -> features: 32 resampled frames x 138 values (126 hand + 12 location)
   -> nearest neighbour against the taught sign library (cosine or DTW, k-NN vote, k=5)
   -> top-3 sign_candidates
   -> language module: Claude picks the sign in context when the top match is not clear,
      and composes the English sentence after the signer pauses
   -> sentence -> ElevenLabs voice (speech_audio)
   -> room broadcast: caption + speak + speech_audio to every participant

ROOM -> SIGNER
 participant mic (browser STT) or typed text, or the phone mic  -> speech_text
   -> caption to everyone
   -> Claude gloss (English -> signs from the vocabulary only) -> avatar_play
   -> the avatar signs it in the signer's UI (unknown words are fingerspelled)
```

Details that matter:

- One room has one signer (the shared camera) and a few participants. Rooms live in memory.
- The service sends the detected hand landmarks back as `landmarks`, so both the signer and the
  participants see the hand skeleton drawn over the signer's video.
- Teaching: the signer records a new sign twice (`TAKES_REQUIRED=2`), live or from an uploaded video.
  The takes are appended to `tools/data/signs/<language>/<label>.json` and work in every room.
- Claude can only return signs in the vocabulary (a JSON-schema enum), so it cannot invent a sign.
- Language is a setting (NSL, ASL, BSL as `nsl`, `ase`, `bfi`); it picks the sign library.

Matching benchmark on the Kaggle [asl-signs](https://www.kaggle.com/competitions/asl-signs) data,
leave-one-out over the 8 default signs found in the dataset (391 takes, 21 participants), from
[tools/README.md](https://github.com/acgodson/insync/blob/main/tools/README.md):

| | cosine | DTW |
|---|---|---|
| hand shape only (`--no-location`) | 54.5% | 61.4% |
| + location | 62.1% | 66.5% |
| + location, `--k 5` | 65.5% | 69.3% |

This measures the matching method on webcam selfie footage. It is an upper bound for first-person
glasses footage, where the body is rarely in view and the location features are mostly zero.

## Where the code is

| File | What it does |
|---|---|
| [backend/main.py](https://github.com/acgodson/insync/blob/main/backend/main.py) | FastAPI routes: `/rooms`, `/app`, `/join/<code>`, `/teach/upload`, `/library`, and the `/ws` WebSocket |
| [backend/rooms.py](https://github.com/acgodson/insync/blob/main/backend/rooms.py) | Room codes, signer and participant joins, routing of each message to the right people |
| [backend/session.py](https://github.com/acgodson/insync/blob/main/backend/session.py) | Per-signer pipeline: frame worker, recognition, teaching, speech to avatar, status |
| [backend/pipeline.py](https://github.com/acgodson/insync/blob/main/backend/pipeline.py) | Hand landmarks, the incremental live segmenter, feature building, library loading and ranking |
| [backend/language/module.py](https://github.com/acgodson/insync/blob/main/backend/language/module.py) | Ephraim's language module surface: sign choice in context, sentence composition, gloss, TTS ([README](https://github.com/acgodson/insync/blob/main/backend/language/README.md)) |
| [backend/static/join.html](https://github.com/acgodson/insync/blob/main/backend/static/join.html) | Lightweight participant page at `/join-lite/<code>`, one file, no external resources |
| [web/dist/index.html](https://github.com/acgodson/insync/blob/main/web/dist/index.html) | The hosted UI (Femi's build) wired to the service; every wiring edit is logged in [web/EDITS.md](https://github.com/acgodson/insync/blob/main/web/EDITS.md) |
| [app/lib/home_screen.dart](https://github.com/acgodson/insync/blob/main/app/lib/home_screen.dart) | Flutter: WebView and `window.insync` bridge, room creation, frame forwarding at 10 fps |
| [app/android/.../MainActivity.kt](https://github.com/acgodson/insync/blob/main/app/android/app/src/main/kotlin/com/insync/app/MainActivity.kt) | Meta Wearables registration and session, glasses camera stream, Mock Device Kit phone-camera fallback, YUV to JPEG |
| [tools/extract.py](https://github.com/acgodson/insync/blob/main/tools/extract.py) | MediaPipe Holistic landmarks from a folder of frames (Hand Landmarker fallback) |
| [tools/segment.py](https://github.com/acgodson/insync/blob/main/tools/segment.py) | Splits a sequence into signs, normalises, resamples to 32 frames, adds location features |
| [tools/match.py](https://github.com/acgodson/insync/blob/main/tools/match.py) | Cosine / DTW matching, k-NN vote, leave-one-out self-test |
| [tools/import_kaggle.py](https://github.com/acgodson/insync/blob/main/tools/import_kaggle.py) | Builds an `ase` library from the Kaggle asl-signs dataset for the benchmark |
| [deploy/deploy.sh](https://github.com/acgodson/insync/blob/main/deploy/deploy.sh) | One-command EC2 deploy: rsync, venv, MediaPipe models, systemd, Caddy https |
| [PRD.md](https://github.com/acgodson/insync/blob/main/PRD.md) | Product, roles, architecture, message contract |

## Message contract

JSON over WebSocket at `/ws?room=<code>&role=signer|participant&name=<name>`. Every message has
`type` and `ts`. The main types:

| Type | Direction | Meaning |
|---|---|---|
| `frame {jpeg, w, h, ts}` | signer -> service | One camera frame |
| `speech_text {text}` | signer or participant -> service | Speech (phone mic, browser STT or typed) |
| `teach_start {label}` / `teach_stop {label}` | signer -> service | Record a take / save the taught sign |
| `settings {language, voice}`, `session {state}` | signer -> service | Profile, pause and resume |
| `room {code, participants}` | service -> all | On every join or leave |
| `landmarks {hands, w, h}` | service -> all | Hand points for each frame |
| `sign_candidates`, `sign_recognized`, `unknown_sign` | service -> signer | Recognition results |
| `sentence {speaker, text}` | service -> signer | The composed sentence from the signs |
| `caption {speaker, text}`, `speak {text}` | service -> participants | Captions, and the signer's sentences to voice |
| `speech_audio {audio, format, text}` | service -> all | ElevenLabs audio of the signer's sentence |
| `avatar_play {signs, fingerspell}` | service -> signer | Signs for the avatar to play |
| `teach_progress`, `sign_learned`, `status` | service -> signer | Teaching progress, latency and fps |

Full routing table: [backend/README.md](https://github.com/acgodson/insync/blob/main/backend/README.md).

## Run it

Backend (the MediaPipe models must be in `tools/models/`, see [tools/README.md](https://github.com/acgodson/insync/blob/main/tools/README.md)):

```
cd backend
python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt
ANTHROPIC_API_KEY=... ELEVENLABS_API_KEY=... .venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
```

Env: `CONFIDENCE_THRESHOLD` (0.6), `TAKES_REQUIRED` (2), `LIBRARY_DIR`, `MATCH_DTW=1`, `MATCH_K` (5).
Language module settings are in [backend/language/README.md](https://github.com/acgodson/insync/blob/main/backend/language/README.md).

Replay recorded frames (from the app's Record mode) against the running service:

```
.venv/bin/python tests/replay.py --teach wave <take1_folder> <take2_folder> <query_folder>
.venv/bin/python tests/replay.py --room ABCD <frames_folder>
.venv/bin/python tests/replay.py --participant Bob --room ABCD --speech "hi"
```

Tools and the benchmark:

```
cd tools && python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
python selftest.py
python import_kaggle.py
python match.py --library data/signs/ase --self-test --dtw --k 5
```

App (JDK 17, Android SDK 36, Meta AI app with Developer Mode for the glasses):

```
cd app
flutter build apk --debug
adb install -r build/app/outputs/flutter-apk/app-debug.apk
```

Deploy: `./deploy/deploy.sh`.

## Team

- Godson: app, backend, tools, deploy.
- Ephraim: language and voice module ([backend/language/](https://github.com/acgodson/insync/blob/main/backend/language/README.md)).
- Femi: web UI.

Built on the Meta Wearables Device Access Toolkit, MediaPipe, Anthropic Claude, ElevenLabs, and the
Kaggle asl-signs dataset.
