from collections import Counter

from language.sessions import make_plan, run, status, write_plan


def test_plan_is_round_robin_with_emergencies_first(vocab):
    plan = make_plan(vocab, "S01", takes=3, max_tier=1)
    shots = plan["shots"]
    assert len(shots) == 30 and Counter(s["label"] for s in shots) == {s.label: 3 for s in vocab.by_tier(1)}
    assert all(s["round"] == 1 for s in shots[:10])  # every sign once before any repeats
    assert shots[0]["label"] in {"HELP", "PAIN", "FIRE"}


def test_run_is_resumable_and_status_counts(vocab, tmp_path):
    plan = make_plan(vocab, "S01", takes=3, max_tier=1)
    d = write_plan(plan, tmp_path)
    answers = iter(["", "b", "hand left frame", "q"])
    run(d, ask=lambda p: next(answers), say=lambda *a: None)
    resumed = run(d, ask=lambda p: "", say=lambda *a: None)
    st = Counter(s["status"] for s in resumed["shots"])
    assert st == {"good": 29, "bad": 1}
    rep = status(vocab, tmp_path, min_good=3, say=lambda *a: None)
    assert len(rep["ready"]) == 9  # one sign has only 2 good takes
