# InSync

AI accessibility meeting rooms: one Deaf signer on the phone app, hearing participants in any
browser. Signs become captions and voice; speech becomes captions and an avatar signing back.
See `PRD.md` for the product and `deploy/` for the live service.

| Folder | What |
|---|---|
| `app/` | Flutter app (glasses or phone camera, WebView UI, native speech, room client) |
| `backend/` | FastAPI room server, recognition session, and `backend/language/` (Ephraim's language & voice module) |
| `tools/` | Landmark extraction, segmentation, matching, dataset benchmark |
| `web/` | Hosted web UI: signer page (`web/dist/index.html`) and the participant join page (`backend/static/join.html`) |
| `deploy/` | EC2 deploy script, systemd unit, Caddy config |

Live: https://insync.13-216-97-225.sslip.io (signer UI at `/app`, join links at `/join/<CODE>`).

---

# Almero — Language & Voice (`backend/language/`)

Cluster C of Almero, the two-way interpreter between a Deaf signer and a hearing speaker.
This module is the part that **understands and voices language**: it turns Bob's speech into
signs for the avatar, and Alice's signs into spoken English for Bob.

**Owner:** Ephraim · **Standalone test:** `python -m language.cli` · **Status:** standalone done, ready to integrate

> **Teammates:** jump to [Instructions for teammates](#instructions-for-teammates). Find your name, follow your section.

---

## Contents

1. [What this module does](#what-this-module-does)
2. [Quick start](#quick-start)
3. [How it works](#how-it-works)
4. [Files](#files)
5. [Testing](#testing)
6. [Running it as a service](#running-it-as-a-service)
7. [Instructions for teammates](#instructions-for-teammates)
8. [The contract](#the-contract)
9. [Vocabulary](#vocabulary)
10. [Claude](#claude)
11. [Voices (TTS)](#voices-tts)
12. [Signer recording sessions](#signer-recording-sessions)
13. [Configuration](#configuration)
14. [Troubleshooting](#troubleshooting)
15. [Open decisions](#open-decisions)

---

## What this module does

| Direction | Input | This module | Output |
|---|---|---|---|
| **Bob → Alice** | Bob's voice (16 kHz audio from the app) | Detects where speech starts and ends, transcribes it with Whisper, asks Claude for the right signs in the right order | `caption` (text for Alice), then `avatar_play` (signs for the avatar) |
| **Alice → Bob** | Recognition's top-3 guesses per sign | Picks the right sign using conversation context, waits for Alice to finish, asks Claude for the English sentence, voices it | `sign_recognized`, then `sentence` (+ `speech_audio` with Alice's voice) |

It also owns the **sign vocabulary** (`vocab.json`), shared by both directions and by recognition, and the **signer recording sessions**: consent, shot lists and take tracking for building the sign library.

What it does **not** do: see hands (recognition, Cluster B), draw the avatar (web UI, Cluster A), or talk to the glasses (the app).

---

## Quick start

**Windows (PowerShell)**, from the `backend` folder. Use the official Python from python.org, not MSYS2: MSYS2's Python can't install the prebuilt packages.

```powershell
py -3.12 -m venv .venv
Set-ExecutionPolicy -Scope Process Bypass -Force
.\.venv\Scripts\Activate.ps1
pip install -r language\requirements.txt

python -m pytest -q language\tests                                    # 54 passed
python -m language.cli --offline --tts none --script language\eval\demo_script.txt
```

**macOS / Linux**

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r language/requirements.txt
python -m pytest -q language/tests
python -m language.cli --offline --tts none --script language/eval/demo_script.txt
```

Optional extras: `ffmpeg` for audio files and local playback (`winget install Gyan.FFmpeg`, `brew install ffmpeg`), and `pip install sounddevice` for the microphone.

Then add keys to switch on the real thing:

```powershell
$env:ANTHROPIC_API_KEY = "sk-ant-..."     # Claude
$env:ELEVENLABS_API_KEY = "sk_..."        # optional: Alice's ElevenLabs voice
```

Keys live in environment variables only. Never commit them or paste them in chat.

---

## How it works

```
BOB → ALICE
 app `audio` (100 ms chunks) ─▶ Endpointer (VAD, 700 ms silence = end) ─▶ Whisper base.en
   ─▶ `caption` ─▶ Claude: English → signs (vocab-only) ─▶ `avatar_play`

ALICE → BOB
 recognition top-3 ─▶ confident? keep top-1 : Claude picks using context ─▶ `sign_recognized`
   ─▶ 1.5 s pause (or an emergency sign: immediately)
   ─▶ Claude: signs → English ─▶ `sentence` ─▶ ElevenLabs / edge / system voice ─▶ `speech_audio`
```

Design choices that matter for the demo:

- **Claude can only return signs we have clips for.** The vocabulary is a JSON-schema `enum` in Claude's structured output, so an invented sign is impossible.
- **Claude is only called when needed.** A sign at ≥ 0.80 confidence with a 0.15 lead skips Claude. A single viable candidate skips it too.
- **Emergencies never wait.** HELP, FIRE, PAIN, CANT-BREATHE and STOP are spoken at once with a canned sentence, with no pause and no network. Their audio is pre-rendered to disk in Alice's voice at startup.
- **Nothing single-points-of-failure the demo.** If Claude times out (4 s), rule-based fallbacks answer. If ElevenLabs fails, edge-tts then the system voice take over, and a circuit breaker skips a failing service for 60 s instead of stalling every sentence.
- **Text before media.** `caption` is sent before the gloss; `sentence` before its audio. Nobody waits on the slow part to read.

**Latency** (measured on one CPU core, no GPU): end-of-speech detection 700 ms, Whisper `base.en` ~0.9 s for a 6 s utterance, signed-sentence pause 1.5 s. The speech direction is 1.7–2.7 s before Claude, so Claude's p95 needs to stay under about 1 s to meet the 3 s target. Check it with the eval.

---

## Files

| File | Purpose |
|---|---|
| `module.py` | **`LanguageModule`**, the only class integration touches |
| `server.py` | WebSocket server speaking the contract (`uvicorn language.server:app`), plus `/health` and `/vocab` |
| `fake_app.py` | Pretends to be the phone app or a UI over the real socket |
| `cli.py` | The CLI loop: interactive or scripted, optional JSONL log |
| `vocab.json`, `vocab.py` | The sign vocabulary; live-taught signs persist to `vocab.local.json` |
| `prompts.py` | The three Claude prompts and their schemas |
| `claude_client.py` | Async Claude client: structured outputs, timeout, one retry |
| `gloss.py` | English → signs (Claude + validation + rule-based fallback) |
| `interpret.py` | Signs → English: candidate picking and sentence composition |
| `conversation.py` | Rolling history shared by every Claude call |
| `stt.py` | Endpointer (VAD) and faster-whisper |
| `tts.py` | ElevenLabs → edge-tts → system voice; breaker, caches, voice switching |
| `contract.py` | Builders for every message this module emits |
| `config.py` | Every setting, overridable with environment variables |
| `sessions.py` | Signer recording sessions: consent, plan, run, status |
| `eval/` | `demo_script.txt`, `cases.json`, `run_eval.py` (prompt accuracy and latency) |
| `tests/` | 54 offline tests: no keys, no network, about 1 s |
| `TTS_INTEGRATION.md` | Voice delivery for the app, with a Flutter sketch |
| `SIGNER_SESSIONS.md` | The recording protocol for sessions with signers |

---

## Testing

Five levels, each needing a little more. A step-by-step version of all of this, including the network setup, is in the **setup guide doc** (ask Ephraim for the link).

| Level | Command | Needs | Proves |
|---|---|---|---|
| 1 | `python -m pytest -q language/tests` | nothing | Contract, vocab, fallbacks, VAD, server, request formats |
| 2 | `python -m language.cli --offline --tts none --script language/eval/demo_script.txt` | nothing | The whole demo flow, offline |
| 3 | `python -m language.eval.run_eval` | Anthropic key | Claude accuracy and p95 latency |
| 4 | `python -m language.cli` then `mic 5`, `wav <file>`, `sign …` | microphone or audio file | Real speech end to end |
| 5 | `python -m language.cli --tts-mode local` then `voices`, `voice <id>`, `speak …` | ElevenLabs key | Alice's voice |

**CLI commands:** `say <text>` (Bob, typed) · `mic <seconds>` · `wav <file>` · `sign HELLO` · `sign WANT:.70 NEED:.66` (unsure recognition) · `end` · `teach LABEL english` · `voices [search]` · `voice <id>` · `speak <text>` · `setting <text>` · `history` · `vocab` · `reset` · `quit`. Type commands without `#` comments: the CLI would read them as speech.

**What good eval results look like:** gloss ≥ 10/11, pick ≥ 3/4 (the offline baseline is 0/4 by design: those cases need context), compose ≥ 5/6, and p95 under ~1,000 ms per call.

---

## Running it as a service

```powershell
$env:ANTHROPIC_API_KEY = "sk-ant-..."
$env:ALMERO_TTS_MODE = "service"        # backend sends speech_audio; "app" = phone speaks itself
$env:ALMERO_NAMES = "Alice,Chidi"
uvicorn language.server:app --host 0.0.0.0 --port 8000
```

| Endpoint | What it gives |
|---|---|
| `ws://<laptop-ip>:8000/ws` | The contract, both ways |
| `GET /health` | Claude on/off, voice chain, signs, connected clients |
| `GET /vocab` | Every sign label with its English meaning, tier and emergency flag |

Test it without anyone else's code, from a second window:

```powershell
python -m language.fake_app --play                         # acts as the phone app
python -m language.fake_app --view projector               # acts as the web UI
python -m language.fake_app --script language\eval\demo_script.txt --play
```

**Network checklist for other devices:** use the laptop's IP from `ipconfig`, never `localhost`; open port 8000 once (`New-NetFirewallRule -DisplayName "Almero 8000" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow`, as Administrator); keep every device on one network. Venue Wi-Fi often blocks devices from reaching each other, so a phone hotspot is the safe choice. If `http://<ip>:8000/health` opens in the phone's browser, everything can connect.

This server runs the language module alone. In the final backend the same wiring moves into `main.py` (see [Dubem's section](#dubem--integration-and-the-flutter-app)).

---

## Instructions for teammates

### Everyone

- **Vocabulary is shared.** `vocab.json` is the one list of signs. Recognition's labels, the avatar's clip names and Claude's choices all use these exact labels: UPPERCASE, hyphens for multi-word (`THANK-YOU`, `CANT-BREATHE`). Get the live list from `GET /vocab`.
- **Speakers** in messages are `"alice"` (the signer) and `"bob"` (the hearing person).
- **Before connecting real code**, connect to `fake_app` traffic or replay `demo.jsonl` (below). Both produce exactly what the live server sends.
- **Keys** stay on the backend laptop. No client ever needs one.

### Femi & Yuki — web UI

1. **Connect and say who you are:**

    ```ts
    const ws = new WebSocket(`ws://${host}:8000/ws`);
    ws.onopen = () => ws.send(JSON.stringify({ type: 'ui_ready', ts: Date.now(), view: 'projector' })); // or 'phone'
    ws.onmessage = (e) => handle(JSON.parse(e.data));
    ```

2. **Render these messages:**

    | Message | Render |
    |---|---|
    | `caption` {text, speaker:"bob"} | Bob's words as a caption, shown before the avatar starts |
    | `avatar_play` {signs, fingerspell} | Play each clip in `signs` in order, then fingerspell each word in `fingerspell` letter by letter (A–Z, 0–9) |
    | `sign_recognized` {label, confidence} | Live feedback while Alice signs |
    | `sentence` {text, speaker:"alice"} | Alice's sentence as a caption for Bob |
    | `unknown_sign` | The "I don't know this sign yet — teach it?" prompt |
    | `status` {latency_ms, fps} | Debug overlay. `fps` is `null` from this module |
    | `speech_audio` | **Ignore.** Only the phone plays audio, or Bob hears an echo |

3. **Name avatar clips by label:** one clip per label in `vocab.json` (`HELLO`, `THANK-YOU`…) plus one per letter for fingerspelling. Signs taught live arrive as new labels; plan a fallback (fingerspell the label) for a label with no clip yet.
4. **Mock without the backend:** Ephraim's `demo.jsonl` has one real message per line. Replay it in `mock.ts` in order, spaced by the differences in `ts`.
5. **Ordering caveat:** the frozen contract splits `signs` and `fingerspell`, so "HELLO [ADA] WHAT" loses its order. If the team adopts the proposed `sequence` field (`ALMERO_EMIT_SEQUENCE=1`), play `sequence` instead: `[{kind:"sign"|"fingerspell", value}]`.

### Dubem — integration and the Flutter app

**Merge into `main.py`.** `server.py` is the reference; the essentials are:

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from language import LanguageModule

@asynccontextmanager
async def lifespan(app):
    app.state.lang = LanguageModule(emit=hub.broadcast)   # your broadcast to app + web UI (sync or async)
    await app.state.lang.start()                          # loads Whisper (~3 s), pre-renders emergency audio
    yield
    await app.state.lang.close()

app = FastAPI(lifespan=lifespan)

# WebSocket handler, for each message from the app:
if msg["type"] in ("audio", "teach_stop", "profile"):
    await app.state.lang.handle(msg)
```

Whisper runs in a thread pool and Claude calls are async, so the event loop stays free for frames. Utterances stay in order per direction.

**What the app sends to this module:**

| Message | When | Format |
|---|---|---|
| `profile` {head, voice_id?} | On connect | `voice_id` (proposed, optional): Alice's ElevenLabs voice |
| `audio` {pcm, rate} | While the mic is on | 16-bit little-endian **mono PCM at 16 kHz**, base64, ~100 ms (3,200 bytes) per message. Other rates are resampled |
| `teach_stop` {label, english?} | After teaching a sign | `english` (proposed, optional); without it the label is used as the word |

**Alice's voice on the phone.** Pick one mode for the demo:

- `ALMERO_TTS_MODE=service` (needed for ElevenLabs): after each `sentence`, the backend sends `speech_audio` {audio (base64 MP3), format, text}. Play it on the **phone speaker**. If none arrives within ~2 s of the `sentence`, speak the text with the phone's TTS and ignore the late audio. Dart sketch in `TTS_INTEGRATION.md`.
- `ALMERO_TTS_MODE=app`: no audio is sent; speak every `sentence` from Alice with the phone's TTS.

**Android gotcha:** a blank WebView with `net::ERR_CLEARTEXT_NOT_PERMITTED` means plain `http://` to the laptop is blocked. Allow cleartext for the hackathon build.

### Martins (and Dubem) — recognition

1. **Hand over each segmented sign** with its top 3 candidates:

    ```python
    await lang.on_sign_candidates([{"label": "WATER", "confidence": 0.71},
                                   {"label": "NAME",  "confidence": 0.66},
                                   {"label": "BOOK",  "confidence": 0.30}])
    ```

2. **Labels** must match `vocab.json` exactly. Load it (or `GET /vocab`) instead of keeping a second list.
3. **Confidence is 0–1.** Below 0.45 → `unknown_sign`. At ≥ 0.80 with a 0.15 lead → accepted without Claude. If your similarity scores sit on another scale, tune `ALMERO_MIN_CONF`, `ALMERO_ACCEPT_CONF` and `ALMERO_ACCEPT_MARGIN` together with Ephraim rather than rescaling in code.
4. **Don't emit** `sign_recognized`, `unknown_sign` or `sentence`; this module emits them after the context step. Recognition emits `landmarks` and computes `sign_candidates`.
5. **Teach it live:** on `teach_stop`, you add the recording to the library and this module adds the label to the vocabulary (saved to `vocab.local.json`), so it's usable in both directions at once.
6. **Testing before the merge:** send `{"type": "sign_candidates", "ts": …, "items": [...]}` to the running language server over the WebSocket.
7. **Recording sessions:** Ephraim runs them with `sessions.py`. If your recorder has a CLI, it plugs in with `--on-take "python -m recognition.record --label {label} --take {take} --signer {signer}"`. Proposed layout: `data/signs/<LABEL>/<signer>_t<n>.*`.

### Milestone 3: "hello" both directions, on real devices

1. Start the backend with `ALMERO_TTS_MODE=service`.
2. Open the web UI on the projector, pointed at `ws://<laptop-ip>:8000/ws`.
3. Start the app on the phone. `/health` should list `app` and `projector`.
4. Bob says "Hello": caption, then the avatar signs HELLO.
5. Alice signs HELLO: `sign_recognized`, then ~1.5 s later the phone says "Hello!" in Alice's voice.
6. Check `latency_ms` on the debug overlay: target under 3,000 ms each way.

No recognition yet? Do step 5 from a laptop with `python -m language.fake_app` and `sign HELLO`.

---

## The contract

All messages carry `type` and `ts` (ms since epoch). Rows marked **proposed** need sign-off from integration before the app relies on them.

| Direction | Type | Fields | |
|---|---|---|---|
| App → service | `audio` | pcm, rate | |
| App → service | `profile` | head, voice_id | voice_id proposed |
| App → service | `teach_stop` | label, english | english proposed |
| Web UI → service | `ui_ready` | view | |
| Recognition → language | `sign_candidates` | items [{label, confidence}] | in-process call |
| Service → all | `caption` | text, speaker | |
| Service → all | `avatar_play` | signs, fingerspell, sequence | sequence proposed, off by default |
| Service → all | `sign_recognized` | label, confidence | |
| Service → all | `unknown_sign` | — | |
| Service → all | `sentence` | text, speaker | |
| Service → all | `status` | latency_ms, fps | |
| Service → app | `speech_audio` | audio, format, text | **proposed**, only with `TTS_MODE=service` |

Dev-only types used by `fake_app` and never by real clients: `dev_say`, `dev_end`, `dev_flush_audio`. `frame`, `motion` and `teach_start` are recognition's; this module ignores them safely.

---

## Vocabulary

`vocab.json` holds 52 signs in three tiers, which also set recording priority:

| Tier | Signs | Meaning |
|---|---|---|
| 1 | 10 | First to record (milestone 1): HELLO, THANK-YOU, YES, NO, NAME, I, YOU, HELP, PAIN, FIRE |
| 2 | 28 | The demo set (38 with tier 1): greetings, questions, classroom, needs, emergencies |
| 3 | 14 | Stretch |

Each entry has a `label`, an `english` meaning, `synonyms` (used by the fallback and shown to Claude), a `category`, a `tier`, an `emergency` flag and, for some, a canned `speak` sentence.

- **Add a sign:** add an entry, keep the label format, and tell recognition and the web UI so the recording and the clip exist.
- **`grammar_notes` are placeholders** that go straight into Claude's prompts. Our native signer must review them, along with each English meaning, before the demo.
- **Reset live-taught signs:** delete `vocab.local.json`.

---

## Claude

Claude does the three jobs that need understanding, not perception:

1. **Pick** the intended sign among recognition's top candidates using the conversation (Bob asked "Are you thirsty?", so WATER over NAME).
2. **Compose** Alice's signs into natural first-person English (`I NO UNDERSTAND` → "I don't understand.").
3. **Gloss** Bob's English into vocabulary signs in a signer's order, with synonyms substituted and names fingerspelled ("where can I find the loo?" → `WHERE TOILET`).

It uses `claude-haiku-5-5` through structured outputs, with a 4 s timeout and one retry. Every call has a rule-based fallback. Tune prompts in `prompts.py`, then check the effect with `python -m language.eval.run_eval`. Scene context (`ALMERO_SETTING`) and participant names (`ALMERO_NAMES`) noticeably improve results.

---

## Voices (TTS)

| Engine | When used | Notes |
|---|---|---|
| ElevenLabs | `ELEVENLABS_API_KEY` set (`ALMERO_TTS=auto`) | Most natural; Alice picks her voice. `eleven_flash_v2_5` by default, `eleven_v4_turbo` for more expression |
| edge-tts | No ElevenLabs key, or ElevenLabs failing | Free Microsoft voices incl. Nigerian English (`en-NG-EzinneNeural`, `en-NG-AbeoNeural`); needs internet |
| System | Both above failing | Windows SAPI, macOS `say`, Linux `espeak-ng`; offline |

**Choosing Alice's voice:** on elevenlabs.io add a few voices from the Voice Library to My Voices (search "Nigerian"). Then in the CLI run `voices` (or `voices nigerian`, which searches only voices in your account), `voice <id>` and `speak Good morning, my name is Ada.` Keep the choice with `ALMERO_ELEVENLABS_VOICE`, or send it as `profile.voice_id`. It's her voice in the room, so she chooses.

**Privacy:** Alice's sentences are sent to ElevenLabs, which logs requests by default. Fine for the demo; say so in consent material before clinical use. Only emergency phrases are cached on disk, never everyday sentences.

---

## Signer recording sessions

The sign library is the ground truth for both directions, so sessions are run with care. The full protocol is in `SIGNER_SESSIONS.md`.

```powershell
python -m language.sessions consent --signer S01                       # in sign, with an interpreter if needed
python -m language.sessions plan    --signer S01 --tier 1 --takes 5    # 50 shots, about 10 minutes
python -m language.sessions run     data\sessions\<date>_S01           # Enter good · b bad · r redo · s skip · q save
python -m language.sessions status                                      # demo-ready signs (≥ 3 good takes)
```

Shot lists are round-robin (every sign once, then again in a new order), with emergencies first. Progress saves after every take, so a session can stop and resume. Consent is per scope (demo, dataset, raw video, public release), and signers use pseudonymous IDs.

---

## Configuration

Set with `$env:NAME = "value"` (PowerShell) or `export NAME=value` before starting.

| Setting | Default | What it does |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Turns Claude on |
| `ALMERO_OFFLINE` | `0` | `1` forces the rule-based fallbacks |
| `ALMERO_CLAUDE_MODEL` | `claude-haiku-5-5` | Claude model |
| `ALMERO_CLAUDE_TIMEOUT_S` | `4.0` | Then the fallback answers |
| `ALMERO_SETTING` | classroom | The scene Claude is told about |
| `ALMERO_NAMES` | `Alice,Bob` | Names STT and fingerspelling must get right |
| `ALMERO_MAX_FINGERSPELL` | `2` | Fingerspelled words per sentence |
| `ALMERO_STT` | `whisper` | `none` disables speech input |
| `ALMERO_WHISPER_MODEL` | `base.en` | `small.en` only on a GPU or fast laptop |
| `ALMERO_WHISPER_DEVICE` | `auto` | `cpu` or `cuda` |
| `ALMERO_VAD_END_MS` | `700` | Silence that ends Bob's sentence |
| `ALMERO_VAD_MAX_S` | `15` | Longest single utterance |
| `ALMERO_SIGN_PAUSE_S` | `1.5` | Pause that ends Alice's sentence |
| `ALMERO_MIN_CONF` | `0.45` | Below this, `unknown_sign` |
| `ALMERO_ACCEPT_CONF` / `ALMERO_ACCEPT_MARGIN` | `0.80` / `0.15` | Accept a sign without Claude |
| `ALMERO_TTS_MODE` | `app` | `app`, `service` or `local` (where Bob hears Alice) |
| `ALMERO_TTS` | `auto` | `auto`, `elevenlabs`, `edge`, `system`, `none` |
| `ELEVENLABS_API_KEY` | — | Turns ElevenLabs on |
| `ALMERO_ELEVENLABS_VOICE` | `JBFqnCBsd6RMkjVDRZzb` | Alice's voice id (docs default "George") |
| `ALMERO_ELEVENLABS_MODEL` | `eleven_flash_v2_5` | or `eleven_v4_turbo` |
| `ALMERO_ELEVENLABS_FORMAT` | `mp3_44100_64` | Any ElevenLabs output format; `pcm_*` is wrapped as WAV |
| `ALMERO_ELEVENLABS_STABILITY` / `_SIMILARITY` / `_SPEED` | `0.5` / `0.75` / `1.0` | Voice settings |
| `ALMERO_TTS_VOICE` | `en-NG-EzinneNeural` | edge-tts voice |
| `ALMERO_TTS_CACHE` | `language/.tts_cache` | Emergency-phrase audio cache |
| `ALMERO_VOCAB` / `ALMERO_VOCAB_LOCAL` | `vocab.json` / `vocab.local.json` | Vocabulary files |
| `ALMERO_SPEAKER_SIGNER` / `ALMERO_SPEAKER_HEARING` | `alice` / `bob` | `speaker` values |
| `ALMERO_EMIT_STATUS` | `1` | Send `status` messages |
| `ALMERO_EMIT_SEQUENCE` | `0` | Add the proposed `sequence` to `avatar_play` |

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| pip tries to build numpy or cmake | You're on MSYS2 Python. Recreate the venv with `py -3.12` |
| `Activate.ps1 cannot be loaded` | `Set-ExecutionPolicy -Scope Process Bypass -Force` |
| `No module named language` | Run from the `backend` folder |
| `CERTIFICATE_VERIFY_FAILED` | The network intercepts secure connections; try a phone hotspot |
| Banner says `claude=OFF` | Set `ANTHROPIC_API_KEY` in this window |
| Colour codes like `[36m` | Add `--no-color` |
| No sound | Install ffmpeg; don't use `--tts none`; use `--tts-mode local` in the CLI |
| Names misheard ("alleys") | Set `ALMERO_NAMES` |
| Slow transcription | Keep `base.en` on CPU |
| ElevenLabs `invalid_api_key` / `voice_not_found` / `quota_exceeded` | Check the key / add the voice to My Voices / check credits |
| `voices nigerian` finds nothing | It searches only your account; add voices from the Voice Library, or run `voices` alone |
| Phone can't connect, laptop can | Use the IP not `localhost`, open the firewall port, use a hotspot |
| Every sign is `unknown_sign` | Recognition's scores are on another scale; tune `ALMERO_MIN_CONF` |
| Bob hears Alice twice | More than one device is speaking; only the phone should |
| Remove a live-taught sign | Delete `vocab.local.json` |

---

## Open decisions

| Decision | Options | Owner | Default until decided |
|---|---|---|---|
| How Bob hears Alice | `speech_audio` from the backend, or phone TTS | Dubem | `app` (phone TTS) |
| `speech_audio` message | Add to the contract | Dubem | Only sent with `TTS_MODE=service` |
| `avatar_play.sequence` | Add, to keep sign/fingerspell order | Dubem, Femi, Yuki | Off |
| `profile.voice_id`, `teach_stop.english` | Optional fields | Dubem | Accepted if present |
| Confidence thresholds | Calibrate against real recognition scores | Martins, Ephraim | 0.45 / 0.80 / 0.15 |
| `grammar_notes` and English meanings | Review with the native signer | Ephraim | Placeholders |
| Recording file layout | `data/signs/<LABEL>/<signer>_t<n>.*` | Martins, Ephraim | Proposed |
