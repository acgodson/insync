"""The sign vocabulary: the single source of truth for both directions.

Recognition matches against these labels; the language module may only ask the
avatar to play these labels. Signs taught live are added at runtime and persisted
to vocab.local.json.
"""
from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path


def norm_label(label: str) -> str:
    """'thank you' / 'Thank_You' / 'THANK-YOU' -> 'THANK-YOU'."""
    return re.sub(r"[\s_]+", "-", label.strip()).upper()


@dataclass
class Sign:
    label: str
    english: str
    synonyms: list[str] = field(default_factory=list)
    category: str = "general"
    tier: int = 3
    emergency: bool = False
    speak: str | None = None  # canned sentence when this sign is the whole utterance
    taught_live: bool = False

    def to_json(self) -> dict:
        d = {"label": self.label, "english": self.english, "synonyms": self.synonyms,
             "category": self.category, "tier": self.tier, "emergency": self.emergency}
        if self.speak:
            d["speak"] = self.speak
        if self.taught_live:
            d["taught_live"] = True
        return d


class Vocabulary:
    def __init__(self, path: Path, local_path: Path | None = None):
        self.path = Path(path)
        self.local_path = Path(local_path) if local_path else None
        self._lock = threading.Lock()
        doc = json.loads(self.path.read_text())
        self.language: str = doc.get("language", "NSL")
        self.grammar_notes: list[str] = doc.get("grammar_notes", [])
        self.signs: dict[str, Sign] = {}
        for s in doc["signs"]:
            self._put(Sign(**{**s, "label": norm_label(s["label"])}))
        if self.local_path and self.local_path.exists():
            for s in json.loads(self.local_path.read_text()).get("signs", []):
                self._put(Sign(**{**s, "label": norm_label(s["label"])}))
        self.version = 0  # bumps on every change; prompts/schemas key off it
        self._reindex()

    # ---- lookup -------------------------------------------------------
    def _put(self, sign: Sign) -> None:
        self.signs[sign.label] = sign

    def _reindex(self) -> None:
        """phrase (lowercase words) -> label, for the rule-based fallback."""
        idx: dict[str, str] = {}
        for s in self.signs.values():  # synonyms first so primary meanings win
            for syn in s.synonyms:
                idx.setdefault(syn.lower(), s.label)
        for s in self.signs.values():
            idx[s.english.lower()] = s.label
            idx[s.label.lower().replace("-", " ")] = s.label
        self.phrase_index = idx
        self.max_phrase_words = max(len(p.split()) for p in idx)

    def __contains__(self, label: str) -> bool:
        return norm_label(label) in self.signs

    def get(self, label: str) -> Sign | None:
        return self.signs.get(norm_label(label))

    def canonical(self, label: str) -> str | None:
        """Case-insensitive match back to the canonical label (structured-output enums
        don't guarantee capitalisation)."""
        n = norm_label(label)
        return n if n in self.signs else None

    @property
    def labels(self) -> list[str]:
        return sorted(self.signs)

    def english(self, label: str) -> str:
        s = self.get(label)
        return s.english if s else label.replace("-", " ").lower()

    def by_tier(self, max_tier: int) -> list[Sign]:
        return sorted((s for s in self.signs.values() if s.tier <= max_tier),
                      key=lambda s: (not s.emergency, s.tier, s.label))

    def prompt_listing(self) -> str:
        lines = []
        for s in sorted(self.signs.values(), key=lambda s: s.label):
            syn = f" (also: {', '.join(s.synonyms)})" if s.synonyms else ""
            lines.append(f"{s.label}: {s.english}{syn}")
        return "\n".join(lines)

    # ---- live teaching ----------------------------------------------------
    def add_sign(self, label: str, english: str | None = None, synonyms: list[str] | None = None) -> Sign:
        label = norm_label(label)
        with self._lock:
            existing = self.signs.get(label)
            if existing:
                return existing
            sign = Sign(label=label, english=english or label.replace("-", " ").lower(),
                        synonyms=synonyms or [], category="taught", tier=3, taught_live=True)
            self._put(sign)
            self.version += 1
            self._reindex()
            self._persist_local()
            return sign

    def _persist_local(self) -> None:
        if not self.local_path:
            return
        taught = [s.to_json() for s in self.signs.values() if s.taught_live]
        tmp = self.local_path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"signs": taught}, indent=1))
        tmp.replace(self.local_path)
