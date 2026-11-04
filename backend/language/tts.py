"""Text-to-speech for Alice's sentences.

Engines, best first; a failing engine falls through to the next:
  elevenlabs  ElevenLabs REST API. Most natural; Alice picks her own voice. Needs ELEVENLABS_API_KEY.
  edge        Microsoft neural voices via edge-tts, incl. Nigerian English
              (en-NG-EzinneNeural, en-NG-AbeoNeural). Free, needs internet.
  system      macOS `say`, Linux `espeak-ng`/`espeak`, Windows SAPI. Offline, robotic.
A circuit breaker skips an engine for a minute after it fails, so a dead network
or an exhausted quota costs one timeout, not one per sentence.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import os
import platform
import shutil
import subprocess
import tempfile
import time
import wave
from collections import OrderedDict
from pathlib import Path

log = logging.getLogger("almero.language.tts")

Audio = tuple[bytes, str]  # (bytes, "mp3" | "wav" | "opus" | "aiff")


class TTSEngine:
    name = "none"
    voice = ""

    async def synth(self, text: str) -> Audio | None:
        return None

    async def aclose(self) -> None:
        pass


# --------------------------------------------------------------------- ElevenLabs
class ElevenLabsError(RuntimeError):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code = status, code
        super().__init__(f"ElevenLabs {status} {code}: {message}")


# Plain-language hints for the errors you'll actually hit at a hackathon.
_HINTS = {
    "invalid_api_key": "check ELEVENLABS_API_KEY",
    "voice_not_found": "voice id doesn't exist in this account; run `voices` in the CLI",
    "quota_exceeded": "out of character credits for this billing period",
    "too_many_concurrent_requests": "plan's concurrency limit hit",
    "missing_permissions": "API key lacks the text_to_speech permission",
}


def _pcm_to_wav(pcm: bytes, rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


class ElevenLabsTTS(TTSEngine):
    """POST /v1/text-to-speech/{voice_id}. One pooled HTTP client, so every sentence after
    the first skips the TLS handshake."""
    name = "elevenlabs"
    BASE = "https://api.elevenlabs.io"

    def __init__(self, api_key: str, voice_id: str, model_id: str = "eleven_flash_v2_5",
                 output_format: str = "mp3_44100_64", stability: float = 0.5,
                 similarity: float = 0.75, speed: float = 1.0, client=None, base_url: str | None = None):
        self.api_key, self.voice, self.model_id = api_key, voice_id, model_id
        self.output_format = output_format
        self.voice_settings = {"stability": stability, "similarity_boost": similarity, "speed": speed}
        self.base = (base_url or os.environ.get("ELEVENLABS_BASE_URL") or self.BASE).rstrip("/")
        self._client = client  # injectable for tests

    def _http(self):
        if self._client is None:
            import httpx
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=3.0),
                                             headers={"xi-api-key": self.api_key})
        return self._client

    @staticmethod
    def _raise_for(resp) -> None:
        if resp.status_code < 400:
            return
        code, message = "error", resp.text[:200]
        try:
            d = resp.json().get("detail", {})
            if isinstance(d, dict):
                code = d.get("status") or d.get("code") or code
                message = d.get("message", message)
            elif isinstance(d, list) and d:  # 422 validation errors
                code, message = "invalid_request", "; ".join(str(x.get("msg", x)) for x in d)
        except ValueError:
            pass
        hint = _HINTS.get(code)
        raise ElevenLabsError(resp.status_code, code, f"{message}" + (f" ({hint})" if hint else ""))

    async def synth(self, text: str) -> Audio | None:
        resp = await self._http().post(
            f"{self.base}/v1/text-to-speech/{self.voice}",
            params={"output_format": self.output_format},
            headers={"xi-api-key": self.api_key},
            json={"text": text, "model_id": self.model_id, "voice_settings": self.voice_settings},
        )
        self._raise_for(resp)
        data = resp.content
        if not data:
            return None
        codec, _, rest = self.output_format.partition("_")
        if codec == "pcm":  # raw samples; wrap so any player (and the app) can play it
            return _pcm_to_wav(data, int(rest.split("_")[0])), "wav"
        return data, {"mp3": "mp3", "wav": "wav", "opus": "opus"}.get(codec, codec)

    async def list_voices(self, search: str | None = None, page_size: int = 30) -> list[dict]:
        """Voices in this account (default voices + any added from the Voice Library)."""
        params = {"page_size": page_size, "include_total_count": "false"}
        if search:
            params["search"] = search
        resp = await self._http().get(f"{self.base}/v2/voices", params=params,
                                      headers={"xi-api-key": self.api_key})
        self._raise_for(resp)
        out = []
        for v in resp.json().get("voices", []):
            labels = v.get("labels") or {}
            out.append({"voice_id": v["voice_id"], "name": v.get("name", ""), "category": v.get("category", ""),
                        "accent": labels.get("accent", ""), "gender": labels.get("gender", ""),
                        "description": (v.get("description") or labels.get("descriptive") or "")[:80]})
        return out

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()


# --------------------------------------------------------------------- edge / system
class EdgeTTS(TTSEngine):
    name = "edge"

    def __init__(self, voice: str = "en-NG-EzinneNeural"):
        self.voice = voice

    async def synth(self, text: str) -> Audio | None:
        import edge_tts
        chunks = []
        async for c in edge_tts.Communicate(text, self.voice).stream():
            if c["type"] == "audio":
                chunks.append(c["data"])
        return (b"".join(chunks), "mp3") if chunks else None


class SystemTTS(TTSEngine):
    name = "system"

    async def synth(self, text: str) -> Audio | None:
        system = platform.system()
        with tempfile.TemporaryDirectory() as d:
            if system == "Darwin":
                path, fmt = os.path.join(d, "o.aiff"), "aiff"
                cmd = ["say", "-o", path, text]
            elif system == "Windows":
                path, fmt = os.path.join(d, "o.wav"), "wav"
                ps = ("Add-Type -AssemblyName System.Speech; $s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
                      f"$s.SetOutputToWaveFile('{path}'); $s.Speak([Console]::In.ReadToEnd())")
                cmd = ["powershell", "-NoProfile", "-Command", ps]
            else:
                exe = shutil.which("espeak-ng") or shutil.which("espeak")
                if not exe:
                    return None
                path, fmt = os.path.join(d, "o.wav"), "wav"
                cmd = [exe, "-w", path, text]
            p = await asyncio.create_subprocess_exec(*cmd, stdin=subprocess.PIPE,
                                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            await p.communicate(text.encode() if system == "Windows" else None)
            if p.returncode != 0 or not os.path.exists(path):
                return None
            return open(path, "rb").read(), fmt


# --------------------------------------------------------------------- chain
def resolve_engine(engine: str, elevenlabs_key: str) -> str:
    if engine == "auto":
        return "elevenlabs" if elevenlabs_key else "edge"
    return engine


class TTS:
    """Engine chain + in-memory cache + small disk cache for pre-warmed phrases."""

    def __init__(self, engine: str = "auto", voice: str = "en-NG-EzinneNeural", *,
                 elevenlabs: dict | None = None, cache_dir: Path | None = None, cache_size: int = 64,
                 engines: list[TTSEngine] | None = None):
        el = elevenlabs or {}
        engine = resolve_engine(engine, el.get("api_key", ""))
        chain: list[TTSEngine] = list(engines or [])
        if not engines:
            if engine == "elevenlabs":
                if el.get("api_key"):
                    chain.append(ElevenLabsTTS(**el))
                else:
                    log.warning("TTS=elevenlabs but ELEVENLABS_API_KEY is not set; using edge-tts")
            if engine in ("elevenlabs", "edge"):
                chain.append(EdgeTTS(voice))
            if engine in ("elevenlabs", "edge", "system"):
                chain.append(SystemTTS())
        self.chain = chain
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self._down_until: dict[str, float] = {}
        self.cooldown_s = 60.0
        self.timeout_s = 4.0
        self.last_engine: str | None = None
        self.last_ms: float | None = None
        self._cache: OrderedDict[str, Audio] = OrderedDict()
        self._cache_size = cache_size

    @property
    def primary(self) -> TTSEngine | None:
        return self.chain[0] if self.chain else None

    def describe(self) -> str:
        return " > ".join(f"{e.name}" + (f"({e.voice})" if e.voice else "") for e in self.chain) or "none"

    def get_engine(self, name: str) -> TTSEngine | None:
        return next((e for e in self.chain if e.name == name), None)

    def set_voice(self, voice: str, engine: str | None = None) -> str | None:
        """Switch the voice of `engine` (default: the primary engine). Clears the
        in-memory cache so nothing plays in the old voice."""
        eng = self.get_engine(engine) if engine else self.primary
        if eng is None or eng.name in ("system", "none"):
            return None
        eng.voice = voice
        self._cache.clear()
        self._down_until.pop(eng.name, None)  # a new voice deserves a fresh try
        return eng.name

    def _key(self, eng: TTSEngine, text: str) -> str:
        extra = getattr(eng, "model_id", "") + getattr(eng, "output_format", "")
        return hashlib.sha256(f"{eng.name}|{eng.voice}|{extra}|{text}".encode()).hexdigest()[:24]

    def _disk_get(self, eng: TTSEngine, text: str) -> Audio | None:
        if not self.cache_dir:
            return None
        for p in self.cache_dir.glob(self._key(eng, text) + ".*"):
            return p.read_bytes(), p.suffix[1:]
        return None

    def _disk_put(self, eng: TTSEngine, text: str, audio: Audio) -> None:
        if not self.cache_dir:
            return
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        (self.cache_dir / f"{self._key(eng, text)}.{audio[1]}").write_bytes(audio[0])

    async def synth(self, text: str, persist: bool = False) -> Audio | None:
        if not text or not self.chain:
            return None
        if text in self._cache:
            self._cache.move_to_end(text)
            return self._cache[text]
        t0 = time.perf_counter()
        for eng in self.chain:
            out = self._disk_get(eng, text)  # works even when the network is down
            if out is None:
                if time.monotonic() < self._down_until.get(eng.name, 0):
                    continue
                try:
                    out = await asyncio.wait_for(eng.synth(text), timeout=self.timeout_s)
                except Exception as e:
                    reason = str(e) if isinstance(e, ElevenLabsError) else type(e).__name__
                    log.warning("TTS %s failed (%s); skipping it for %.0fs", eng.name, reason, self.cooldown_s)
                    self._down_until[eng.name] = time.monotonic() + self.cooldown_s
                    continue
                if out and persist:
                    self._disk_put(eng, text, out)
            if out:
                self.last_engine, self.last_ms = eng.name, (time.perf_counter() - t0) * 1000
                self._cache[text] = out
                if len(self._cache) > self._cache_size:
                    self._cache.popitem(last=False)
                return out
        return None

    async def warm(self, phrases: list[str]) -> None:
        """Pre-render phrases that must never wait on the network (emergencies), to disk."""
        if not phrases:
            return
        await self.synth(phrases[0], persist=True)  # trips the breaker once if the network is down
        await asyncio.gather(*(self.synth(p, persist=True) for p in phrases[1:]), return_exceptions=True)

    async def aclose(self) -> None:
        for e in self.chain:
            await e.aclose()


async def play_local(audio: Audio) -> None:
    """Play on this machine (laptop by the projector)."""
    data, fmt = audio
    with tempfile.NamedTemporaryFile(suffix="." + fmt, delete=False) as f:
        f.write(data)
        path = f.name
    for cmd in (["afplay", path], ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", path],
                ["mpg123", "-q", path], ["aplay", "-q", path]):
        if shutil.which(cmd[0]) and not (cmd[0] == "aplay" and fmt != "wav") \
                and not (cmd[0] == "mpg123" and fmt != "mp3"):
            p = await asyncio.create_subprocess_exec(*cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            await p.wait()
            break
    else:
        log.warning("no audio player found (install ffmpeg)")
    os.unlink(path)
