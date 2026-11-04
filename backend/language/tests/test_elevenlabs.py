"""ElevenLabs engine against a mock HTTP server (httpx.MockTransport)."""
import asyncio
import io
import json
import wave

import httpx
import pytest

from language.module import LanguageModule
from language.tts import TTS, ElevenLabsError, ElevenLabsTTS, TTSEngine, resolve_engine
from .conftest import FakeClaude, FakeSTT

# Exact body the live API returned for a bad key (probed while building this).
INVALID_KEY = {"detail": {"type": "authentication_error", "code": "unauthorized",
                          "message": "Invalid API key", "status": "invalid_api_key", "request_id": "x"}}


class Server:
    """Records requests; responds via a handler."""

    def __init__(self, handler):
        self.requests = []
        self.handler = handler

    def client(self):
        def h(req):
            self.requests.append(req)
            return self.handler(req)
        return httpx.AsyncClient(transport=httpx.MockTransport(h))


def ok_mp3(req):
    return httpx.Response(200, content=b"ID3" + b"\x00" * 100, headers={"content-type": "audio/mpeg"})


def el(server, **kw):
    return ElevenLabsTTS(api_key="sk_test", voice_id=kw.pop("voice_id", "VOICE1"), client=server.client(), **kw)


class Backup(TTSEngine):
    name, voice = "backup", ""

    def __init__(self):
        self.calls = 0

    async def synth(self, text):
        self.calls += 1
        return b"RIFFbackup", "wav"


def test_request_shape():
    srv = Server(ok_mp3)
    audio = asyncio.run(el(srv, model_id="eleven_flash_v2_5", speed=1.1).synth("I need water."))
    assert audio[1] == "mp3" and audio[0].startswith(b"ID3")
    r = srv.requests[0]
    assert r.method == "POST" and r.url.path == "/v1/text-to-speech/VOICE1"
    assert r.url.params["output_format"] == "mp3_44100_64"
    assert r.headers["xi-api-key"] == "sk_test"
    body = json.loads(r.content)
    assert body["text"] == "I need water." and body["model_id"] == "eleven_flash_v2_5"
    assert body["voice_settings"] == {"stability": 0.5, "similarity_boost": 0.75, "speed": 1.1}


def test_errors_are_readable():
    srv = Server(lambda r: httpx.Response(401, json=INVALID_KEY))
    with pytest.raises(ElevenLabsError) as e:
        asyncio.run(el(srv).synth("hi"))
    assert e.value.code == "invalid_api_key" and "ELEVENLABS_API_KEY" in str(e.value)
    srv = Server(lambda r: httpx.Response(422, json={"detail": [{"msg": "bad output_format"}]}))
    with pytest.raises(ElevenLabsError) as e:
        asyncio.run(el(srv).synth("hi"))
    assert "bad output_format" in str(e.value)


def test_failure_falls_back_and_breaker_stops_retrying():
    srv = Server(lambda r: httpx.Response(429, json={"detail": {"status": "quota_exceeded", "message": "no credits"}}))
    backup = Backup()
    tts = TTS(engines=[el(srv), backup])

    async def go():
        a = await tts.synth("Hello!")
        b = await tts.synth("Goodbye!")
        return a, b
    a, b = asyncio.run(go())
    assert a[0] == b"RIFFbackup" and b[0] == b"RIFFbackup"
    assert len(srv.requests) == 1  # second sentence skipped ElevenLabs entirely
    assert tts.last_engine == "backup"


def test_pcm_is_wrapped_as_wav():
    srv = Server(lambda r: httpx.Response(200, content=b"\x01\x00" * 1600))
    data, fmt = asyncio.run(el(srv, output_format="pcm_16000").synth("hi"))
    assert fmt == "wav"
    with wave.open(io.BytesIO(data)) as w:
        assert w.getframerate() == 16000 and w.getnframes() == 1600


def test_list_voices():
    def h(req):
        assert req.url.path == "/v2/voices" and req.url.params["search"] == "nigerian"
        return httpx.Response(200, json={"voices": [
            {"voice_id": "abc", "name": "Ada", "category": "professional",
             "labels": {"accent": "nigerian", "gender": "female"}, "description": "Warm, clear"}],
            "has_more": False})
    vs = asyncio.run(el(Server(h)).list_voices("nigerian"))
    assert vs == [{"voice_id": "abc", "name": "Ada", "category": "professional", "accent": "nigerian",
                   "gender": "female", "description": "Warm, clear"}]


def test_set_voice_clears_cache_and_uses_new_voice():
    srv = Server(ok_mp3)
    tts = TTS(engines=[el(srv)])

    async def go():
        await tts.synth("Hello!")
        assert tts.set_voice("VOICE2") == "elevenlabs"
        await tts.synth("Hello!")
    asyncio.run(go())
    assert [r.url.path for r in srv.requests] == ["/v1/text-to-speech/VOICE1", "/v1/text-to-speech/VOICE2"]


def test_emergency_phrases_survive_network_loss(tmp_path):
    srv_ok = Server(ok_mp3)
    asyncio.run(TTS(engines=[el(srv_ok)], cache_dir=tmp_path).warm(["Help! I need help.", "Fire! There's a fire!"]))
    assert len(list(tmp_path.iterdir())) == 2
    srv_down = Server(lambda r: (_ for _ in ()).throw(httpx.ConnectError("no network")))
    tts = TTS(engines=[el(srv_down)], cache_dir=tmp_path)
    audio = asyncio.run(tts.synth("Help! I need help."))
    assert audio and audio[0].startswith(b"ID3") and not srv_down.requests
    # ordinary sentences are never written to disk
    asyncio.run(TTS(engines=[el(srv_ok)], cache_dir=tmp_path).synth("I need water."))
    assert len(list(tmp_path.iterdir())) == 2


def test_auto_engine_selection():
    assert resolve_engine("auto", "sk_x") == "elevenlabs"
    assert resolve_engine("auto", "") == "edge"
    assert resolve_engine("system", "sk_x") == "system"
    chain = TTS("auto", elevenlabs={"api_key": "sk_x", "voice_id": "V"}).chain
    assert [e.name for e in chain] == ["elevenlabs", "edge", "system"]
    assert [e.name for e in TTS("elevenlabs", elevenlabs={"api_key": ""}).chain] == ["edge", "system"]


def test_module_service_mode_with_elevenlabs_and_profile_voice(settings, vocab, tmp_path):
    settings.tts_mode = "service"
    srv = Server(ok_mp3)
    tts = TTS(engines=[el(srv)], cache_dir=tmp_path)

    async def go():
        out = []
        lm = LanguageModule(out.append, settings, vocab=vocab, claude=FakeClaude(), stt=FakeSTT([]), tts=tts)
        await lm.handle({"type": "profile", "ts": 0, "head": {}, "voice_id": "ALICE_VOICE"})
        await lm.on_sign_candidates([{"label": "HELP", "confidence": .9}])
        while lm._bg:
            await asyncio.sleep(0.01)
        await lm.close()
        return out
    out = asyncio.run(go())
    kinds = [m["type"] for m in out if m["type"] != "status"]
    assert kinds == ["sign_recognized", "sentence", "speech_audio"]
    assert out[-1]["format"] == "mp3" and out[-1]["text"] == "Help! I need help."
    assert srv.requests[-1].url.path == "/v1/text-to-speech/ALICE_VOICE"
