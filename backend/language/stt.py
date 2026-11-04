"""Speech-to-text for Bob's side.

The app streams `audio` messages (16 kHz PCM chunks). The Endpointer finds where
an utterance starts and ends (energy VAD with an adaptive noise floor), then the
STT engine transcribes the whole utterance in one go.
"""
from __future__ import annotations

import base64
import logging
import time
from collections import deque
from dataclasses import dataclass

import numpy as np

log = logging.getLogger("almero.language.stt")

RATE = 16000
FRAME = 480  # 30 ms at 16 kHz

# Whisper's well-known outputs on silence/noise. Dropped unless the audio is clearly speech.
HALLUCINATIONS = {"thank you.", "thank you", "thanks for watching!", "thanks for watching.", "you",
                  "bye.", ".", "okay.", "so", "subtitles by the amara.org community"}


def decode_pcm(pcm_b64: str, rate: int = RATE) -> np.ndarray:
    """Contract `audio.pcm`: base64 of 16-bit little-endian mono PCM."""
    x = np.frombuffer(base64.b64decode(pcm_b64), dtype="<i2")
    return resample(x, rate, RATE) if rate != RATE else x


def resample(x: np.ndarray, src: int, dst: int) -> np.ndarray:
    if src == dst or len(x) == 0:
        return x
    n = int(round(len(x) * dst / src))
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x.astype(np.float32)).astype(np.int16)


def dbfs(frame: np.ndarray) -> float:
    rms = np.sqrt(np.mean(frame.astype(np.float32) ** 2)) + 1e-9
    return 20 * np.log10(rms / 32768.0)


@dataclass
class Utterance:
    audio: np.ndarray        # int16 @ 16 kHz, includes pre-roll
    voiced_ms: int
    ended_at: float          # perf_counter when the end was detected
    end_silence_ms: int      # how long we waited after speech stopped


class Endpointer:
    def __init__(self, end_silence_ms: int = 700, max_utterance_s: float = 15.0,
                 start_frames: int = 3, preroll_ms: int = 300, min_voiced_ms: int = 250,
                 abs_floor_db: float = -50.0, snr_db: float = 10.0):
        self.end_frames = max(1, end_silence_ms // 30)
        self.max_frames = int(max_utterance_s * 1000 / 30)
        self.start_frames = start_frames
        self.min_voiced_frames = max(1, min_voiced_ms // 30)
        self.abs_floor_db, self.snr_db = abs_floor_db, snr_db
        self.noise_db = -60.0
        self._buf = np.zeros(0, dtype=np.int16)
        self._pre: deque[np.ndarray] = deque(maxlen=max(1, preroll_ms // 30))
        self._cur: list[np.ndarray] = []
        self._in_speech = False
        self._run = 0          # consecutive speech frames before onset
        self._silence = 0
        self._voiced = 0

    def reset(self) -> None:
        self.__init__(self.end_frames * 30, self.max_frames * 30 / 1000, self.start_frames,
                      self._pre.maxlen * 30, self.min_voiced_frames * 30, self.abs_floor_db, self.snr_db)

    def _is_speech(self, e: float) -> bool:
        return e > max(self.abs_floor_db, self.noise_db + self.snr_db)

    def feed(self, pcm: np.ndarray) -> list[Utterance]:
        out: list[Utterance] = []
        self._buf = np.concatenate([self._buf, pcm.astype(np.int16)])
        while len(self._buf) >= FRAME:
            f, self._buf = self._buf[:FRAME], self._buf[FRAME:]
            e = dbfs(f)
            speech = self._is_speech(e)
            if not self._in_speech:
                if not speech:  # track the room's noise floor while nobody talks
                    self.noise_db = 0.95 * self.noise_db + 0.05 * e
                self._pre.append(f)
                self._run = self._run + 1 if speech else 0
                if self._run >= self.start_frames:
                    self._in_speech = True
                    self._cur = list(self._pre)
                    self._voiced, self._silence = self._run, 0
                continue
            self._cur.append(f)
            if speech:
                self._voiced += 1
                self._silence = 0
            else:
                self._silence += 1
            if self._silence >= self.end_frames or len(self._cur) >= self.max_frames:
                u = self._finish()
                if u:
                    out.append(u)
        return out

    def flush(self) -> list[Utterance]:
        """Force-end (e.g. push-to-talk released)."""
        u = self._finish() if self._in_speech else None
        return [u] if u else []

    def _finish(self) -> Utterance | None:
        audio = np.concatenate(self._cur) if self._cur else np.zeros(0, np.int16)
        voiced, silence = self._voiced, self._silence
        self._in_speech, self._cur, self._run, self._voiced, self._silence = False, [], 0, 0, 0
        self._pre.clear()
        if voiced < self.min_voiced_frames:
            return None  # a cough, a door
        return Utterance(audio, voiced * 30, time.perf_counter(), silence * 30)


# --------------------------------------------------------------------- engines
class STTEngine:
    name = "base"

    def warmup(self) -> None: ...

    def transcribe(self, audio: np.ndarray) -> str:
        raise NotImplementedError


class WhisperSTT(STTEngine):
    """faster-whisper running locally. small.en is a good laptop default; use
    base.en if the CPU is slow, medium.en on a GPU."""
    name = "whisper"

    def __init__(self, model: str = "base.en", device: str = "auto", hint_words: list[str] | None = None,
                 names: list[str] | None = None):
        self.model_name, self.device = model, device
        # Biases decoding toward our vocabulary and the people in the room, without forcing it.
        parts = ["Classroom conversation."]
        if names:
            parts.append("Names: " + ", ".join(names) + ".")
        if hint_words:
            parts.append("Words: " + ", ".join(hint_words[:60]) + ".")
        self.hint = " ".join(parts) if len(parts) > 1 else None
        self._model = None

    def warmup(self) -> None:
        if self._model is None:
            from faster_whisper import WhisperModel
            t0 = time.perf_counter()
            compute = "int8" if self.device in ("cpu", "auto") else "float16"
            self._model = WhisperModel(self.model_name, device=self.device, compute_type=compute)
            self._model.transcribe(np.zeros(RATE // 2, np.float32), language="en", beam_size=1)
            log.info("whisper %s ready in %.1fs", self.model_name, time.perf_counter() - t0)

    def transcribe(self, audio: np.ndarray) -> str:
        self.warmup()
        f = audio.astype(np.float32) / 32768.0
        segments, _ = self._model.transcribe(
            f, language="en", beam_size=1, vad_filter=False, condition_on_previous_text=False,
            initial_prompt=self.hint, without_timestamps=True)
        kept = []
        for s in segments:
            if s.no_speech_prob > 0.6 and s.avg_logprob < -0.8:
                continue
            kept.append(s.text.strip())
        text = " ".join(kept).strip()
        if text.lower() in HALLUCINATIONS and len(audio) < RATE * 1.5:
            log.info("dropped likely hallucination %r", text)
            return ""
        return text


class NoSTT(STTEngine):
    """For text-only runs; audio is ignored."""
    name = "none"

    def transcribe(self, audio: np.ndarray) -> str:
        return ""


def make_stt(engine: str, model: str, device: str, hint_words: list[str],
             names: list[str] | None = None) -> STTEngine:
    if engine == "whisper":
        return WhisperSTT(model, device, hint_words, names)
    return NoSTT()
