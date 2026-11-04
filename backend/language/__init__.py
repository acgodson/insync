"""Almero language & voice module (Cluster C).

STT, Claude prompts (context selection, English -> sign order), TTS, and the
signer recording session tooling. The integration surface is LanguageModule.
"""


def __getattr__(name):  # lazy, so `python -m language.sessions` doesn't pull in audio deps
    if name == "LanguageModule":
        from .module import LanguageModule
        return LanguageModule
    if name == "Vocabulary":
        from .vocab import Vocabulary
        return Vocabulary
    raise AttributeError(name)
