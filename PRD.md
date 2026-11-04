# InSync PRD

AI accessibility meeting rooms for Deaf signers and hearing people. One signer on the mobile app,
up to about 4 participants in a browser. Signs become captions and voice for the room; speech becomes
captions and an avatar signing back to the signer.

## Product

InSync is an accessibility meeting room. One Deaf signer on the phone app, up to about 4 hearing participants
who join from any browser with the https link. The signer's signs become captions and spoken audio for the
participants; participants' speech becomes captions and an avatar signing back on the signer's phone.

- **Instant room.** Opening the app lands the signer in an active room with a code and a share link
  (`https://insync.13-216-97-225.sslip.io/join/<CODE>`). No setup beyond first-run onboarding (name, voice,
  sign language). Tapping the room line ("Room CODE · N participants") copies the link.
- **Join from anywhere.** Participants open the link in a browser (desktop or phone). No app, no account.
- **One shared camera.** The signer is the only one whose camera (the "screen") is used. The glasses camera,
  or the phone camera when no glasses are connected, watches the signer. Recognised signs become text. The
  signer sees a live mirror preview of what the camera sees, the room captions, and the avatar signing back
  what hearing people say.
- **Participant side (browser).** The mic (or a text box) sends speech. Participants see who is in the room,
  whether the signer is live, captions of everything said and signed under each speaker's name, and hear the
  signer's words as AI voice ("Speak captions aloud", on by default). They never need the avatar.
- **Phone mic.** A hearing person next to the signer can talk into the phone; it shows as "Phone mic".
- **Teaching.** The signer can teach a custom sign for a word (two takes, live or from a video). Taught
  signs work in every room the signer opens.
- **Language is a setting**, not the product. The signer picks their sign language (NSL, ASL or BSL; `nsl`,
  `ase`, `bfi`) in the profile; it only selects the sign library and avatar vocabulary.
- **Status is always honest.** The app shows the camera source and state in plain words: phone camera,
  glasses connected, glasses not worn, waiting for glasses, paused.

## Roles in a room

| Role | Where | Sends | Receives |
|---|---|---|---|
| signer (1) | mobile app (WebView on `/app`) | camera frames, teach commands, settings, phone-mic speech | captions, avatar_play, landmarks, sign events, `sentence {speaker: signer name}` |
| participant (up to ~4) | any browser, `/join/<CODE>` | speech text (browser STT or typed) | room list, captions, sentences to speak aloud |

A room has exactly one signer, who is the only shared camera, and a handful of participants (sized for about 4).
Captions carry the speaker's name: the signer's name, the participant's name, or "Phone mic".
Later: more than one signer per room.

## Architecture

- **Hosted.** The backend and both web pages are served by us at `https://insync.13-216-97-225.sslip.io`
  (Caddy https in front of FastAPI on EC2): signer page at `/app`, participant page at `/join/<CODE>`.
- `app/` Flutter. Splash, room creation, WebView on the hosted `/app` for the signer UI, native bridge (TTS,
  STT, camera stream, WebSocket, `serviceBase`). Creates the room on launch and shows the code and link.
- `backend/` FastAPI. Room server: `/ws?room=<code>&role=signer|participant&name=<name>`. Per room: one
  recognition session for the signer (frames, segmentation, matching, teaching; it names the signer on its
  sentences) and a broadcast to participants. Library in `tools/data/signs/<language>/`.
- `web/dist/index.html` Signer view. There is no Vite source: this single built file is the source we maintain,
  edited with literal find/replace and logged in `web/EDITS.md`.
- `backend/static/join.html` Participant view, a single hand-written file with no external resources.
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
