# segment.py - split a landmark sequence into individual signs and add them to the library.
#
# Usage:
#   python segment.py <sequence.json> --label <label> [--language nsl] [--signer <id>] [--out data/signs]

import argparse
import json
import sys
from pathlib import Path

import numpy as np

NUM_POINTS = 21
NUM_FRAMES = 32                    # every take is resampled to this many frames
SIDES = ("left", "right")          # slot order in the 126-value frame vector: left 0..62, right 63..125
HAND_VALUES = 2 * NUM_POINTS * 3   # 126 hand-shape values per frame, followed by the location block
LOCATION_VALUES = 2 * 2 * 3        # 12: per hand (left, right) wrist - shoulder midpoint, wrist - nose (x, y, z)
FEATURES = "hands126+location12"   # layout tag stored in every library file (files without it are "hands126")

# TODO: tune on real glasses footage.
MOTION_THRESHOLD = 0.004           # mean landmark displacement per frame (normalised image units) below which the hand counts as "still"
PAUSE_SECONDS = 0.5                # stillness longer than this ends a sign
MIN_SIGN_SECONDS = 0.2             # shorter segments are discarded as noise

# Reference scale: after converting landmarks to pixels, coordinates are divided by this
# constant, so 1.0 unit ~ one hand length (wrist to middle fingertip) for a hand held at
# a normal signing distance in a 504x896 glasses frame. A fixed constant (rather than
# per-take hand size) keeps the absolute size/distance of movements comparable between takes.
# TODO: measure on real footage and adjust.
REFERENCE_SCALE_PX = 150.0

# Location block weight (multiplies the 12 location values). Measured on data/signs/ase
# (391 Kaggle takes, 32 frames each) with weight 1.0:
#   per-value RMS:          hand block 0.489, location block 0.590
#   per-frame block norm:   hand block 5.49,  location block 2.04 -> location = 35% of the total norm
# 0.8 puts the location values just below the hand values (RMS 0.472 vs 0.489) and the location
# block at 29% of the total vector norm (per-frame norm 1.63 vs 5.49).
# TODO: tune (then re-import / re-segment the library; the weight is baked into the takes).
LOCATION_WEIGHT = 0.8


# --- Loading ---

def load_sequence(path):
    return sequence_arrays(json.loads(Path(path).read_text()))


def sequence_arrays(seq):
    """sequence.json dict -> (seq, ts, points, visible, pose, pose_visible)."""
    frames = seq["frames"]
    ts = np.array([f["ts"] for f in frames], dtype=float)
    # points: (frames, 2 hands, 21, 3); visible: (frames, 2 hands)
    points = np.array([[f["hands"][s]["points"] for s in SIDES] for f in frames], dtype=float)
    visible = np.array([[f["hands"][s]["visible"] for s in SIDES] for f in frames], dtype=bool)
    # pose: (frames, 2 refs, 3) = shoulder midpoint, nose; frames without "pose" (old files) count as not visible.
    pose = np.zeros((len(frames), 2, 3))
    pose_visible = np.zeros(len(frames), dtype=bool)
    for i, f in enumerate(frames):
        p = f.get("pose")
        if p and p["visible"]:
            pose[i] = [p["shoulder_mid"], p["nose"]]
            pose_visible[i] = True
    return seq, ts, points.reshape(len(frames), 2, NUM_POINTS, 3), visible, pose, pose_visible


# --- Segmentation ---

def frame_motion(points, visible):
    """Mean x/y displacement of landmarks between each frame and the previous one.
    Returns inf when no hand is visible in both frames (e.g. a hand just appeared)."""
    motion = np.full(len(points), np.inf)
    for i in range(1, len(points)):
        both = visible[i] & visible[i - 1]
        if not both.any():
            continue
        disp = np.linalg.norm(points[i, both, :, :2] - points[i - 1, both, :, :2], axis=-1)
        motion[i] = disp.mean()
    return motion


def find_signs(ts, points, visible):
    """Returns a list of (start_index, end_index) inclusive.

    A sign starts when a hand becomes visible (or, if hands stayed in frame after a
    pause, when they start moving again). It ends when all hands leave the frame, or
    when the hands stay still for more than PAUSE_SECONDS."""
    any_visible = visible.any(axis=1)
    moving = frame_motion(points, visible) > MOTION_THRESHOLD
    signs = []
    start = None
    still_since = None

    for i in range(len(ts)):
        if start is None:
            just_appeared = any_visible[i] and (i == 0 or not any_visible[i - 1])
            if any_visible[i] and (just_appeared or moving[i]):
                start, still_since = i, None
            continue

        if not any_visible[i]:
            signs.append((start, i - 1))
            start = None
        elif moving[i]:
            still_since = None
        else:
            still_since = i if still_since is None else still_since
            if ts[i] - ts[still_since] > PAUSE_SECONDS * 1000:
                signs.append((start, still_since))
                start = None

    if start is not None:
        signs.append((start, len(ts) - 1))

    return [(a, b) for a, b in signs if (ts[b] - ts[a]) >= MIN_SIGN_SECONDS * 1000]


# --- Normalisation ---

def normalise(points, visible, width, height):
    """Translate to the wrist origin, scale by REFERENCE_SCALE_PX, and mirror left-only signs."""
    pts = points.copy()
    # Normalised image coords -> pixels (z uses the same scale as x, per MediaPipe docs).
    pts[..., 0] *= width
    pts[..., 1] *= height
    pts[..., 2] *= width

    # Origin: midpoint between the wrists at the first frame (or the single visible wrist).
    first = np.argmax(visible.any(axis=1))
    wrists = pts[first, visible[first], 0, :]
    origin = wrists.mean(axis=0)
    origin[2] = 0.0  # z is already relative to the wrist in MediaPipe
    pts = (pts - origin) / REFERENCE_SCALE_PX

    vis = visible.copy()
    left_only = vis[:, 0].any() and not vis[:, 1].any()
    if left_only:
        # Mirror x and move into the right slot so left-handed signers match right-handed ones.
        pts[..., 0] *= -1
        pts = pts[:, ::-1]
        vis = vis[:, ::-1]

    pts[~vis] = 0.0
    return pts, vis, left_only


def resample(ts, pts, vis, n=NUM_FRAMES):
    """Linear interpolation over time to n frames: pts (frames, 2, K, 3) -> array (n, 2 * K * 3),
    e.g. (n, 126) for hands (K = 21). Each hand is interpolated only between frames where it
    is visible; target times whose nearest source frame has the hand missing are left as zeros."""
    k_points = pts.shape[2]
    targets = np.linspace(ts[0], ts[-1], n)
    nearest = np.abs(ts[None, :] - targets[:, None]).argmin(axis=1)
    out = np.zeros((n, 2, k_points, 3))
    for h in range(2):
        idx = np.where(vis[:, h])[0]
        if len(idx) == 0:
            continue
        flat = pts[idx, h].reshape(len(idx), -1)
        interp = np.stack([np.interp(targets, ts[idx], flat[:, k]) for k in range(flat.shape[1])], axis=1)
        out[:, h] = interp.reshape(n, k_points, 3)
        out[~vis[nearest, h], h] = 0.0
    return out.reshape(n, -1)


# --- Location (where the hands are relative to the body) ---

def location(points, visible, pose, pose_visible, width, height):
    """Wrist position relative to the shoulder midpoint and to the nose, per hand and frame
    -> loc (frames, 2 hands, 2 refs, 3), loc_visible (frames, 2 hands).

    Same pixel conversion and REFERENCE_SCALE_PX as normalise(), so 1.0 ~ one hand length.
    z is left at 0: the hand wrist z is MediaPipe's per-hand depth origin (always ~0) and pose z
    is on a different scale, so a difference would be meaningless. The slot is kept so depth can
    be added later without changing the layout. Zero when the hand or the pose is not visible."""
    scale = np.array([width, height, 0.0]) / REFERENCE_SCALE_PX
    wrists = points[:, :, 0, :]                                      # (frames, 2, 3)
    loc = (wrists[:, :, None, :] - pose[:, None, :, :]) * scale      # (frames, 2, 2, 3)
    loc_visible = visible & pose_visible[:, None]
    loc[~loc_visible] = 0.0
    return loc, loc_visible


def take_features(ts, points, visible, pose, pose_visible, width, height):
    """One sign segment -> (data (NUM_FRAMES, 138), hand visibility after normalise, mirrored).
    Shared by segment.py, match.py and import_kaggle.py so all libraries have the same layout:
    126 hand values (normalise + resample) then 12 location values x LOCATION_WEIGHT."""
    pts, vis, mirrored = normalise(points, visible, width, height)
    loc, loc_vis = location(points, visible, pose, pose_visible, width, height)
    if mirrored:
        # Same mirroring as normalise(): flip x and move the left hand into the right slot.
        loc[..., 0] *= -1
        loc, loc_vis = loc[:, ::-1], loc_vis[:, ::-1]
    data = np.hstack([resample(ts, pts, vis), LOCATION_WEIGHT * resample(ts, loc, loc_vis)])
    return data, vis, mirrored


# --- Library file ---

def library_header(label, language, signer):
    """New label file. "features" / "location_weight" let match.py refuse mixed layouts."""
    return {"label": label, "language": language, "signer": signer,
            "features": FEATURES, "location_weight": LOCATION_WEIGHT, "takes": []}


def append_takes(library_file, label, language, signer, new_takes):
    if library_file.exists():
        lib = json.loads(library_file.read_text())
        layout = (lib.get("features", "hands126"), lib.get("location_weight"))
        if layout != (FEATURES, LOCATION_WEIGHT):
            sys.exit(f"{library_file} has layout {layout}, current is {(FEATURES, LOCATION_WEIGHT)}; "
                     "re-record it into a new library folder instead of mixing layouts.")
    else:
        lib = library_header(label, language, signer)
    start_n = len(lib["takes"])
    for i, take in enumerate(new_takes):
        take["id"] = f"{label}_{signer}_{start_n + i + 1:03d}"
        lib["takes"].append(take)
    library_file.parent.mkdir(parents=True, exist_ok=True)
    library_file.write_text(json.dumps(lib))
    return len(lib["takes"])


# --- Main ---

def main():
    parser = argparse.ArgumentParser(description="Split a sequence.json into signs and append them to the library.")
    parser.add_argument("sequence")
    parser.add_argument("--label", required=True)
    parser.add_argument("--language", default="nsl")
    parser.add_argument("--signer", default="unknown")
    parser.add_argument("--out", default="data/signs")
    args = parser.parse_args()

    seq, ts, points, visible, pose, pose_visible = load_sequence(args.sequence)
    signs = find_signs(ts, points, visible)
    print(f"Found {len(signs)} sign(s) in {args.sequence}")

    takes = []
    for k, (a, b) in enumerate(signs, 1):
        s = slice(a, b + 1)
        data, _, mirrored = take_features(ts[s], points[s], visible[s], pose[s], pose_visible[s],
                                          seq["width"], seq["height"])
        takes.append({
            "id": None,
            "signer": args.signer,
            "source": seq.get("source", str(args.sequence)),
            "start_ts": int(ts[a]),
            "end_ts": int(ts[b]),
            "data": np.round(data, 5).tolist(),
        })
        note = " (left-hand only, mirrored)" if mirrored else ""
        print(f"  sign {k}: {(ts[b] - ts[a]) / 1000:.2f}s, frames {a}-{b}{note}")

    if not takes:
        return
    library_file = Path(args.out) / args.language / f"{args.label}.json"
    total = append_takes(library_file, args.label, args.language, args.signer, takes)
    print(f"Appended {len(takes)} take(s) to {library_file} (now {total} takes)")


if __name__ == "__main__":
    main()
