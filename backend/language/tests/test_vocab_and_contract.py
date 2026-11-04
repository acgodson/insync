from language import contract
from language.vocab import Vocabulary, norm_label
from .conftest import VOCAB


def test_labels_are_canonical_and_unique(vocab):
    assert all(l == norm_label(l) for l in vocab.labels)
    assert len(vocab.labels) == len(set(vocab.labels)) >= 30  # demo target: 30-50 signs


def test_tier1_is_the_first_ten_and_includes_spec_emergencies(vocab):
    t1 = {s.label for s in vocab.by_tier(1)}
    assert len(t1) == 10 and {"HELLO", "HELP", "PAIN", "FIRE"} <= t1
    em = {s.label for s in vocab.signs.values() if s.emergency}
    assert {"HELP", "FIRE", "PAIN", "CANT-BREATHE"} <= em  # the four named in the overview
    assert all(vocab.get(l).speak for l in em)


def test_canonical_is_case_and_separator_insensitive(vocab):
    assert vocab.canonical("thank you") == "THANK-YOU"
    assert vocab.canonical("Cant_Breathe") == "CANT-BREATHE"
    assert vocab.canonical("NOPE") is None


def test_no_synonym_shadows_a_primary_meaning(vocab):
    for s in vocab.signs.values():
        assert vocab.phrase_index[s.english.lower()] == s.label


def test_teach_live_persists_and_reloads(vocab, tmp_path):
    v0 = vocab.version
    vocab.add_sign("science", "science")
    assert "SCIENCE" in vocab and vocab.version == v0 + 1
    assert vocab.phrase_index["science"] == "SCIENCE"
    again = Vocabulary(VOCAB, tmp_path / "vocab.local.json")
    assert again.get("SCIENCE").taught_live


def test_contract_shapes():
    for m in [contract.caption("hi", "bob"), contract.sentence("Hi", "alice"),
              contract.sign_recognized("HELLO", 0.91234), contract.unknown_sign(),
              contract.avatar_play([("sign", "HELLO"), ("fingerspell", "ADA")]), contract.status(812.4)]:
        contract.validate(m)
    m = contract.avatar_play([("fingerspell", "ADA"), ("sign", "HELLO")])
    assert m["signs"] == ["HELLO"] and m["fingerspell"] == ["ADA"] and "sequence" not in m
    m = contract.avatar_play([("fingerspell", "ADA"), ("sign", "HELLO")], include_sequence=True)
    assert m["sequence"][0] == {"kind": "fingerspell", "value": "ADA"}
    assert contract.sign_recognized("X", 0.91234)["confidence"] == 0.912
