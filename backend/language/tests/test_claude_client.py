"""Exercises the real ClaudeJSON code path against a fake SDK client."""
import asyncio
import json
import sys
import types

import pytest

from language.claude_client import ClaudeJSON, ClaudeUnavailable
from language.prompts import compose_schema, gloss_schema, pick_schema


class _Block:
    def __init__(self, text):
        self.type, self.text = "text", text


class _Resp:
    def __init__(self, text, stop="end_turn"):
        self.content, self.stop_reason = [_Block(text)], stop


def install_fake_sdk(monkeypatch, behaviour):
    seen = {}

    class Messages:
        async def create(self, **kw):
            seen.update(kw)
            return await behaviour(kw)

    class AsyncAnthropic:
        def __init__(self, **kw):
            seen["client_kwargs"] = kw
            self.messages = Messages()
    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(AsyncAnthropic=AsyncAnthropic))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    return seen


def test_request_shape_and_parse(monkeypatch):
    async def ok(kw):
        return _Resp(json.dumps({"label": "WATER"}))
    seen = install_fake_sdk(monkeypatch, ok)
    c = ClaudeJSON("claude-haiku-5-5", timeout_s=2)
    out = asyncio.run(c.call(system="sys", user="u", schema=pick_schema(["NAME", "WATER"]), name="pick"))
    assert out == {"label": "WATER"}
    assert seen["model"] == "claude-haiku-5-5" and seen["system"] == "sys"
    assert seen["output_config"]["format"]["type"] == "json_schema"
    assert seen["output_config"]["format"]["schema"]["properties"]["label"]["enum"] == ["NAME", "WATER"]
    assert seen["client_kwargs"]["max_retries"] == 1


def test_timeout_becomes_unavailable(monkeypatch):
    async def slow(kw):
        await asyncio.sleep(5)
    install_fake_sdk(monkeypatch, slow)
    c = ClaudeJSON("m", timeout_s=0.05)
    with pytest.raises(ClaudeUnavailable):
        asyncio.run(c.call(system="s", user="u", schema={}))


def test_truncated_json_becomes_unavailable(monkeypatch):
    async def cut(kw):
        return _Resp('{"sentence": "I want', "max_tokens")
    install_fake_sdk(monkeypatch, cut)
    with pytest.raises(ClaudeUnavailable):
        asyncio.run(ClaudeJSON("m").call(system="s", user="u", schema={}))


def test_offline_or_no_key_is_disabled(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert not ClaudeJSON("m").enabled
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    assert not ClaudeJSON("m", offline=True).enabled


def _walk(node):
    yield node
    if isinstance(node, dict):
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def test_schemas_stay_inside_structured_output_limits(vocab):
    """Supported subset: string enums, anyOf, minItems 0/1 only, objects closed."""
    for schema in (gloss_schema(vocab), pick_schema(["A", "B"]), compose_schema(["A"])):
        for n in _walk(schema):
            if isinstance(n, dict):
                if n.get("type") == "object":
                    assert n.get("additionalProperties") is False
                assert n.get("minItems", 0) in (0, 1) and "maxItems" not in n
                if "enum" in n:
                    assert all(isinstance(e, str) for e in n["enum"])
