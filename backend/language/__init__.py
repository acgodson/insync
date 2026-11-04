"""Language step: hearing person's text -> ordered avatar signs. Mock rules for the skeleton.

# TODO(phase2): Claude ordering (grammar of the target sign language) + ElevenLabs voice.
# The teammate's language/TTS work replaces to_signs() and speak(); keep these signatures.
"""
import re

from .vocab import BASE_VOCAB, MAX_FINGERSPELL_LEN, STOP_WORDS, SYNONYMS


def to_signs(text, taught_labels=()):
    """-> {"signs": [...], "fingerspell": [...]}, order preserved (mock.ts toSigns rules)."""
    vocab = BASE_VOCAB | set(taught_labels)
    signs, fingerspell = [], []
    for raw in text.split():
        word = re.sub(r"[^A-Za-z']", "", raw)
        if not word:
            continue
        w = SYNONYMS.get(word.lower(), word.lower())
        if w in vocab:
            signs.append(w)
        elif w in STOP_WORDS:
            continue
        elif word[0].isupper() or len(w) <= MAX_FINGERSPELL_LEN:
            fingerspell.append(w)
    return {"signs": signs, "fingerspell": fingerspell}


def speak(text, voice):
    """Text the hearing side should hear. Native TTS on the phone for now; nothing to do here."""
    # TODO(phase2): ElevenLabs
    return None
