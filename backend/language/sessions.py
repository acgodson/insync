"""Signer recording sessions: consent, shot lists, take tracking, readiness.

Cluster B owns the recorder (glasses frames -> landmark sequence). This tool runs
the session around it: who is signing and what they agreed to, which sign to do
next, how many good takes each sign has, and which signs are demo-ready.

    python -m language.sessions consent --signer S01
    python -m language.sessions plan    --signer S01 --tier 1 --takes 5
    python -m language.sessions run     data/sessions/2026-11-05_S01 [--on-take "CMD {label} {take} {signer}"]
    python -m language.sessions status  [--min-good 3]

Layout (proposed, agree with Cluster B):
    data/consent/S01.json                       consent record (keep out of git)
    data/sessions/<date>_<signer>/plan.json     shot list + state, saved after every take
    data/sessions/<date>_<signer>/takes.jsonl   append-only log of every take
    data/signs/<LABEL>/<signer>_t<n>.*          written by the recorder
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import random
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

from .config import Settings
from .vocab import Vocabulary, norm_label

DATA = Path("data")

CONSENT_SCOPES = {
    "demo": "Use my signing live in the hackathon demo.",
    "dataset": "Keep my recorded hand landmarks to improve Almero's recognition.",
    "video": "Keep the raw video of my recordings (not just landmarks).",
    "public": "Include my anonymised landmark data in a public dataset release.",
}


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


# ------------------------------------------------------------------ consent
def consent(signer: str, data: Path, ask: Callable[[str], str] = input) -> Path:
    print(f"Consent for signer {signer}. Explain each item in sign (with an interpreter if needed).")
    print("Every item is optional. The signer can withdraw at any time and their data is deleted.\n")
    rec = {"signer": signer, "recorded_at": _now(), "scopes": {}}
    rec["display_name"] = ask("Name (optional, stored only in this file): ").strip() or None
    for key, text in CONSENT_SCOPES.items():
        rec["scopes"][key] = ask(f"  {text} [y/N] ").strip().lower().startswith("y")
    rec["interpreter_present"] = ask("Interpreter present? [y/N] ").strip().lower().startswith("y")
    rec["witness"] = ask("Recorded by (your name): ").strip()
    out = data / "consent" / f"{signer}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rec, indent=1))
    print(f"saved {out}")
    return out


def load_consent(signer: str, data: Path) -> dict | None:
    p = data / "consent" / f"{signer}.json"
    return json.loads(p.read_text()) if p.exists() else None


# ------------------------------------------------------------------ plan
def make_plan(vocab: Vocabulary, signer: str, takes: int, max_tier: int,
              labels: list[str] | None = None, seed: int = 7) -> dict:
    """Round-robin shot list: every sign once, then every sign again, and so on.
    Spacing repetitions apart captures natural variation instead of five copies of
    the same movement, and spreads fatigue evenly. Round 1 is in priority order
    (emergency first) so a short session still covers what matters most."""
    signs = [vocab.get(l) for l in labels] if labels else vocab.by_tier(max_tier)
    signs = [s for s in signs if s]
    rng = random.Random(seed)
    shots = []
    for r in range(1, takes + 1):
        order = list(signs) if r == 1 else rng.sample(signs, len(signs))
        shots += [{"label": s.label, "english": s.english, "round": r, "status": "todo"} for s in order]
    return {"signer": signer, "created": _now(), "takes_per_sign": takes, "shots": shots, "cursor": 0}


def write_plan(plan: dict, data: Path) -> Path:
    d = data / "sessions" / f"{dt.date.today().isoformat()}_{plan['signer']}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "plan.json").write_text(json.dumps(plan, indent=1))
    return d


# ------------------------------------------------------------------ run
HELP = "[Enter] good  b bad  r redo  s skip sign  n note  p pause  q save & quit"


def run(session_dir: Path, on_take: str | None = None, ask: Callable[[str], str] = input,
        say: Callable[[str], None] = print, break_every: int = 40) -> dict:
    plan_p = session_dir / "plan.json"
    plan = json.loads(plan_p.read_text())
    log = open(session_dir / "takes.jsonl", "a")
    shots = plan["shots"]
    take_no: dict[str, int] = {}
    for s in shots:
        if s["status"] in ("good", "bad"):
            take_no[s["label"]] = take_no.get(s["label"], 0) + 1
    since_break, t_start = 0, time.time()

    def save():
        tmp = plan_p.with_suffix(".tmp")
        tmp.write_text(json.dumps(plan, indent=1))
        tmp.replace(plan_p)  # crash-safe: never a half-written plan

    while plan["cursor"] < len(shots):
        shot = shots[plan["cursor"]]
        if shot["status"] != "todo":
            plan["cursor"] += 1
            continue
        n = take_no.get(shot["label"], 0) + 1
        done = sum(1 for s in shots if s["status"] != "todo")
        mins = (time.time() - t_start) / 60
        say(f"\n[{done + 1}/{len(shots)}  round {shot['round']}/{plan['takes_per_sign']}  {mins:.0f} min]"
            f"   {shot['label']}  ({shot['english']})   take {n}")
        if on_take:
            cmd = on_take.format(label=shot["label"], take=n, signer=plan["signer"])
            say(f"  $ {cmd}")
            rc = subprocess.call(shlex.split(cmd))
            if rc != 0:
                say(f"  recorder exited {rc}; marking for redo")
                continue
        a = ask(f"  {HELP}\n  > ").strip().lower()
        if a == "q":
            break
        if a == "p":
            say("  paused; press Enter to continue")
            ask("")
            since_break = 0
            continue
        if a == "r":
            continue
        if a == "s":
            for s in shots[plan["cursor"]:]:
                if s["label"] == shot["label"] and s["status"] == "todo":
                    s["status"] = "skipped"
            save()
            continue
        note = None
        if a == "n":
            note = ask("  note: ").strip()
            a = ask("  good? [Y/n] ").strip().lower()
            a = "b" if a.startswith("n") else ""
        status = "bad" if a == "b" else "good"
        if status == "bad" and note is None:
            note = ask("  why (optional): ").strip() or None
        shot.update(status=status, take=n, at=_now(), **({"note": note} if note else {}))
        take_no[shot["label"]] = n
        log.write(json.dumps({"signer": plan["signer"], **shot}) + "\n")
        log.flush()
        plan["cursor"] += 1
        save()
        since_break += 1
        if since_break >= break_every:
            say(f"  {since_break} takes since the last break. Offer the signer a rest (p).")
            since_break = 0
    save()
    log.close()
    good = sum(1 for s in shots if s["status"] == "good")
    say(f"\nsession saved: {good} good takes, {sum(1 for s in shots if s['status'] == 'todo')} still to do")
    return plan


# ------------------------------------------------------------------ status
def status(vocab: Vocabulary, data: Path, min_good: int = 3, say: Callable[[str], None] = print) -> dict:
    good: dict[str, dict[str, int]] = {}
    for plan_p in sorted((data / "sessions").glob("*/plan.json")):
        plan = json.loads(plan_p.read_text())
        for s in plan["shots"]:
            if s["status"] == "good":
                good.setdefault(norm_label(s["label"]), {}).setdefault(plan["signer"], 0)
                good[norm_label(s["label"])][plan["signer"]] += 1
    files = {}
    if (data / "signs").exists():  # what the recorder actually wrote
        for d in (data / "signs").iterdir():
            if d.is_dir():
                files[norm_label(d.name)] = sum(1 for f in d.iterdir() if f.is_file())
    rows = []
    for s in vocab.by_tier(9):
        g = sum(good.get(s.label, {}).values())
        rows.append({"label": s.label, "tier": s.tier, "emergency": s.emergency, "good": g,
                     "files": files.get(s.label), "ready": g >= min_good})
    ready = [r for r in rows if r["ready"]]
    say(f"{'LABEL':<14}{'tier':>5}{'good':>6}{'files':>7}  status")
    for r in rows:
        mark = "ready" if r["ready"] else ("partial" if r["good"] else "missing")
        warn = "  <- recorder count differs" if r["files"] is not None and r["files"] < r["good"] else ""
        em = " (emergency)" if r["emergency"] else ""
        say(f"{r['label']:<14}{r['tier']:>5}{r['good']:>6}{str(r['files'] if r['files'] is not None else '-'):>7}"
            f"  {mark}{em}{warn}")
    t1 = [r for r in rows if r["tier"] == 1]
    say(f"\n{len(ready)}/{len(rows)} signs demo-ready (>= {min_good} good takes); "
        f"milestone 1 (tier 1): {sum(r['ready'] for r in t1)}/{len(t1)}")
    return {"rows": rows, "ready": [r["label"] for r in ready]}


# ------------------------------------------------------------------ CLI
def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m language.sessions")
    ap.add_argument("--data", default=str(DATA))
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("consent"); c.add_argument("--signer", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--signer", required=True)
    p.add_argument("--takes", type=int, default=5)
    p.add_argument("--tier", type=int, default=2, help="1 = first 10 signs, 2 = demo set, 3 = all")
    p.add_argument("--labels", help="comma-separated, overrides --tier")
    r = sub.add_parser("run"); r.add_argument("session_dir")
    r.add_argument("--on-take", help="recorder command, e.g. 'python -m recognition.record --label {label} --take {take} --signer {signer}'")
    st = sub.add_parser("status"); st.add_argument("--min-good", type=int, default=3)
    a = ap.parse_args(argv)
    data = Path(a.data)
    s = Settings()
    vocab = Vocabulary(s.vocab_path, s.vocab_local_path)

    if a.cmd == "consent":
        consent(a.signer, data)
    elif a.cmd == "plan":
        if not load_consent(a.signer, data):
            sys.exit(f"No consent record for {a.signer}. Run: python -m language.sessions consent --signer {a.signer}")
        labels = [norm_label(x) for x in a.labels.split(",")] if a.labels else None
        plan = make_plan(vocab, a.signer, a.takes, a.tier, labels)
        d = write_plan(plan, data)
        n = len(plan["shots"])
        print(f"{d}/plan.json: {n // a.takes} signs x {a.takes} takes = {n} shots "
              f"(~{n * 12 / 60:.0f} min at 12 s per take, plus breaks)")
    elif a.cmd == "run":
        run(Path(a.session_dir), a.on_take)
    elif a.cmd == "status":
        status(vocab, data, a.min_good)


if __name__ == "__main__":
    main()
