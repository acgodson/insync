"""Thin async wrapper around the Claude Messages API for JSON-schema calls.

Uses structured outputs (output_config.format = json_schema), so responses are
always schema-valid JSON. Callers treat ClaudeUnavailable as "use the fallback".
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time

log = logging.getLogger("almero.language.claude")


class ClaudeUnavailable(RuntimeError):
    pass


class ClaudeJSON:
    def __init__(self, model: str, timeout_s: float = 4.0, offline: bool = False):
        self.model = model
        self.timeout_s = timeout_s
        self.enabled = not offline and bool(os.environ.get("ANTHROPIC_API_KEY"))
        self._client = None
        self.last_latency_ms: float | None = None
        if self.enabled:
            try:
                import anthropic
                # One retry inside the SDK; our own wall-clock timeout bounds the total.
                self._client = anthropic.AsyncAnthropic(timeout=timeout_s, max_retries=1)
            except ImportError:
                log.warning("anthropic SDK not installed; using rule-based fallbacks")
                self.enabled = False

    async def call(self, *, system: str, user: str, schema: dict, max_tokens: int = 400,
                   name: str = "call") -> dict:
        if not self.enabled:
            raise ClaudeUnavailable("Claude disabled (offline mode or no ANTHROPIC_API_KEY)")
        t0 = time.perf_counter()
        try:
            resp = await asyncio.wait_for(
                self._client.messages.create(
                    model=self.model,
                    max_tokens=max_tokens,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                    output_config={"format": {"type": "json_schema", "schema": schema}},
                ),
                timeout=self.timeout_s,
            )
        except Exception as e:  # timeout, network, rate limit, refusal...
            log.warning("Claude %s failed after %.0f ms: %r", name, (time.perf_counter() - t0) * 1000, e)
            raise ClaudeUnavailable(str(e)) from e
        self.last_latency_ms = (time.perf_counter() - t0) * 1000
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        try:
            out = json.loads(text)
        except json.JSONDecodeError as e:  # e.g. max_tokens hit mid-object
            raise ClaudeUnavailable(f"bad JSON ({resp.stop_reason}): {text[:200]}") from e
        log.info("Claude %s %.0f ms -> %s", name, self.last_latency_ms, text[:200])
        return out
