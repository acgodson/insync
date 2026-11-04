import pytest

from language.claude_client import ClaudeUnavailable
from language.conversation import Conversation
from language.gloss import Glosser, fallback_gloss, validate_items
from .conftest import FakeClaude, run


@pytest.mark.parametrize("text,signs", [
    ("Hello!", ["HELLO"]),
    ("Where is the restroom?", ["WHERE", "TOILET"]),
    ("What's your name?", ["WHAT", "YOU", "NAME"]),
    ("I can't breathe", ["I", "CANT-BREATHE"]),
    ("You can't go home.", ["YOU", "NO", "GO", "HOME"]),
    ("Thank you thank you", ["THANK-YOU"]),
    ("um, okay so", []),
])
def test_fallback_gloss(vocab, text, signs):
    assert fallback_gloss(text, vocab).signs == signs


def test_fallback_spends_fingerspelling_on_names_first(vocab):
    r = fallback_gloss("today we learn photosynthesis with chidi", vocab, max_fingerspell=1, names=["Chidi"])
    assert ("fingerspell", "CHIDI") in r.items and ("fingerspell", "PHOTOSYNTHESIS") not in r.items


def test_validate_items_normalises_claude_output(vocab):
    items = validate_items([{"sign": "thank-you"}, {"fingerspell": "toilet"}, {"fingerspell": "Ada!"},
                            {"fingerspell": "Lagos"}, {"fingerspell": "Abuja"}, {"sign": "NOT-A-SIGN"}],
                           vocab, max_fingerspell=2)
    assert items == [("sign", "THANK-YOU"), ("sign", "TOILET"), ("fingerspell", "ADA"), ("fingerspell", "LAGOS")]


def test_glosser_uses_claude_and_enum_schema(vocab):
    fc = FakeClaude({"gloss": {"items": [{"sign": "WHERE"}, {"sign": "TOILET"}]}})
    g = Glosser(vocab, fc, "classroom", names=["Ada"])
    r = run(g.gloss("Excuse me, where can I find the loo?", Conversation()))
    assert r.source == "claude" and r.signs == ["WHERE", "TOILET"]
    call = fc.calls[0]
    enum = call["schema"]["properties"]["items"]["items"]["anyOf"][0]["properties"]["sign"]["enum"]
    assert enum == vocab.labels
    assert "Ada" in call["system"] and "loo" in call["user"]


def test_glosser_falls_back_when_claude_fails(vocab):
    g = Glosser(vocab, FakeClaude({"gloss": ClaudeUnavailable("timeout")}), "classroom")
    r = run(g.gloss("Where is the toilet?", Conversation()))
    assert r.source == "fallback" and r.signs == ["WHERE", "TOILET"]


def test_glosser_schema_tracks_live_teaching(vocab):
    fc = FakeClaude({"gloss": {"items": []}})
    g = Glosser(vocab, fc, "classroom")
    run(g.gloss("hi", Conversation()))
    vocab.add_sign("SCIENCE")
    run(g.gloss("hi", Conversation()))
    enum = fc.calls[1]["schema"]["properties"]["items"]["items"]["anyOf"][0]["properties"]["sign"]["enum"]
    assert "SCIENCE" in enum
