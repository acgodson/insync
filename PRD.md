# InSync PRD

AI accessibility meeting rooms for Deaf signers and hearing people. One signer on the mobile app,
any number of participants in a browser. Signs become captions and voice for the room; speech becomes
captions and an avatar signing back to the signer.

## Product

- **Instant room.** Opening the app lands the signer in an active room with a code and a share link.
  No setup beyond first-run onboarding (name, voice, sign language).
- **Join from anywhere.** Participants open the link in a browser (desktop or phone). No app, no account.
- **Signer side (mobile app).** The glasses camera, or the phone camera when no glasses are connected,
  watches the signer. Recognised signs become text. The signer sees a live mirror preview of what the
  camera sees, the room captions, and the avatar signing back what hearing people say.
- **Participant side (browser).** The mic captures speech. Participants see captions of everything said
  and signed, and hear the signer's words as AI voice. They never need the avatar.
- **Teaching.** The signer can teach a custom sign for a word (two takes, live or from a video). Taught
  signs work in every room the signer opens.
- **Language is a setting**, not the product. NSL, ASL and BSL (`nsl`, `ase`, `bfi`) are chosen in the
  signer's profile and only select the sign library and avatar vocabulary.
- **Status is always honest.** The app shows the camera source and state in plain words: phone camera,
  glasses connected, glasses not worn, waiting for glasses, paused.

## Roles in a room

| Role | Where | Sends | Receives |
|---|---|---|---|
| signer | mobile app | camera frames, teach commands, settings | captions, avatar_play, landmarks, sign events |
| participant | browser | speech text (STT in the browser or app) | captions, sentences to speak aloud |

A room has exactly one signer and any number of participants. Later: more than one signer per room.

## Architecture

- `app/` Flutter. Splash, room creation, WebView for the signer UI, native bridge (TTS, STT, camera
  stream, WebSocket). Creates the room on launch and shows the code and link.
- `backend/` FastAPI. Room server: `/ws?room=<code>&role=signer|participant`. Per room: one recognition
  session for the signer (frames, segmentation, matching, teaching) and a broadcast to participants.
  Library in `tools/data/signs/<language>/`.
- `web/` Signer view (inside the app) and participant view (browser, join by link). We own this code
  fully; the teammate's build was the starting point and is reshaped to fit this product.
- `tools/` Feature builder, segmenter, matcher, dataset benchmark. Unchanged by the product pivot.

## Message contract (room edition)

Every message carries `type` and `ts`. JSON over WebSocket. The Phase 1 contract stays; these are the
room additions.

- Join: `ws://<host>:8000/ws?room=<code>&role=signer|participant&name=<display name>`
- Service → all: `room {code, participants: [{name, role}]}` on every join or leave.
- Service → participants: `caption {speaker, text}` for everything, and `speak {text}` for the signer's
  sentences so the browser or app can voice them.
- Service → signer: `caption`, `avatar_play`, `landmarks`, `sign_candidates`, `sign_recognized`,
  `unknown_sign`, `teach_progress`, `sign_learned`, `status`.
- Participant → service: `speech_text {text}`.
- HTTP: `POST /rooms` creates a room and returns `{code, link}`; `GET /rooms/<code>` returns its state.

## Out of scope for now

Real recognition quality, cloud TTS/STT (ElevenLabs), the Claude context step, hologram view,
replaying recorded landmarks on the avatar, iOS, auth, deployment, more than one signer per room.
`// TODO(phase2)` marks the plug-in points.

## Phases

1. Backend service: contract, live segmentation, teaching, replay. **Done.**
2. App: rename, splash, WebView bridge, mock camera to service. **Done.**
3. Rooms: room server in the backend, room creation and link in the app, participant view in the
   browser, signer view wired to the live service, camera mirror preview and honest status line. **Done.**
4. Deployment: EC2 (us-east-1, profile `regina`) behind Caddy https at
   `https://insync.13-216-97-225.sslip.io`; `./deploy/deploy.sh` redeploys. **Done (placeholder hostname).**
5. Later: real domain, ElevenLabs voice, Claude ordering, multiple signers.
