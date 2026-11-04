# selftest.py - end-to-end smoke test on synthetic data (no camera footage needed).
#
# Usage:
#   python selftest.py
#
# 1. Writes a few blank 504x896 JPEG frames and runs extract.py on them (checks the model loads).
# 2. Fabricates sequence.json files with a fake moving hand for a few made-up labels.
#    Every frame also carries a fake body pose (nose + shoulder midpoint) for the location features.
# 3. Runs segment.py on each into a temporary library, then match.py (cosine + DTW, query + --self-test,
#    --k, --no-location, a mixed-layout library, --query on a whole sequence.json and on a frames folder).
# Everything happens in a temporary folder; data/signs is not touched.

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).parent
WIDTH, HEIGHT = 504, 896
FPS = 30
rng = np.random.default_rng(0)


# --- Fake hand ---

def hand_template():
    """21 points of an open hand in pixels, wrist at (0, 0), fingers pointing up."""
    pts = [(0, 0)]
    for finger_x, length in [(-50, 70), (-25, 110), (0, 120), (25, 110), (50, 90)]:
        for k in range(1, 5):
            pts.append((finger_x * (0.4 + 0.15 * k), -length * k / 4 - 20))
    return np.array([[x, y, 0.0] for x, y in pts])


TEMPLATE = hand_template()


def hand_points(cx, cy, mirror=False):
    """Fake hand with its wrist at normalised (cx, cy). mirror=True gives a left hand shape."""
    pts = TEMPLATE.copy()
    if mirror:
        pts[:, 0] *= -1
    pts += rng.normal(0, 0.5, pts.shape)  # small pixel jitter
    return [[cx + x / WIDTH, cy + y / HEIGHT, z / WIDTH] for x, y, z in pts]


# --- Fake signs: t in [0, 1] -> {side: (cx, cy)} ---

def sign_wave(t, amp):
    return {"right": (0.5 + amp * 0.12 * np.sin(4 * np.pi * t), 0.55)}


def sign_wave_left(t, amp):
    # Same wave performed by a left-handed signer: mirror image of sign_wave.
    return {"left": (0.5 - amp * 0.12 * np.sin(4 * np.pi * t), 0.55)}


def sign_down(t, amp):
    return {"right": (0.55, 0.35 + amp * 0.35 * t)}


def sign_circle(t, amp):
    a = 2 * np.pi * t
    return {
        "left": (0.3 + amp * 0.08 * np.cos(a), 0.6 + amp * 0.08 * np.sin(a)),
        "right": (0.7 - amp * 0.08 * np.cos(a), 0.6 + amp * 0.08 * np.sin(a)),
    }


# --- Sequence builder ---

def empty():
    return {"visible": False, "points": [[0.0, 0.0, 0.0]] * 21}


def fake_pose():
    """Signer's body facing the camera: nose and shoulder midpoint with a little jitter."""
    nose = [0.5 + rng.normal(0, 0.002), 0.2 + rng.normal(0, 0.002), 0.0]
    return {"visible": True, "nose": nose, "shoulder_mid": [nose[0], nose[1] + 0.15, 0.0]}


def make_frame(ts, positions):
    hands = {"left": empty(), "right": empty()}
    for side, (cx, cy) in positions.items():
        hands[side] = {"visible": True, "points": hand_points(cx, cy, mirror=(side == "left"))}
    return {"ts": int(ts), "hands": hands, "pose": fake_pose()}


def build_sequence(reps, hold_between=False):
    """reps: list of sign functions. Gaps with no hands between reps, unless hold_between,
    in which case the hand stays still in frame for 0.8 s (tests the pause rule)."""
    frames = []
    ts = 1762134567890.0
    dt = 1000.0 / FPS

    def add(n, positions_fn):
        nonlocal ts
        for i in range(n):
            frames.append(make_frame(ts, positions_fn(i)))
            ts += dt

    add(10, lambda i: {})
    for fn in reps:
        duration = rng.uniform(0.8, 1.2)        # speed variation
        amp = rng.uniform(0.9, 1.1)             # size variation
        n = int(duration * FPS)
        add(n, lambda i: fn(i / (n - 1), amp))
        if hold_between:
            last = fn(1.0, amp)
            add(int(0.8 * FPS), lambda i: last)
        else:
            add(12, lambda i: {})
    return {"source": "synthetic", "width": WIDTH, "height": HEIGHT, "frames": frames}


# --- Runner ---

def run(*args):
    cmd = [sys.executable, *map(str, args)]
    print("\n$ " + " ".join(Path(c).name if i < 2 else str(c) for i, c in enumerate(cmd)))
    result = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True)
    print(result.stdout.rstrip())
    if result.returncode != 0:
        print(result.stderr)
        sys.exit(f"FAILED: {' '.join(map(str, args))}")
    return result.stdout


def main():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)

        # 1. extract.py on blank frames (no hands expected; checks the model loads and video writes).
        frames_dir = tmp / "frames"
        frames_dir.mkdir()
        for k in range(5):
            img = np.full((HEIGHT, WIDTH, 3), 40, np.uint8)
            cv2.imwrite(str(frames_dir / f"frame_{1762134567890 + k * 33}.jpg"), img)
        run("extract.py", frames_dir, "--out", tmp / "blank_sequence.json")

        # 2. Synthetic sequences -> segment.py
        library = tmp / "signs"
        plans = {
            "wave": [sign_wave] * 4 + [sign_wave_left] * 2,
            "down": [sign_down] * 6,
            "circle": [sign_circle] * 6,
        }
        for label, reps in plans.items():
            seq_path = tmp / f"{label}_sequence.json"
            seq_path.write_text(json.dumps(build_sequence(reps)))
            run("segment.py", seq_path, "--label", label, "--signer", "synthetic", "--out", library)

        # Pause rule: hand stays in frame but holds still between reps -> should still split.
        seq_path = tmp / "down_hold_sequence.json"
        seq_path.write_text(json.dumps(build_sequence([sign_down] * 2, hold_between=True)))
        out = run("segment.py", seq_path, "--label", "down", "--signer", "synthetic", "--out", library)
        assert "Found 2 sign(s)" in out, "pause rule did not split the held sequence"

        # 3. match.py
        nsl = library / "nsl"
        run("match.py", nsl, nsl / "wave.json", "--take", "4")   # a mirrored left-hand take
        run("match.py", nsl, nsl / "circle.json", "--take", "0", "--dtw")
        run("match.py", nsl, "--self-test")
        run("match.py", nsl, "--self-test", "--dtw")

        # Feature layout: 126 hand values + 12 location values, tagged in the file.
        lib = json.loads((nsl / "down.json").read_text())
        assert lib["features"] == "hands126+location12"
        data = np.array(lib["takes"][0]["data"])
        assert data.shape == (32, 138) and np.abs(data[:, 126:]).sum() > 0
        assert np.abs(data[:, 126:132]).sum() == 0  # one-handed (right) sign: left location block empty

        # k-nearest voting and hand-shape-only matching.
        out = run("match.py", nsl, "--self-test", "--k", "3")
        assert "Accuracy:" in out and "k=3" in out
        out = run("match.py", nsl, "--self-test", "--dtw", "--no-location")
        assert "no location" in out
        out = run("match.py", nsl, nsl / "wave.json", "--take", "0", "--k", "3")
        assert out.split("Top matches")[1].splitlines()[1].split()[0] == "wave"

        # A library mixing the old 126-value layout with the new one is refused, unless --no-location.
        mixed = tmp / "mixed"
        mixed.mkdir()
        (mixed / "down.json").write_text((nsl / "down.json").read_text())
        old = json.loads((nsl / "circle.json").read_text())
        del old["features"], old["location_weight"]
        for take in old["takes"]:
            take["data"] = [row[:126] for row in take["data"]]
        (mixed / "circle.json").write_text(json.dumps(old))
        cmd = [sys.executable, "match.py", str(mixed), "--self-test"]
        result = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True)
        assert result.returncode != 0 and "Mixed feature layouts" in result.stderr, result.stderr
        out = run("match.py", mixed, "--self-test", "--no-location")
        assert "Warning: mixed feature layouts" in out

        # --query on a whole sequence.json (segmented, every sign matched) and on a frames folder.
        seq_path = tmp / "query_sequence.json"
        seq_path.write_text(json.dumps(build_sequence([sign_circle, sign_down])))
        out = run("match.py", "--library", nsl, "--query", seq_path)
        assert "Found 2 sign(s)" in out and out.count("Top matches") == 2
        tops = [block.splitlines()[1].split()[0] for block in out.split("Top matches")[1:]]
        assert tops == ["circle", "down"], tops
        out = run("match.py", "--library", nsl, "--query", frames_dir)
        assert "Found 0 sign(s)" in out

    print("\nSelf test passed.")


if __name__ == "__main__":
    main()
