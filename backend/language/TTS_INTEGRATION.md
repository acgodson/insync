# ElevenLabs voice: how it connects to the rest of Almero

For Dubem (app, contract) and Femi & Yuki (web UI).

## The flow

```
Alice signs ─▶ backend composes the sentence
                 ├─▶ `sentence`      {text, speaker}           instant, to app + web UI
                 └─▶ ElevenLabs (API key stays on the backend)
                       └─▶ `speech_audio` {audio, format, text}  ~0.3–0.8 s later, to the app
                             └─▶ app plays it on the phone speaker for Bob
```

Run the backend with `ALMERO_TTS_MODE=service`. In the default `app` mode the
backend sends no audio and the phone speaks `sentence` with its own TTS.

## Contract addition (needs sign-off)

`speech_audio` is new. It fills the "speech audio" arrow in the architecture diagram
that §6 never defined.

| type | fields | notes |
|---|---|---|
| speech_audio | audio (base64), format, text | `format` is `mp3` by default; `text` matches the `sentence` it voices. 20–40 KB per sentence |

Optional, also proposed: `profile` may carry `voice_id` (Alice's chosen ElevenLabs
voice). The backend switches to it on connect. Without it, the backend's
`ALMERO_ELEVENLABS_VOICE` is used.

## App (Dubem): play it, with a fallback

Bob must never be left in silence. Arm a timer on `sentence`; if `speech_audio`
for that text hasn't arrived in time, speak with the phone's own TTS, and ignore
the late audio. Sketch for Flutter with `audioplayers` and `flutter_tts`; check the
API against the versions in `pubspec.yaml`.

```dart
import 'dart:async';
import 'dart:convert';
import 'package:audioplayers/audioplayers.dart';
import 'package:flutter_tts/flutter_tts.dart';

class AlmeroVoice {
  final _player = AudioPlayer();
  final _deviceTts = FlutterTts();
  final Map<String, Timer> _pending = {};   // sentence text -> fallback timer
  final Set<String> _spokenByDevice = {};

  void onMessage(Map<String, dynamic> msg) {
    switch (msg['type']) {
      case 'sentence':
        if (msg['speaker'] != 'alice') return;
        final text = msg['text'] as String;
        _pending[text]?.cancel();
        _pending[text] = Timer(const Duration(milliseconds: 2000), () {
          _pending.remove(text);
          _spokenByDevice.add(text);
          _deviceTts.speak(text);           // ElevenLabs too slow or down
        });
        break;
      case 'speech_audio':
        final text = msg['text'] as String;
        _pending.remove(text)?.cancel();
        if (_spokenByDevice.remove(text)) return;   // already spoken; don't say it twice
        _player.play(BytesSource(base64Decode(msg['audio'] as String)));
        break;
    }
  }
}
```

Route playback to the phone speaker (Bob hears it), not the glasses.

## Web UI (Femi, Yuki)

Ignore `speech_audio`. Exactly one device should speak, or Bob hears an echo. If
the team decides the projector speakers are the voice instead, play it there and
disable the app's playback:

```ts
if (msg.type === 'speech_audio' && view === 'projector')
  new Audio(`data:audio/${msg.format === 'mp3' ? 'mpeg' : msg.format};base64,${msg.audio}`).play();
```

## Choosing Alice's voice

1. On elevenlabs.io: Voices → Voice Library, search "Nigerian", add one or two to My Voices.
2. Audition them with Alice in the CLI: `voices nigerian`, `voice <id>`, `speak Good morning, my name is Ada.`
3. Set `ALMERO_ELEVENLABS_VOICE=<id>` (or send it as `profile.voice_id`).

It is Alice's voice in the room, so she chooses it.

## What to know

- **Latency:** `eleven_flash_v2_5` is ElevenLabs' fast model (~100 ms median plus network).
  `eleven_v4_turbo` is more expressive at similar speed; switch with `ALMERO_ELEVENLABS_MODEL`.
  The sentence text reaches the app before the audio, so captions are never delayed.
- **Failure:** bad key, no credits or no network → falls back to edge-tts, then the system
  voice, then the app's own TTS via the timer above. Emergency phrases are pre-rendered to
  disk at startup in Alice's voice, so they play even with no network.
- **Cost:** billed per character. Pre-rendered emergency phrases are cached on disk, so
  restarts don't re-spend credits.
- **Privacy:** Alice's sentences are sent to ElevenLabs, which logs requests by default
  (zero-retention mode is enterprise-only). Fine for the demo; say so in consent material
  before using it in clinics or hospitals. Only emergency phrases are cached on disk,
  never her everyday sentences.
