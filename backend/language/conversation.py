"""Rolling conversation history shared by every Claude call (both directions)."""
from __future__ import annotations

from collections import deque


class Conversation:
    def __init__(self, signer: str = "alice", hearing: str = "bob", max_turns: int = 10):
        self.signer_name = f"{signer.capitalize()} (Deaf, signing)"
        self.hearing_name = f"{hearing.capitalize()} (hearing, speaking)"
        self.turns: deque[tuple[str, str]] = deque(maxlen=max_turns)

    def add_signer(self, text: str) -> None:
        self.turns.append((self.signer_name, text))

    def add_hearing(self, text: str) -> None:
        self.turns.append((self.hearing_name, text))

    def recent(self) -> list[tuple[str, str]]:
        return list(self.turns)

    def clear(self) -> None:
        self.turns.clear()
