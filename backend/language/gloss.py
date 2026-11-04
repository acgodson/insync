"""English -> ordered sign sequence for the avatar (reply direction).

Claude does the real work; the result is validated against the vocabulary and a
rule-based glosser takes over whenever Claude is unavailable or too slow.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import prompts
from .claude_client import ClaudeJSON, ClaudeUnavailable
from .conversation import Conversation
from .vocab import Vocabulary

Item = tuple[str, str]  # ("sign", LABEL) | ("fingerspell", WORD)

STOPWORDS = set("""
a an the is are am was were be been being to of in on at for with by from as
do does did will would shall should can could may might must it its this that these those there
and or but so if then than um uh er erm hmm like just really very okay ok oh well also please's
let let's us we our they them their he him his she her
about say said tell told get got make made have has had some any all up out into over
""".split())
NEGATIONS = {"can't", "cannot", "won't", "isn't", "aren't", "wasn't", "weren't", "haven't", "hasn't",
             "shouldn't", "wouldn't", "couldn't", "mustn't"}
CLITIC = re.compile(r"^(.+?)'(s|re|m|ll|ve|d)$")


def _tokens(text: str) -> tuple[list[str], list[str]]:
    """Split clitics ("what's" -> "what"), keep negation as a word the vocab knows."""
    raw, low = [], []
    for t in re.findall(r"[A-Za-z0-9']+", text.replace("’", "'")):
        t = t.strip("'")
        if not t:
            continue
        m = CLITIC.match(t.lower())
        if m and t.lower() not in NEGATIONS:
            raw.append(t[: len(m.group(1))]); low.append(m.group(1))
            continue
        raw.append(t); low.append(t.lower())
    return raw, low


@dataclass
class GlossResult:
    items: list[Item]
    source: str  # "claude" | "fallback"
    dropped: list[str] = field(default_factory=list)

    @property
    def signs(self) -> list[str]:
        return [v for k, v in self.items if k == "sign"]


def _fs_word(word: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", word.upper())


def _lemmas(tok: str) -> list[str]:
    out = []
    for suf, rep in (("'s", ""), ("ies", "y"), ("es", ""), ("s", ""), ("ing", ""), ("ing", "e"),
                     ("ed", ""), ("ed", "e"), ("ly", "")):
        if tok.endswith(suf) and len(tok) - len(suf) >= 3:
            out.append(tok[: -len(suf)] + rep)
    return out


def fallback_gloss(text: str, vocab: Vocabulary, max_fingerspell: int = 2,
                   names: list[str] = ()) -> GlossResult:
    """Deterministic glosser: longest phrase match -> lemma match -> drop stopwords ->
    fingerspell names first, then other unknown content words, within budget."""
    raw, toks = _tokens(text)
    known_names = {n.lower() for n in names}
    slots: list[tuple[str, str, int]] = []  # (kind, value, priority) priority: 0 sign, 1 name, 2 other
    dropped: list[str] = []
    i = 0
    while i < len(toks):
        matched = False
        for n in range(min(vocab.max_phrase_words, len(toks) - i), 0, -1):
            phrase = " ".join(toks[i:i + n])
            label = vocab.phrase_index.get(phrase)
            if label is None and n == 1 and phrase in NEGATIONS and vocab.canonical("NO"):
                label = "NO"
            if label is None and n == 1:
                label = next((vocab.phrase_index[l] for l in _lemmas(phrase) if l in vocab.phrase_index), None)
            if label:
                slots.append(("sign", label, 0))
                i += n
                matched = True
                break
        if matched:
            continue
        tok, orig = toks[i], raw[i]
        if tok in STOPWORDS or len(tok) < 2:
            dropped.append(orig)
        else:
            is_name = tok in known_names or (orig[0].isupper() and i > 0)
            slots.append(("fingerspell", _fs_word(orig), 1 if is_name else 2))
        i += 1

    # Spend the fingerspelling budget on names first, then other unknown words.
    fs_rank = sorted((p, idx) for idx, (k, _, p) in enumerate(slots) if k == "fingerspell")
    keep = {idx for _, idx in fs_rank[:max_fingerspell]}
    items: list[Item] = []
    for idx, (k, v, _) in enumerate(slots):
        if k == "fingerspell" and idx not in keep:
            dropped.append(v.lower())
            continue
        if items and items[-1] == (k, v):  # "thank you thank you" -> one sign
            continue
        items.append((k, v))
    return GlossResult(items, "fallback", dropped)


def validate_items(raw_items: list[dict], vocab: Vocabulary, max_fingerspell: int) -> list[Item]:
    """Normalise Claude's output: canonical labels, fingerspelled words we actually
    have a sign for become signs, enforce the fingerspelling budget."""
    items: list[Item] = []
    fs = 0
    for it in raw_items:
        if "sign" in it:
            label = vocab.canonical(it["sign"])
            if label:
                items.append(("sign", label))
                continue
            word = it["sign"]  # should be impossible with enum decoding; degrade gracefully
        else:
            word = it.get("fingerspell", "")
        label = vocab.phrase_index.get(word.lower().replace("-", " "))
        if label:
            items.append(("sign", label))
            continue
        w = _fs_word(word)
        if w and fs < max_fingerspell:
            items.append(("fingerspell", w))
            fs += 1
    return items


class Glosser:
    def __init__(self, vocab: Vocabulary, claude: ClaudeJSON, setting: str, max_fingerspell: int = 2,
                 names: list[str] = ()):
        self.vocab = vocab
        self.names = list(names)
        self.claude = claude
        self.setting = setting
        self.max_fs = max_fingerspell
        self._cache_key = None
        self._system = self._schema = None

    def _prompt_parts(self):
        key = (self.vocab.version, self.setting)
        if key != self._cache_key:  # rebuild only when vocab changes (live teaching)
            self._system = prompts.gloss_system(self.vocab, self.setting, self.max_fs, self.names)
            self._schema = prompts.gloss_schema(self.vocab)
            self._cache_key = key
        return self._system, self._schema

    async def gloss(self, text: str, convo: Conversation) -> GlossResult:
        text = text.strip()
        if not text:
            return GlossResult([], "fallback")
        system, schema = self._prompt_parts()
        try:
            out = await self.claude.call(
                system=system,
                user=prompts.gloss_user(text, convo.recent(), convo.hearing_name),
                schema=schema, name="gloss")
            return GlossResult(validate_items(out.get("items", []), self.vocab, self.max_fs), "claude")
        except ClaudeUnavailable:
            return fallback_gloss(text, self.vocab, self.max_fs, self.names)
