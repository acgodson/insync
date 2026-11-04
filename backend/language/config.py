"""All tunables in one place, overridable with ALMERO_* environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _env(name: str, default, cast=str):
    raw = os.environ.get(f"ALMERO_{name}")
    if raw is None:
        return default
    if cast is bool:
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    return cast(raw)


@dataclass
class Settings:
    # --- Claude ---
    claude_model: str = field(default_factory=lambda: _env("CLAUDE_MODEL", "claude-haiku-5-5"))
    claude_timeout_s: float = field(default_factory=lambda: _env("CLAUDE_TIMEOUT_S", 4.0, float))
    offline: bool = field(default_factory=lambda: _env("OFFLINE", False, bool))  # force rule-based fallbacks
    setting: str = field(default_factory=lambda: _env(
        "SETTING", "A classroom in a mainstream Nigerian school. Alice is a Deaf student; Bob is her teacher."))

    # --- Vocabulary ---
    vocab_path: Path = field(default_factory=lambda: Path(_env("VOCAB", str(HERE / "vocab.json"))))
    # Signs taught live are persisted here so they survive restarts.
    vocab_local_path: Path = field(default_factory=lambda: Path(_env("VOCAB_LOCAL", str(HERE / "vocab.local.json"))))
    # People and places likely to be named in the demo; biases STT and keeps fingerspelling right.
    names: list[str] = field(default_factory=lambda: [n.strip() for n in _env("NAMES", "Alice,Bob").split(",") if n.strip()])
    max_fingerspell_words: int = field(default_factory=lambda: _env("MAX_FINGERSPELL", 2, int))

    # --- Sign -> English (context step) ---
    accept_conf: float = field(default_factory=lambda: _env("ACCEPT_CONF", 0.80, float))   # take top-1 without Claude
    accept_margin: float = field(default_factory=lambda: _env("ACCEPT_MARGIN", 0.15, float))
    min_conf: float = field(default_factory=lambda: _env("MIN_CONF", 0.45, float))         # below -> unknown_sign
    sign_pause_s: float = field(default_factory=lambda: _env("SIGN_PAUSE_S", 1.5, float))  # end of Alice's utterance

    # --- STT ---
    stt_engine: str = field(default_factory=lambda: _env("STT", "whisper"))  # whisper | text
    whisper_model: str = field(default_factory=lambda: _env("WHISPER_MODEL", "base.en"))  # small.en on GPU/fast laptop
    whisper_device: str = field(default_factory=lambda: _env("WHISPER_DEVICE", "auto"))
    stt_rate: int = 16000
    vad_end_silence_ms: int = field(default_factory=lambda: _env("VAD_END_MS", 700, int))
    vad_max_utterance_s: float = field(default_factory=lambda: _env("VAD_MAX_S", 15.0, float))

    # --- TTS ---
    # auto -> ElevenLabs if ELEVENLABS_API_KEY is set, else edge. Every engine falls back down the chain.
    tts_engine: str = field(default_factory=lambda: _env("TTS", "auto"))  # auto | elevenlabs | edge | system | none
    tts_voice: str = field(default_factory=lambda: _env("TTS_VOICE", "en-NG-EzinneNeural"))  # edge-tts voice
    # ElevenLabs. The key uses ElevenLabs' standard variable name, so their own tools see it too.
    elevenlabs_api_key: str = field(default_factory=lambda: os.environ.get("ELEVENLABS_API_KEY", ""))
    # Default is ElevenLabs' "George" from their docs; pick Alice's own voice with the CLI `voices` command.
    elevenlabs_voice_id: str = field(default_factory=lambda: _env("ELEVENLABS_VOICE", "JBFqnCBsd6RMkjVDRZzb"))
    elevenlabs_model: str = field(default_factory=lambda: _env("ELEVENLABS_MODEL", "eleven_flash_v2_5"))  # or eleven_v4_turbo
    elevenlabs_format: str = field(default_factory=lambda: _env("ELEVENLABS_FORMAT", "mp3_44100_64"))
    elevenlabs_stability: float = field(default_factory=lambda: _env("ELEVENLABS_STABILITY", 0.5, float))
    elevenlabs_similarity: float = field(default_factory=lambda: _env("ELEVENLABS_SIMILARITY", 0.75, float))
    elevenlabs_speed: float = field(default_factory=lambda: _env("ELEVENLABS_SPEED", 1.0, float))
    # Only pre-warmed phrases (emergencies) are cached on disk: never Alice's everyday sentences.
    tts_cache_dir: Path = field(default_factory=lambda: Path(_env("TTS_CACHE", str(HERE / ".tts_cache"))))
    # Where Bob hears Alice's sentence:
    #   app     -> the app speaks the `sentence` message itself (contract as frozen; no audio sent)
    #   service -> backend sends a `speech_audio` message (PROPOSED contract addition, see README)
    #   local   -> play on this machine's speakers (laptop next to the projector)
    tts_mode: str = field(default_factory=lambda: _env("TTS_MODE", "app"))

    # --- Contract ---
    speaker_signer: str = field(default_factory=lambda: _env("SPEAKER_SIGNER", "alice"))
    speaker_hearing: str = field(default_factory=lambda: _env("SPEAKER_HEARING", "bob"))
    emit_status: bool = field(default_factory=lambda: _env("EMIT_STATUS", True, bool))
    # avatar_play has separate signs/fingerspell arrays, which loses interleaving order.
    # When on, an extra `sequence` field carries the true order (PROPOSED, off by default).
    emit_sequence: bool = field(default_factory=lambda: _env("EMIT_SEQUENCE", False, bool))

    history_turns: int = 10
