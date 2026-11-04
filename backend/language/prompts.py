"""System prompts and JSON schemas for the three Claude calls.

1. gloss    English (Bob's speech) -> ordered NSL signs / fingerspelling
2. pick     top-3 sign candidates -> the one that fits the conversation
3. compose  a sequence of signs -> the English sentence Alice means

The sign label is an `enum` in each schema, so constrained decoding guarantees
Claude can only return signs we actually have clips for.
"""
from __future__ import annotations

from .vocab import Vocabulary


def _history(turns: list[tuple[str, str]]) -> str:
    if not turns:
        return "(conversation just started)"
    return "\n".join(f"{who}: {text}" for who, text in turns)


# ---------------------------------------------------------------- gloss
def gloss_system(vocab: Vocabulary, setting: str, max_fingerspell: int, names: list[str] = ()) -> str:
    notes = "\n".join(f"- {n}" for n in vocab.grammar_notes)
    names_line = f"\nPeople and places in this conversation (fingerspell with this spelling; speech recognition may garble them): {', '.join(names)}\n" if names else ""
    return f"""You convert spoken English into a sequence of signs for an avatar that signs {vocab.language} (Nigerian Sign Language) to a Deaf person, live, in under three seconds.

The avatar can ONLY play signs from the vocabulary below, or fingerspell a word letter by letter.

Rules:
1. Convey the meaning, not the words. Map synonyms and paraphrases to the closest vocabulary sign ("restroom" -> TOILET, "can you say that again" -> AGAIN).
2. Leave out words that are not signed and that the meaning survives without: articles, "is/are/am", filler, politeness padding.
3. Fingerspell only essential words that have no sign, mainly names of people and places. At most {max_fingerspell} fingerspelled words per sentence; fingerspelling is slow. Write a fingerspelled word in uppercase letters A-Z or digits, no spaces.
4. Order the signs the way a signer would, following the grammar notes.
5. Keep it short enough to follow in real time: usually 1 to 8 items. Drop low-value detail before meaning-critical content. Safety information (fire, pain, help, stop, doctor) always survives.
6. If the speech is only filler or noise ("um", "okay so"), return an empty list.

Grammar notes from our native signer:
{notes}

Setting: {setting}
{names_line}
Vocabulary (LABEL: meaning):
{vocab.prompt_listing()}"""


def gloss_user(text: str, history: list[tuple[str, str]], hearing_name: str) -> str:
    return f"""Recent conversation:
{_history(history)}

{hearing_name} just said: "{text}"

Return the signs for the avatar."""


def gloss_schema(vocab: Vocabulary) -> dict:
    return {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "anyOf": [
                        {"type": "object",
                         "properties": {"sign": {"type": "string", "enum": vocab.labels}},
                         "required": ["sign"], "additionalProperties": False},
                        {"type": "object",
                         "properties": {"fingerspell": {"type": "string"}},
                         "required": ["fingerspell"], "additionalProperties": False},
                    ]
                },
            }
        },
        "required": ["items"],
        "additionalProperties": False,
    }


# ---------------------------------------------------------------- pick
def pick_system(vocab: Vocabulary, setting: str) -> str:
    return f"""You are the context step of a {vocab.language} (Nigerian Sign Language) recogniser. The vision model matched one sign against its library and returned its top candidates with similarity scores. Choose the sign the signer most likely meant.

Use the conversation so far and the signs already recognised in this utterance. The scores are a strong hint, not the truth: similar-looking signs get confused, and context usually settles it. When context gives no reason to prefer another candidate, keep the highest score.

Setting: {setting}"""


def pick_user(candidates: list[tuple[str, float]], so_far: list[str],
              history: list[tuple[str, str]], vocab: Vocabulary) -> str:
    cands = "\n".join(f"- {l} ({vocab.english(l)}): {c:.2f}" for l, c in candidates)
    return f"""Recent conversation:
{_history(history)}

Signs already recognised in this utterance: {' '.join(so_far) if so_far else '(none, this is the first sign)'}

Candidates for the current sign:
{cands}"""


def pick_schema(candidates: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {"label": {"type": "string", "enum": candidates}},
        "required": ["label"],
        "additionalProperties": False,
    }


# ---------------------------------------------------------------- compose
def compose_system(vocab: Vocabulary, setting: str, signer_name: str) -> str:
    notes = "\n".join(f"- {n}" for n in vocab.grammar_notes)
    return f"""You voice a Deaf signer. You receive the {vocab.language} (Nigerian Sign Language) signs {signer_name} just made, as glosses, and write the English sentence they mean. It is spoken aloud to a hearing person immediately.

Sign language grammar differs from English: articles, "is/are" and tense endings are usually not signed, time signs carry tense, and question words may come last.

Rules:
1. Speak as the signer, in the first person ("I need water", not "She needs water").
2. Add only the grammar English needs. Do not add facts, feelings or politeness that the signs do not carry.
3. If the signs are a question, or clearly answer the other person's last question, phrase it that way.
4. Each slot may list lower-scored alternatives. Swap in an alternative only when it clearly makes more sense in context. Report the labels you used.
5. One short, natural sentence (two at most). Plain Nigerian English is fine.

Grammar notes from our native signer:
{notes}

Setting: {setting}"""


def compose_user(slots: list[dict], history: list[tuple[str, str]], vocab: Vocabulary) -> str:
    lines = []
    for i, s in enumerate(slots, 1):
        alts = [f"{l} ({c:.2f})" for l, c in s["alternatives"]]
        alt = f"   alternatives: {', '.join(alts)}" if alts else ""
        lines.append(f"{i}. {s['label']} ({vocab.english(s['label'])}){alt}")
    return f"""Recent conversation:
{_history(history)}

Signs, in order:
{chr(10).join(lines)}"""


def compose_schema(allowed_labels: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "labels": {"type": "array", "items": {"type": "string", "enum": allowed_labels}},
            "sentence": {"type": "string"},
        },
        "required": ["labels", "sentence"],
        "additionalProperties": False,
    }
