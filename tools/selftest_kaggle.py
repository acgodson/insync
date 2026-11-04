# selftest_kaggle.py - test import_kaggle.py + match.py on fabricated asl-signs data (no Kaggle account needed).
#
# Usage:
#   python selftest_kaggle.py
#
# 1. Fabricates a tiny train.csv and 2 participants x 3 sequences x 2 signs of parquet files in the
#    competition layout (543 landmark rows per frame, NaN hands on some frames, selfie handedness,
#    a body pose with nose + shoulders, NaN pose on one frame).
# 2. Runs import_kaggle.py --offline into a temporary library, then match.py --self-test / --query on it.
# Everything happens in a temporary folder; data/kaggle and data/signs are not touched.

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from selftest import hand_template

HERE = Path(__file__).parent
rng = np.random.default_rng(1)
PARTICIPANTS = [16069, 2044]
TYPES = [("face", 468), ("left_hand", 21), ("pose", 33), ("right_hand", 21)]  # competition row order
TEMPLATE = hand_template() / 600.0  # pixels -> rough normalised units
POSE_REFS = {0: (0.5, 0.2), 11: (0.62, 0.35), 12: (0.38, 0.35)}  # nose, shoulders (normalised x, y)


# --- Fake signs: t in [0, 1] -> wrist position (x, y) of the signer's physical right hand ---

def sign_hello(t):
    return 0.6 + 0.1 * np.sin(4 * np.pi * t), 0.35          # wave beside the head


def sign_thankyou(t):
    return 0.55, 0.4 + 0.3 * t                              # from the chin forward/down


# --- Parquet builder ---

def fake_parquet(path, sign_fn):
    """One sequence. The physical right hand is stored as 'left_hand' because the dataset is a
    mirrored selfie view labelled by Holistic; 'right_hand' is always NaN (one-handed signs)."""
    n = int(rng.integers(20, 40))
    missing = set(range(3)) | set(rng.choice(np.arange(4, n - 1), size=3, replace=False).tolist())
    no_pose = int(rng.integers(4, n - 1))  # one frame where the pose model failed
    rows = []
    for f in range(n):
        cx, cy = sign_fn(f / (n - 1))
        for kind, count in TYPES:
            for k in range(count):
                if kind == "left_hand" and f not in missing:
                    x, y, z = TEMPLATE[k] + [cx, cy, 0.0] + rng.normal(0, 0.002, 3)
                elif kind == "pose" and k in POSE_REFS and f != no_pose:
                    x, y, z = *(np.array(POSE_REFS[k]) + rng.normal(0, 0.002, 2)), 0.0
                elif kind == "face" or (kind == "pose" and f != no_pose):
                    x, y, z = rng.uniform(0.3, 0.7), rng.uniform(0.1, 0.9), 0.0
                else:
                    x = y = z = np.nan
                rows.append((f, f"{f}-{kind}-{k}", kind, k, x, y, z))
    df = pd.DataFrame(rows, columns=["frame", "row_id", "type", "landmark_index", "x", "y", "z"])
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path)


def fabricate(cache):
    rows = []
    seq_id = 1000
    for sign, fn in [("hello", sign_hello), ("thankyou", sign_thankyou)]:
        for pid in PARTICIPANTS:
            for _ in range(3):
                seq_id += 1
                rel = f"train_landmark_files/{pid}/{seq_id}.parquet"
                fake_parquet(cache / rel, fn)
                rows.append((rel, pid, seq_id, sign))
    # Listed in train.csv but not in the cache: must be skipped in --offline mode.
    rows.append((f"train_landmark_files/{PARTICIPANTS[0]}/9999.parquet", PARTICIPANTS[0], 9999, "hello"))
    rows.append((f"train_landmark_files/{PARTICIPANTS[1]}/9998.parquet", PARTICIPANTS[1], 9998, "yes"))
    pd.DataFrame(rows, columns=["path", "participant_id", "sequence_id", "sign"]).to_csv(cache / "train.csv", index=False)


# --- Runner ---

def run(*args, expect_fail=False):
    cmd = [sys.executable, *map(str, args)]
    print("\n$ " + " ".join(Path(c).name if i < 2 else str(c) for i, c in enumerate(cmd)))
    result = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True)
    out = result.stdout + result.stderr
    print(out.rstrip())
    if (result.returncode != 0) != expect_fail:
        sys.exit(f"FAILED: {' '.join(map(str, args))}")
    return out


def has_kaggle_credentials():
    home = Path.home() / ".kaggle"
    return ((home / "kaggle.json").exists() or (home / "access_token").exists()
            or "KAGGLE_API_TOKEN" in os.environ or "KAGGLE_KEY" in os.environ)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        cache, out = tmp / "kaggle", tmp / "signs"
        cache.mkdir()
        fabricate(cache)
        ase = out / "ase"

        # --list from the cache
        listing = run("import_kaggle.py", "--list", "--offline", "--cache", cache)
        assert "hello" in listing and "3 participants" not in listing and "2 participants" in listing

        # Import (alias "thank you" -> thankyou, unknown "help", one missing parquet).
        args = ("import_kaggle.py", "--signs", "hello", "thank you", "help", "--offline", "--cache", cache, "--out", out)
        text = run(*args)
        assert "'thank you' -> dataset sign 'thankyou'" in text
        assert "'help': not in the dataset" in text
        assert "1 parquet file(s) not in cache" in text
        run(*args)  # rerun must overwrite, not append

        for label in ("hello", "thankyou"):
            lib = json.loads((ase / f"{label}.json").read_text())
            assert lib["label"] == label and lib["language"] == "ase"
            assert lib["features"] == "hands126+location12"
            assert len(lib["takes"]) == 6, f"{label}: expected 6 takes, got {len(lib['takes'])}"
            assert {t["signer"] for t in lib["takes"]} == {str(p) for p in PARTICIPANTS}
            for take in lib["takes"]:
                data = np.array(take["data"])
                assert data.shape == (32, 138) and np.isfinite(data).all()
                # Default --mirror: the physical right hand ('left_hand' column) lands in our right slot.
                assert np.abs(data[:, 63:126]).sum() > 0 and np.abs(data[:, :63]).sum() == 0
                # Location: right hand only (126..131 = left hand block, 132..137 = right hand block).
                assert np.abs(data[:, 126:132]).sum() == 0 and np.abs(data[:, 132:]).sum() > 0
                assert take["start_ts"] == 100  # first 3 frames have no hands: frame 3 at 30 fps

        # Round robin: 4 takes must come 2 + 2 from the two participants.
        run("import_kaggle.py", "--signs", "hello", "--max-takes", "4", "--offline", "--cache", cache, "--out", tmp / "rr")
        signers = [t["signer"] for t in json.loads((tmp / "rr" / "ase" / "hello.json").read_text())["takes"]]
        assert sorted(signers) == sorted([str(p) for p in PARTICIPANTS] * 2), signers

        # Matching
        for extra in ([], ["--dtw"], ["--no-location"], ["--k", "3"]):
            result = run("match.py", "--self-test", "--library", ase, *extra)
            assert "Per-label accuracy" in result and "Accuracy: 12/12" in result
        result = run("match.py", "--library", ase, "--query", ase / "thankyou.json", "--take", "2")
        assert "Top matches for thankyou_" in result
        assert result.split("Top matches")[1].splitlines()[1].split()[0] == "thankyou"

        # Without credentials the kaggle path must fail with the manual steps (skipped if credentials exist,
        # so the test never downloads anything).
        if not has_kaggle_credentials():
            result = run("import_kaggle.py", "--list", "--cache", tmp / "empty", expect_fail=True)
            assert "competitions/asl-signs/rules" in result and "chmod 600" in result

    print("\nKaggle self test passed.")


if __name__ == "__main__":
    main()
