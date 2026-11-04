"""Word lists for speech -> avatar signs (same rules as the web mock's toSigns)."""

# Words the avatar can sign procedurally. Anything else short is fingerspelled.
BASE_VOCAB = {
    "hello", "good", "morning", "you", "understand", "homework", "yes", "no", "help", "which",
    "okay", "together", "thank", "please", "what", "name", "class", "question", "book", "read",
    "write", "today", "now", "me", "need", "want", "go", "sit", "stop", "finish", "again", "see",
    "tomorrow", "page",
}

SYNONYMS = {"hi": "hello", "thanks": "thank", "i": "me", "fractions": "fraction", "ok": "okay", "pages": "page"}

STOP_WORDS = {
    "a", "an", "the", "do", "does", "is", "are", "to", "of", "and", "let's", "lets", "it", "this",
    "that", "with", "at", "on", "in", "be", "will",
}

# Unknown words longer than this are left to the captions rather than fingerspelled.
MAX_FINGERSPELL_LEN = 6
