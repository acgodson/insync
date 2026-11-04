# `backend/language/` — Cluster C: Language & voice

Owner: Ephraim. STT, Claude prompts, TTS, and the signer recording sessions.
Standalone test: the CLI loop (`python -m language.cli`).

```
Bob   audio ─▶ Endpointer (VAD) ─▶ Whisper ─▶ caption ─▶ Claude gloss ─▶ avatar_play
Alice sign_candidates ─▶ pick (Claude only if unsure) ─▶ sign_recognized
      … pause (1.5 s) or emergency sign ─▶ Claude compose ─▶ sentence ─▶ TTS
```

## Quick start

```bash
cd backend
pip install -r language/requirements.txt
export ANTHROPIC_API_KEY=...

python -m language.cli                                    # interactive; type `help`
python -m language.cli --script language/eval/demo_script.txt --log demo.jsonl
python -m language.cli --offline                          # no Claude: rule-based fallbacks
python -m language.eval.run_eval                          # prompt accuracy + latency
python -m pytest -q language/tests                        # 54 offline tests
```

`demo.jsonl` holds every emitted message in the exact contract shape, so Cluster A's
`mock.ts` can replay a real conversation.

## Files

| File | What it does |
|---|---|
| `module.py` | `LanguageModule`, the only thing integration needs to touch |
| `vocab.json` / `vocab.py` | The sign vocabulary, single source of truth for both directions. Tiers set recording priority. Live-taught signs persist to `vocab.local.json` |
| `prompts.py` | The three Claude prompts. Sign labels are a JSON-schema `enum`, so Claude cannot return a sign we have no clip for |
| `claude_client.py` | Haiku 5.5 via structured outputs, hard timeout, one retry |
| `gloss.py` | English → signs (Claude, validated) with a rule-based fallback |
| `interpret.py` | Signs → English: candidate picking and sentence composition, with fallbacks |
| `stt.py` | Streaming endpointer + faster-whisper, biased to vocabulary and participant names |
| `tts.py` | ElevenLabs → edge-tts (en-NG voices) → system TTS, with a circuit breaker, voice switching and an emergency-phrase disk cache. See `TTS_INTEGRATION.md` |
| `cli.py` | The CLI loop |
| `server.py` | WebSocket server speaking the contract (`uvicorn language.server:app`), so the app and web UI can connect before the full backend exists |
| `fake_app.py` | Pretends to be the phone app or a UI over the real socket |
| `sessions.py` | Signer sessions: consent, round-robin shot lists, take tracking, readiness. See `SIGNER_SESSIONS.md` |
| `eval/` | Demo script, eval cases, eval runner |

## Integration (for Dubem)

```python
from language import LanguageModule

lang = LanguageModule(emit=broadcast)   # broadcast(msg: dict) -> app + web UI; sync or async
await lang.start()                      # loads Whisper, pre-renders emergency phrases (~3 s)

# in the WebSocket handler
if msg["type"] in ("audio", "teach_stop"):
    await lang.handle(msg)

# from recognition/, once per segmented sign (top 3)
await lang.on_sign_candidates([{"label": "WATER", "confidence": 0.71}, ...])
```

Emits `caption`, `avatar_play`, `sign_recognized`, `unknown_sign`, `sentence`, `status`.
Whisper runs in a thread pool and Claude calls are async, so the event loop is never blocked.
Utterances stay in order per direction.

**Design choices worth knowing**

- A confident sign (≥ 0.80 with a 0.15 margin) skips Claude entirely. Claude is only asked when recognition is genuinely unsure.
- Emergency signs (HELP, FIRE, PAIN, CANT-BREATHE, STOP) speak immediately with a canned sentence. No pause wait, no network.
- Any Claude failure or timeout (4 s) falls back to rules. The demo degrades; it doesn't stop.
- The caption is sent before the gloss, so Alice can read while the avatar is still being prepared.

## Latency (measured in the sandbox, 1 CPU core, no GPU)

| Stage | Measured | Notes |
|---|---|---|
| End-of-speech detection | 700 ms | `ALMERO_VAD_END_MS`; 500 is fine in a quiet room |
| Whisper `base.en`, 6 s utterance | ~0.9 s | `small.en` was 3.0 s on one core; use it only on a GPU or a fast laptop |
| Claude Haiku call | not measured here | run `run_eval` for p50/p95 on your network |
| Pause that ends Alice's sentence | 1.5 s | `ALMERO_SIGN_PAUSE_S`; the largest single cost in the sign direction |

Speech direction end to end without Claude: 1.7–2.7 s. That leaves under a second for Claude in the 3 s budget, so check `run_eval` p95 early.

## Open contract questions (need sign-off from integration)

1. **How does Bob hear Alice?** The architecture diagram shows speech audio from the service, but §6 has no audio message. Default `TTS_MODE=app`: the app speaks `sentence` itself (contract untouched). `service` sends a proposed `speech_audio {audio, format, text}`, which is what ElevenLabs needs. `local` plays on the laptop. Full proposal and Flutter sketch in `TTS_INTEGRATION.md`.
2. **`avatar_play` loses order between signs and fingerspelling.** "HELLO [ADA] WHAT" becomes `signs:[HELLO, WHAT]`, `fingerspell:[ADA]`. `ALMERO_EMIT_SEQUENCE=1` adds a proposed `sequence:[{kind, value}]` with the true order.
3. **`speaker` values.** I use `"alice"` / `"bob"`. Configurable (`ALMERO_SPEAKER_SIGNER` / `ALMERO_SPEAKER_HEARING`).
4. **`audio.pcm` format.** Assumed 16-bit little-endian mono. Other rates are resampled.
5. **Who emits `unknown_sign`?** I emit it below `MIN_CONF` (0.45). If recognition emits it, set `ALMERO_MIN_CONF=0`.
6. **Labels.** Recognition's library labels must match `vocab.json` exactly (UPPERCASE, hyphens). I'd like Cluster B to load `vocab.json` rather than keep its own list.
7. **`teach_stop`** could carry an optional `english` field. Without it, the label is used as the English word.

## Before the demo

- Have the native signer review `grammar_notes` in `vocab.json`. They are explicit placeholders, and they go straight into the prompts.
- Set `ALMERO_NAMES` to the real people in the demo. Without it, Whisper turned "Alice" into "alleys" in testing.
- Set `ALMERO_SETTING` per scene (classroom, clinic, interview). It changes how Claude disambiguates.
- Let the signer choose the voice. With ElevenLabs: `voices nigerian`, `voice <id>`, `speak ...` in the CLI, then set `ALMERO_ELEVENLABS_VOICE`. Without it: `ALMERO_TTS_VOICE=en-NG-AbeoNeural` or `en-NG-EzinneNeural`. It's their voice in the room.

## ElevenLabs voices

Set `ELEVENLABS_API_KEY` and the engine switches to ElevenLabs automatically (`ALMERO_TTS=auto`).

| Setting | Default | |
|---|---|---|
| `ELEVENLABS_API_KEY` | — | standard ElevenLabs variable name |
| `ALMERO_ELEVENLABS_VOICE` | `JBFqnCBsd6RMkjVDRZzb` | find yours with the CLI `voices` command |
| `ALMERO_ELEVENLABS_MODEL` | `eleven_flash_v2_5` | `eleven_v4_turbo` for more expression |
| `ALMERO_ELEVENLABS_FORMAT` | `mp3_44100_64` | any ElevenLabs `output_format`; `pcm_*` is wrapped as WAV |
| `ALMERO_ELEVENLABS_STABILITY` / `_SIMILARITY` / `_SPEED` | 0.5 / 0.75 / 1.0 | voice settings |
