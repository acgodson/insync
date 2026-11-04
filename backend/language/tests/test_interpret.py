from language.conversation import Conversation
from language.interpret import Interpreter, Slot, fallback_sentence
from .conftest import FakeClaude, run


def mk(vocab, fc):
    return Interpreter(vocab, fc, "classroom", accept_conf=0.8, accept_margin=0.15, min_conf=0.45)


def test_confident_sign_skips_claude(vocab):
    fc = FakeClaude({"pick": {"label": "NO"}})
    s = run(mk(vocab, fc).pick([("YES", 0.9), ("NO", 0.6)], [], Conversation()))
    assert s.label == "YES" and s.source == "fast" and not fc.calls


def test_below_threshold_is_unknown(vocab):
    assert run(mk(vocab, FakeClaude()).pick([("BOOK", 0.3), ("READ", 0.2)], [], Conversation())) is None


def test_single_viable_candidate(vocab):
    s = run(mk(vocab, FakeClaude()).pick([("BOOK", 0.6), ("READ", 0.2)], [], Conversation()))
    assert s.label == "BOOK" and s.source == "single"


def test_ambiguous_uses_claude_with_candidate_enum(vocab):
    fc = FakeClaude({"pick": {"label": "water"}})  # enum casing isn't guaranteed
    s = run(mk(vocab, fc).pick([("NAME", 0.7), ("WATER", 0.65), ("BOOK", 0.2)], ["I", "WANT"], Conversation()))
    assert s.label == "WATER" and s.source == "claude" and s.confidence == 0.65
    assert fc.calls[0]["schema"]["properties"]["label"]["enum"] == ["NAME", "WATER"]
    assert "I WANT" in fc.calls[0]["user"]


def test_ambiguous_falls_back_to_top1(vocab):
    s = run(mk(vocab, FakeClaude()).pick([("NAME", 0.7), ("WATER", 0.65)], [], Conversation()))
    assert s.label == "NAME" and s.source == "fallback"


def test_compose_canned_single_sign(vocab):
    fc = FakeClaude()
    c = run(mk(vocab, fc).compose([Slot("HELP", 0.9)], Conversation()))
    assert c.sentence == "Help! I need help." and c.source == "canned" and not fc.calls


def test_compose_with_claude(vocab):
    fc = FakeClaude({"compose": {"labels": ["I", "NO", "UNDERSTAND"], "sentence": "I don't understand."}})
    slots = [Slot("I", .9), Slot("NO", .88), Slot("UNDERSTAND", .66, [("KNOW", .61)])]
    c = run(mk(vocab, fc).compose(slots, Conversation()))
    assert c.sentence == "I don't understand." and c.source == "claude"
    assert set(fc.calls[0]["schema"]["properties"]["labels"]["items"]["enum"]) == {"I", "NO", "UNDERSTAND", "KNOW"}


def test_fallback_sentence(vocab):
    assert fallback_sentence(["I", "WANT", "WATER"], vocab) == "I want water."
    assert fallback_sentence(["YOU", "NAME", "WHAT"], vocab) == "You name what?"
