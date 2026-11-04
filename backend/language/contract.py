"""Builders for the messages this module emits. Mirrors §6 of the tech breakdown.

Every message carries `type` and `ts` (ms since epoch). Field names here are the
frozen contract; anything marked PROPOSED is opt-in and must be agreed with
integration before it is switched on.
"""
from __future__ import annotations

import time
from typing import Any, Iterable

Msg = dict[str, Any]


def now_ms() -> int:
    return int(time.time() * 1000)


def _m(type_: str, **fields) -> Msg:
    return {"type": type_, "ts": now_ms(), **fields}


def caption(text: str, speaker: str) -> Msg:
    return _m("caption", text=text, speaker=speaker)


def sentence(text: str, speaker: str) -> Msg:
    return _m("sentence", text=text, speaker=speaker)


def sign_recognized(label: str, confidence: float) -> Msg:
    return _m("sign_recognized", label=label, confidence=round(float(confidence), 3))


def unknown_sign() -> Msg:
    return _m("unknown_sign")


def avatar_play(items: Iterable[tuple[str, str]], include_sequence: bool = False) -> Msg:
    """items: ordered (kind, value) pairs, kind in {"sign", "fingerspell"}."""
    items = list(items)
    msg = _m(
        "avatar_play",
        signs=[v for k, v in items if k == "sign"],
        fingerspell=[v for k, v in items if k == "fingerspell"],
    )
    if include_sequence:  # PROPOSED
        msg["sequence"] = [{"kind": k, "value": v} for k, v in items]
    return msg


def status(latency_ms: float, fps: float | None = None) -> Msg:
    return _m("status", latency_ms=round(float(latency_ms)), fps=fps)


def speech_audio(audio_b64: str, fmt: str, text: str) -> Msg:
    """PROPOSED: TTS audio for the app to play to Bob. Only sent when TTS_MODE=service."""
    return _m("speech_audio", audio=audio_b64, format=fmt, text=text)


# Required fields per type, used by tests and by the CLI to self-check output.
REQUIRED = {
    "caption": {"text", "speaker"},
    "sentence": {"text", "speaker"},
    "sign_recognized": {"label", "confidence"},
    "unknown_sign": set(),
    "avatar_play": {"signs", "fingerspell"},
    "status": {"latency_ms", "fps"},
    "speech_audio": {"audio", "format", "text"},
}


def validate(msg: Msg) -> None:
    assert isinstance(msg.get("ts"), int), f"missing ts: {msg}"
    req = REQUIRED.get(msg.get("type"))
    assert req is not None, f"unknown type: {msg.get('type')}"
    missing = req - msg.keys()
    assert not missing, f"{msg['type']} missing {missing}"
