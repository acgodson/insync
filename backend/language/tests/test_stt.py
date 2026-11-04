import base64

import numpy as np

from language.stt import Endpointer, decode_pcm, resample
from .conftest import speech_pcm


def feed_all(ep, x, chunk=1600):
    out = []
    for i in range(0, len(x), chunk):
        out += ep.feed(x[i:i + chunk])
    return out


def test_one_utterance_with_preroll():
    utts = feed_all(Endpointer(end_silence_ms=600), speech_pcm(800, 1000))
    assert len(utts) == 1
    assert 700 <= utts[0].voiced_ms <= 900
    assert len(utts[0].audio) / 16 >= 800 + 200  # speech + pre-roll


def test_short_pause_stays_one_utterance_long_pause_splits():
    a, b = speech_pcm(600, 300), speech_pcm(600, 1200)
    assert len(feed_all(Endpointer(end_silence_ms=700), np.concatenate([a, b]))) == 1
    a = speech_pcm(600, 1200)
    assert len(feed_all(Endpointer(end_silence_ms=700), np.concatenate([a, b]))) == 2


def test_clicks_are_ignored_and_flush_ends_speech():
    ep = Endpointer()
    assert feed_all(ep, speech_pcm(60, 1000)) == []
    feed_all(ep, speech_pcm(800, 0))
    assert len(ep.flush()) == 1


def test_decode_and_resample():
    x = (np.arange(800) % 100).astype("<i2")
    assert np.array_equal(decode_pcm(base64.b64encode(x.tobytes()).decode()), x)
    assert len(decode_pcm(base64.b64encode(x.tobytes()).decode(), rate=8000)) == 1600
    assert len(resample(np.zeros(4410, np.int16), 44100, 16000)) == 1600
