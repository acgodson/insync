import asyncio
import shutil
from pathlib import Path

import numpy as np
import pytest

from language.claude_client import ClaudeUnavailable
from language.config import Settings
from language.vocab import Vocabulary

VOCAB = Path(__file__).resolve().parents[1] / "vocab.json"


@pytest.fixture
def vocab(tmp_path):
    return Vocabulary(VOCAB, tmp_path / "vocab.local.json")


class FakeClaude:
    """Stands in for ClaudeJSON. `responses` maps call name -> dict | Exception | callable(kwargs)."""

    def __init__(self, responses=None, enabled=True):
        self.responses = responses or {}
        self.enabled = enabled
        self.calls = []

    async def call(self, *, system, user, schema, max_tokens=400, name="call"):
        self.calls.append({"name": name, "system": system, "user": user, "schema": schema})
        r = self.responses.get(name)
        if r is None or not self.enabled:
            raise ClaudeUnavailable("fake: no response")
        if isinstance(r, Exception):
            raise r
        return r(schema) if callable(r) else r


class FakeSTT:
    name = "fake"

    def __init__(self, texts):
        self.texts = list(texts)

    def warmup(self):
        pass

    def transcribe(self, audio):
        return self.texts.pop(0) if self.texts else ""


@pytest.fixture
def settings(tmp_path):
    s = Settings()
    s.vocab_local_path = tmp_path / "vocab.local.json"
    s.tts_mode = "app"
    s.sign_pause_s = 0.2
    s.stt_engine = "none"
    return s


def speech_pcm(ms_speech=800, ms_silence=1000, amp=6000):
    rng = np.random.default_rng(1)
    t = np.arange(int(16 * ms_speech)) / 16000
    speech = amp * np.sin(2 * np.pi * 200 * t) + rng.normal(0, 50, len(t))
    sil = rng.normal(0, 50, int(16 * ms_silence))
    return np.concatenate([sil[:4800], speech, sil]).astype(np.int16)


def run(coro):
    return asyncio.run(coro)
