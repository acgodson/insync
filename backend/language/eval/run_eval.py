"""Score the Claude prompts on fixed cases; report accuracy and latency.

    ANTHROPIC_API_KEY=... python -m language.eval.run_eval
    python -m language.eval.run_eval --offline        # baseline: rule-based fallbacks
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from pathlib import Path

from ..claude_client import ClaudeJSON
from ..config import Settings
from ..conversation import Conversation
from ..gloss import Glosser
from ..interpret import Interpreter, Slot
from ..vocab import Vocabulary

CASES = Path(__file__).with_name("cases.json")


def convo_from(history) -> Conversation:
    c = Conversation()
    for who, text in history:
        (c.add_hearing if who == "bob" else c.add_signer)(text)
    return c


async def main(offline: bool) -> None:
    s = Settings()
    s.offline = offline or s.offline
    vocab = Vocabulary(s.vocab_path)  # never the live-taught overlay
    claude = ClaudeJSON(s.claude_model, s.claude_timeout_s, s.offline)
    g = Glosser(vocab, claude, s.setting, s.max_fingerspell_words, ["Alice", "Chidi"])
    it = Interpreter(vocab, claude, s.setting, s.accept_conf, s.accept_margin, s.min_conf)
    cases = json.loads(CASES.read_text())
    lat: dict[str, list[float]] = {"gloss": [], "pick": [], "compose": []}
    score: dict[str, list[bool]] = {k: [] for k in lat}
    print(f"model={s.claude_model if claude.enabled else 'OFFLINE (fallbacks)'}\n")

    for c in cases["gloss"]:
        t = time.perf_counter()
        r = await g.gloss(c["text"], convo_from(c.get("history", [])))
        lat["gloss"].append((time.perf_counter() - t) * 1000)
        fs = [v for k, v in r.items if k == "fingerspell"]
        ok = all(x in r.signs for x in c.get("include", [])) and all(x in fs for x in c.get("fingerspell", []))
        ok &= len(r.items) <= c.get("max_items", 99)
        ok &= ("first" not in c) or (bool(r.items) and r.items[0] == ("sign", c["first"]))
        score["gloss"].append(ok)
        shown = " ".join(v if k == "sign" else f"[{v}]" for k, v in r.items)
        print(f"{'PASS' if ok else 'FAIL'} gloss   {c['text']!r} -> {shown}  ({r.source})")

    for c in cases["pick"]:
        t = time.perf_counter()
        slot = await it.pick([tuple(x) for x in c["candidates"]], c["so_far"], convo_from(c["history"]))
        lat["pick"].append((time.perf_counter() - t) * 1000)
        ok = slot is not None and slot.label == c["expect"]
        score["pick"].append(ok)
        print(f"{'PASS' if ok else 'FAIL'} pick    {c['so_far']} + {[x[0] for x in c['candidates']]} -> "
              f"{slot.label if slot else None} (want {c['expect']}, {slot.source if slot else '-'})")

    for c in cases["compose"]:
        t = time.perf_counter()
        r = await it.compose([Slot(l, 0.9) for l in c["signs"]], convo_from(c["history"]))
        lat["compose"].append((time.perf_counter() - t) * 1000)
        low = r.sentence.lower()
        ok = all(w in low for w in c.get("contains", []))
        ok &= ("contains_any" not in c) or any(w in low for w in c["contains_any"])
        ok &= ("ends" not in c) or r.sentence.rstrip().endswith(c["ends"])
        score["compose"].append(ok)
        print(f"{'PASS' if ok else 'FAIL'} compose {' '.join(c['signs'])} -> {r.sentence!r} ({r.source})")

    print()
    for k in lat:
        xs = sorted(lat[k])
        p95 = xs[min(len(xs) - 1, int(0.95 * len(xs)))]
        print(f"{k:8} {sum(score[k])}/{len(score[k])} pass   p50 {statistics.median(xs):5.0f} ms   p95 {p95:5.0f} ms")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    asyncio.run(main(ap.parse_args().offline))
