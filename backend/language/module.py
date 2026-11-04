"""LanguageModule: the integration surface of Cluster C.

Wiring (in the FastAPI WebSocket hub, owned by integration):

    lang = LanguageModule(emit=broadcast)      # broadcast(msg) -> app + web UI
    await lang.start()
    ...
    await lang.handle(msg)                      # app messages: audio, teach_stop
    await lang.on_sign_candidates(items)        # from recognition/, per segmented sign

Both directions:
  Bob   audio -> Endpointer -> Whisper -> caption -> Claude gloss -> avatar_play
  Alice sign_candidates -> pick (Claude only if unsure) -> sign_recognized
        ... pause or emergency -> Claude compose -> sentence (+ TTS)
"""
from __future__ import annotations

import asyncio
import base64
import inspect
import logging
import time
from typing import Any, Awaitable, Callable

from . import contract
from .claude_client import ClaudeJSON
from .config import Settings
from .conversation import Conversation
from .gloss import Glosser
from .interpret import Interpreter, Slot
from .stt import Endpointer, STTEngine, Utterance, decode_pcm, make_stt
from .tts import TTS, play_local
from .vocab import Vocabulary

log = logging.getLogger("almero.language")

Emit = Callable[[dict], Any]


class LanguageModule:
    def __init__(self, emit: Emit, settings: Settings | None = None, *, vocab: Vocabulary | None = None,
                 stt: STTEngine | None = None, tts: TTS | None = None, claude: ClaudeJSON | None = None):
        self.s = s = settings or Settings()
        self._emit_fn = emit
        self.vocab = vocab or Vocabulary(s.vocab_path, s.vocab_local_path)
        self.claude = claude or ClaudeJSON(s.claude_model, s.claude_timeout_s, s.offline)
        self.convo = Conversation(s.speaker_signer, s.speaker_hearing, s.history_turns)
        self.glosser = Glosser(self.vocab, self.claude, s.setting, s.max_fingerspell_words, s.names)
        self.interp = Interpreter(self.vocab, self.claude, s.setting, s.accept_conf, s.accept_margin, s.min_conf)
        hint = [x.english for x in self.vocab.signs.values()]
        self.stt = stt or make_stt(s.stt_engine, s.whisper_model, s.whisper_device, hint, s.names)
        self.tts = tts or TTS(
            "none" if s.tts_mode == "app" else s.tts_engine, s.tts_voice,
            elevenlabs=dict(api_key=s.elevenlabs_api_key, voice_id=s.elevenlabs_voice_id,
                            model_id=s.elevenlabs_model, output_format=s.elevenlabs_format,
                            stability=s.elevenlabs_stability, similarity=s.elevenlabs_similarity,
                            speed=s.elevenlabs_speed),
            cache_dir=s.tts_cache_dir)
        self.endpointer = Endpointer(s.vad_end_silence_ms, s.vad_max_utterance_s)

        self._speech_lock = asyncio.Lock()   # keeps Bob's utterances in order
        self._sign_lock = asyncio.Lock()     # keeps Alice's signs in order
        self._slots: list[Slot] = []
        self._last_sign_t: float | None = None
        self._pause_timer: asyncio.TimerHandle | None = None
        self._bg: set[asyncio.Task] = set()

    # ------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        """Load Whisper and pre-synthesise emergency phrases so first use is fast."""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self.stt.warmup)
        await self.tts.warm(self._emergency_phrases())
        log.info("language module ready (claude=%s, stt=%s, tts_mode=%s, tts=%s, %d signs)",
                 "on" if self.claude.enabled else "fallback", self.stt.name, self.s.tts_mode,
                 self.tts.describe(), len(self.vocab.labels))

    def _emergency_phrases(self) -> list[str]:
        return [x.speak for x in self.vocab.signs.values() if x.emergency and x.speak]

    async def close(self) -> None:
        if self._pause_timer:
            self._pause_timer.cancel()
        for t in list(self._bg):
            t.cancel()
        if hasattr(self.tts, "aclose"):
            await self.tts.aclose()

    async def emit(self, msg: dict) -> None:
        r = self._emit_fn(msg)
        if inspect.isawaitable(r):
            await r

    def _spawn(self, coro: Awaitable) -> None:
        t = asyncio.ensure_future(coro)
        self._bg.add(t)
        t.add_done_callback(self._bg.discard)

    # ------------------------------------------------------------ dispatch
    async def handle(self, msg: dict) -> None:
        t = msg.get("type")
        if t == "audio":
            await self.on_audio(msg["pcm"], msg.get("rate", 16000))
        elif t == "teach_stop":
            await self.on_teach_stop(msg["label"], msg.get("english"))
        elif t == "sign_candidates":
            await self.on_sign_candidates(msg["items"])
        elif t == "profile" and msg.get("voice_id"):  # PROPOSED optional field: Alice's chosen voice
            await self.set_voice(msg["voice_id"])

    # ------------------------------------------------------------ Bob -> Alice
    async def on_audio(self, pcm_b64: str, rate: int = 16000) -> None:
        for utt in self.endpointer.feed(decode_pcm(pcm_b64, rate)):
            self._spawn(self._process_utterance(utt))

    async def flush_audio(self) -> None:
        """End the current utterance now (push-to-talk release, end of a WAV file)."""
        for utt in self.endpointer.flush():
            await self._process_utterance(utt)

    async def _process_utterance(self, utt: Utterance) -> None:
        async with self._speech_lock:
            t_speech_end = utt.ended_at - utt.end_silence_ms / 1000
            loop = asyncio.get_running_loop()
            text = await loop.run_in_executor(None, self.stt.transcribe, utt.audio)
            log.info("STT %.0f ms: %r", (time.perf_counter() - utt.ended_at) * 1000, text)
            if text:
                await self._speech_text(text, t_speech_end)

    async def on_text(self, text: str) -> None:
        """Bob's words as text (typed in the CLI, or from an external STT)."""
        async with self._speech_lock:
            await self._speech_text(text, time.perf_counter())

    async def _speech_text(self, text: str, t0: float) -> None:
        # Caption first: Alice can read before the avatar starts.
        await self.emit(contract.caption(text, self.s.speaker_hearing))
        res = await self.glosser.gloss(text, self.convo)
        self.convo.add_hearing(text)
        if res.items:
            await self.emit(contract.avatar_play(res.items, self.s.emit_sequence))
        self.last_gloss = res
        if self.s.emit_status:
            await self.emit(contract.status((time.perf_counter() - t0) * 1000))

    # ------------------------------------------------------------ Alice -> Bob
    async def on_sign_candidates(self, items: list[dict]) -> None:
        """One segmented sign from recognition: items = [{label, confidence}] (top 3)."""
        async with self._sign_lock:
            self._last_sign_t = time.perf_counter()
            cands = [(i["label"], float(i["confidence"])) for i in items]
            slot = await self.interp.pick(cands, [x.label for x in self._slots], self.convo)
            if slot is None:
                await self.emit(contract.unknown_sign())
                self._arm_pause_timer()
                return
            self._slots.append(slot)
            await self.emit(contract.sign_recognized(slot.label, slot.confidence))
            sign = self.vocab.get(slot.label)
            if sign and sign.emergency:  # don't wait for the pause: speak now
                await self._flush_signs_locked(reason="emergency")
            else:
                self._arm_pause_timer()

    def _arm_pause_timer(self) -> None:
        if self._pause_timer:
            self._pause_timer.cancel()
        loop = asyncio.get_running_loop()
        self._pause_timer = loop.call_later(self.s.sign_pause_s, lambda: self._spawn(self.end_signing("pause")))

    async def end_signing(self, reason: str = "explicit") -> None:
        async with self._sign_lock:
            await self._flush_signs_locked(reason)

    async def _flush_signs_locked(self, reason: str) -> None:
        if self._pause_timer:
            self._pause_timer.cancel()
            self._pause_timer = None
        slots, self._slots = self._slots, []
        if not slots:
            return
        t_last = self._last_sign_t or time.perf_counter()
        composed = await self.interp.compose(slots, self.convo)
        if not composed.sentence:
            return
        self.convo.add_signer(composed.sentence)
        await self.emit(contract.sentence(composed.sentence, self.s.speaker_signer))
        self.last_composed = composed
        log.info("compose (%s, %s): %s -> %r", reason, composed.source, composed.labels, composed.sentence)
        if self.s.emit_status:
            await self.emit(contract.status((time.perf_counter() - t_last) * 1000))
        if self.s.tts_mode != "app":
            self._spawn(self._speak(composed.sentence))

    # ------------------------------------------------------------ voice
    async def set_voice(self, voice: str) -> str | None:
        """Use `voice` for Alice from now on (an ElevenLabs voice id, or an edge-tts voice
        name when edge is the primary engine). Emergency phrases are re-rendered in it."""
        engine = self.tts.set_voice(voice)
        if engine:
            log.info("voice -> %s (%s)", voice, engine)
            if self.s.tts_mode != "app":
                self._spawn(self.tts.warm(self._emergency_phrases()))
        return engine

    async def speak(self, text: str):
        """Synthesise (and deliver per TTS_MODE) any text: used by the CLI to audition voices."""
        await self._speak(text)
        return getattr(self.tts, "last_engine", None), getattr(self.tts, "last_ms", None)

    async def _speak(self, text: str) -> None:
        audio = await self.tts.synth(text)
        if not audio:
            return
        log.info("TTS %s %.0f ms (%d bytes %s)", getattr(self.tts, "last_engine", "?"),
                 getattr(self.tts, "last_ms", None) or 0, len(audio[0]), audio[1])
        if self.s.tts_mode == "service":
            await self.emit(contract.speech_audio(base64.b64encode(audio[0]).decode(), audio[1], text))
        elif self.s.tts_mode == "local":
            await play_local(audio)

    # ------------------------------------------------------------ teach it live
    async def on_teach_stop(self, label: str, english: str | None = None) -> None:
        """A new sign was recorded live; make it usable in both directions immediately."""
        sign = self.vocab.add_sign(label, english)
        log.info("taught live: %s (%s)", sign.label, sign.english)
