import asyncio
import base64

from language import contract
from language.module import LanguageModule
from .conftest import FakeClaude, FakeSTT, speech_pcm


def make(settings, vocab, claude=None, stt=None):
    out = []

    async def emit(m):
        contract.validate(m)
        out.append(m)
    lm = LanguageModule(emit, settings, vocab=vocab, claude=claude or FakeClaude(), stt=stt or FakeSTT([]))
    return lm, out


def types(out):
    return [m["type"] for m in out if m["type"] != "status"]


def test_audio_to_caption_then_avatar(settings, vocab):
    async def go():
        lm, out = make(settings, vocab, FakeClaude({"gloss": {"items": [{"sign": "HELLO"}, {"fingerspell": "ADA"}]}}),
                       FakeSTT(["Hello Ada"]))
        pcm = speech_pcm(800, 1200).tobytes()
        for i in range(0, len(pcm), 3200):
            await lm.handle({"type": "audio", "ts": 0, "pcm": base64.b64encode(pcm[i:i + 3200]).decode(), "rate": 16000})
        while lm._bg:
            await asyncio.sleep(0.01)
        return out
    out = asyncio.run(go())
    assert types(out) == ["caption", "avatar_play"]
    assert out[0]["text"] == "Hello Ada" and out[0]["speaker"] == "bob"
    assert out[1]["signs"] == ["HELLO"] and out[1]["fingerspell"] == ["ADA"]
    assert any(m["type"] == "status" for m in out)


def test_signs_compose_after_pause(settings, vocab):
    async def go():
        fc = FakeClaude({"compose": {"labels": ["I", "WANT", "WATER"], "sentence": "I want some water."}})
        lm, out = make(settings, vocab, fc)
        await lm.on_sign_candidates([{"label": "I", "confidence": .95}])
        await lm.on_sign_candidates([{"label": "WANT", "confidence": .9}])
        await lm.on_sign_candidates([{"label": "WATER", "confidence": .9}])
        assert "sentence" not in types(out)  # still waiting for the pause
        await asyncio.sleep(settings.sign_pause_s + 0.15)
        return out, lm
    out, lm = asyncio.run(go())
    assert types(out) == ["sign_recognized"] * 3 + ["sentence"]
    assert out[-2]["text"] == "I want some water." and out[-2]["speaker"] == "alice"
    assert lm.convo.recent()[-1][1] == "I want some water."


def test_emergency_speaks_immediately(settings, vocab):
    settings.sign_pause_s = 10

    async def go():
        lm, out = make(settings, vocab)
        await lm.on_sign_candidates([{"label": "FIRE", "confidence": .9}])
        return out
    out = asyncio.run(go())
    assert types(out) == ["sign_recognized", "sentence"] and out[1]["text"] == "Fire! There's a fire!"


def test_unknown_then_teach_live(settings, vocab):
    async def go():
        lm, out = make(settings, vocab)
        await lm.on_sign_candidates([{"label": "SCIENCE", "confidence": .3}])
        await lm.handle({"type": "teach_stop", "ts": 0, "label": "science"})
        await lm.on_text("We learn science today")
        return out
    out = asyncio.run(go())
    assert types(out)[0] == "unknown_sign"
    play = [m for m in out if m["type"] == "avatar_play"][0]
    assert "SCIENCE" in play["signs"]


def test_service_tts_mode_emits_speech_audio(settings, vocab):
    settings.tts_mode = "service"

    class FakeTTS:
        async def synth(self, text):
            return (b"ID3fake", "mp3")

        async def warm(self, phrases):
            pass

    async def go():
        out = []
        lm = LanguageModule(out.append, settings, vocab=vocab, claude=FakeClaude(), stt=FakeSTT([]), tts=FakeTTS())
        await lm.on_sign_candidates([{"label": "HELP", "confidence": .9}])
        while lm._bg:
            await asyncio.sleep(0.01)
        return out
    out = asyncio.run(go())
    sa = [m for m in out if m["type"] == "speech_audio"][0]
    assert sa["format"] == "mp3" and base64.b64decode(sa["audio"]) == b"ID3fake"
