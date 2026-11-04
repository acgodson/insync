"""Sign -> English (signer direction): the context step.

pick():    choose among recognition's top-3 for one sign (Claude only when unsure)
compose(): turn the utterance's signs into the sentence Alice means
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import prompts
from .claude_client import ClaudeJSON, ClaudeUnavailable
from .conversation import Conversation
from .vocab import Vocabulary, norm_label

WH = {"WHAT", "WHERE", "WHO", "HOW", "WHY", "WHEN"}


@dataclass
class Slot:
    label: str
    confidence: float
    alternatives: list[tuple[str, float]] = field(default_factory=list)
    source: str = "fast"  # fast | claude | fallback | single


@dataclass
class Composed:
    sentence: str
    labels: list[str]
    source: str  # claude | canned | fallback


def fallback_sentence(labels: list[str], vocab: Vocabulary) -> str:
    words = [vocab.english(l) for l in labels]
    if not words:
        return ""
    s = " ".join(words)
    s = s[0].upper() + s[1:]
    return s + ("?" if any(l in WH for l in labels) else ".")


class Interpreter:
    def __init__(self, vocab: Vocabulary, claude: ClaudeJSON, setting: str,
                 accept_conf=0.80, accept_margin=0.15, min_conf=0.45):
        self.vocab, self.claude, self.setting = vocab, claude, setting
        self.accept_conf, self.accept_margin, self.min_conf = accept_conf, accept_margin, min_conf

    async def pick(self, candidates: list[tuple[str, float]], so_far: list[str],
                   convo: Conversation) -> Slot | None:
        """Returns None when the sign should be reported as unknown."""
        cands = sorted(((norm_label(l), float(c)) for l, c in candidates), key=lambda x: -x[1])
        if not cands or cands[0][1] < self.min_conf:
            return None
        top, conf = cands[0]
        alts = [c for c in cands[1:] if c[1] >= self.min_conf]
        margin = conf - (cands[1][1] if len(cands) > 1 else 0.0)
        if not alts:
            return Slot(top, conf, [], "single")
        if conf >= self.accept_conf and margin >= self.accept_margin:
            return Slot(top, conf, alts, "fast")
        viable = [cands[0], *alts]
        labels = [l for l, _ in viable]
        try:
            out = await self.claude.call(
                system=prompts.pick_system(self.vocab, self.setting),
                user=prompts.pick_user(viable, so_far, convo.recent(), self.vocab),
                schema=prompts.pick_schema(labels), max_tokens=50, name="pick")
            chosen = norm_label(out["label"])
            if chosen in labels:
                c = dict(viable)[chosen]
                return Slot(chosen, c, [v for v in viable if v[0] != chosen], "claude")
        except (ClaudeUnavailable, KeyError):
            pass
        return Slot(top, conf, alts, "fallback")

    async def compose(self, slots: list[Slot], convo: Conversation) -> Composed:
        labels = [s.label for s in slots]
        if not slots:
            return Composed("", [], "fallback")
        if len(slots) == 1:
            sign = self.vocab.get(labels[0])
            if sign and sign.speak:
                return Composed(sign.speak, labels, "canned")
        allowed = sorted({s.label for s in slots} | {l for s in slots for l, _ in s.alternatives})
        try:
            out = await self.claude.call(
                system=prompts.compose_system(self.vocab, self.setting, convo.signer_name),
                user=prompts.compose_user(
                    [{"label": s.label, "alternatives": s.alternatives} for s in slots],
                    convo.recent(), self.vocab),
                schema=prompts.compose_schema(allowed), max_tokens=200, name="compose")
            sentence = out.get("sentence", "").strip()
            if sentence:
                used = [norm_label(l) for l in out.get("labels", [])] or labels
                return Composed(sentence, used, "claude")
        except ClaudeUnavailable:
            pass
        return Composed(fallback_sentence(labels, self.vocab), labels, "fallback")
