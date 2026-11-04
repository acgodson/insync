# import_kaggle.py - build a benchmark library from the Kaggle "asl-signs" competition
# (Google - Isolated Sign Language Recognition) in our data/signs/<language>/<label>.json format.
#
# Usage:
#   python import_kaggle.py --list                                   # download train.csv only, print signs + counts
#   python import_kaggle.py [--signs hello "thank you" ...] [--max-takes 50] [--language ase]
#                           [--mirror | --no-mirror] [--offline] [--cache data/kaggle] [--out data/signs]
#
# Only train.csv and the individual parquet files for the chosen sequences are downloaded
# (the full dataset is ~40 GB and is never fetched). Everything is cached under data/kaggle/
# in the same layout as the competition: data/kaggle/train.csv and
# data/kaggle/train_landmark_files/<participant_id>/<sequence_id>.parquet.
# --offline uses the cache only and never calls the kaggle CLI.

import argparse
import difflib
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from segment import NUM_POINTS, library_header, take_features

HERE = Path(__file__).parent
COMPETITION = "asl-signs"
DEFAULT_SIGNS = ["hello", "thank you", "yes", "no", "please", "help", "water", "more", "mother", "father"]

# Assumption: the competition does not publish a frame rate; the clips are phone/webcam
# video, so frame index -> timestamp uses 30 fps. Only relative timing matters (resample()
# spreads each take over 32 frames), so a wrong guess just scales the start_ts/end_ts values.
# TODO: confirm if the frame rate is ever published.
ASSUMED_FPS = 30.0

# The landmarks are normalised image coordinates, but the source video size is not given.
# normalise() converts to pixels and divides by REFERENCE_SCALE_PX, which was chosen for a
# 504x896 glasses frame, so we pretend the dataset frames have that size too (portrait phone).
# TODO: tune if dataset hands come out much larger/smaller than glasses hands.
ASSUMED_WIDTH, ASSUMED_HEIGHT = 504, 896

# Requested name -> dataset name, for words the dataset spells differently.
# Matching also ignores case and spaces ("thank you" -> "thankyou").
ALIASES = {"mother": "mom", "father": "dad"}

MANUAL_STEPS = f"""
To get the Kaggle files:
  1. Sign in at https://www.kaggle.com and accept the competition rules at
     https://www.kaggle.com/competitions/{COMPETITION}/rules  (otherwise downloads return 403).
  2. Create an API token at https://www.kaggle.com/settings/api and save it as
     ~/.kaggle/kaggle.json, then:  chmod 600 ~/.kaggle/kaggle.json
     (newer kaggle CLIs also accept ~/.kaggle/access_token, KAGGLE_API_TOKEN, or `kaggle auth login`)
  3. Or download the files by hand from https://www.kaggle.com/competitions/{COMPETITION}/data
     into the cache layout and rerun with --offline:
       {{cache}}/train.csv
       {{cache}}/train_landmark_files/<participant_id>/<sequence_id>.parquet
"""


# --- Kaggle downloads ---

def kaggle_command():
    local = Path(sys.executable).parent / "kaggle"
    return str(local) if local.exists() else "kaggle"


def kaggle_download(remote_path, dest, cache):
    """Download one competition file to dest (unzipping if needed). Exits with manual steps on failure."""
    staging = cache / "_download"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    cmd = [kaggle_command(), "competitions", "download", "-c", COMPETITION, "-f", remote_path, "-p", str(staging), "-q"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        failed = result.returncode != 0
        output = (result.stdout + result.stderr).strip()
    except FileNotFoundError as e:
        failed, output = True, str(e)

    files = [p for p in staging.rglob("*") if p.is_file()]
    if failed or not files:
        print(f"$ {' '.join(cmd)}\n{output}\n\nThe kaggle command failed.")
        sys.exit(MANUAL_STEPS.format(cache=cache))

    dest.parent.mkdir(parents=True, exist_ok=True)
    src = files[0]
    if src.suffix == ".zip":
        with zipfile.ZipFile(src) as z:
            dest.write_bytes(z.read(z.namelist()[0]))
    else:
        shutil.move(str(src), dest)
    shutil.rmtree(staging, ignore_errors=True)


def cached_file(remote_path, cache, offline):
    """Path of the cached copy, downloading it first if needed. None if offline and missing."""
    dest = cache / remote_path
    if dest.exists():
        return dest
    if offline:
        return None
    kaggle_download(remote_path, dest, cache)
    return dest


def load_train_csv(cache, offline):
    path = cached_file("train.csv", cache, offline)
    if path is None:
        sys.exit(f"{cache / 'train.csv'} not found (--offline).\n" + MANUAL_STEPS.format(cache=cache))
    return pd.read_csv(path)


# --- Sign selection ---

def resolve_sign(name, dataset_signs):
    """Requested sign name -> dataset sign name, or None."""
    key = name.lower().replace(" ", "")
    by_key = {s.lower().replace(" ", ""): s for s in dataset_signs}
    if key in by_key:
        return by_key[key]
    alias = ALIASES.get(name.lower())
    return alias if alias in dataset_signs else None


def pick_sequences(rows, max_takes):
    """Round-robin over participants (sorted by id) so no single signer dominates."""
    queues = [list(g.sort_values("sequence_id").itertuples()) for _, g in rows.groupby("participant_id")]
    picked = []
    while len(picked) < max_takes and any(queues):
        for q in queues:
            if q and len(picked) < max_takes:
                picked.append(q.pop(0))
    return picked


# --- Parquet -> our hand + pose layout ---

def parquet_to_hands(path, mirror):
    """Returns ts (frames,), points (frames, 2, 21, 3), visible (frames, 2) in our slot order (left, right),
    pose (frames, 2, 3) = shoulder midpoint (pose 11 + 12) and nose (pose 0), pose_visible (frames,).

    Handedness: the dataset is a selfie (mirrored webcam) view labelled by MediaPipe Holistic,
    whose hand labels follow the pose model. In a mirrored image the signer's physical right
    hand looks like a left hand of a person facing the camera, so Holistic files it under
    'left_hand'. With mirror=True (default) the columns are swapped so the signer's physical
    right hand goes to our right slot. x is NOT flipped: in a mirrored selfie the signer's
    right hand is already on the right side of the image, as it is in the glasses'
    first-person view. With mirror=False the columns are used as labelled. The pose references
    (nose, shoulder midpoint) have no side, so mirroring does not affect them."""
    df = pd.read_parquet(path, columns=["frame", "type", "landmark_index", "x", "y", "z"])
    pose_df = df[(df["type"] == "pose") & df["landmark_index"].isin([0, 11, 12])]
    df = df[df["type"].isin(["left_hand", "right_hand"])]
    frames = np.sort(df["frame"].unique())
    slot_of = {"right_hand": 0, "left_hand": 1} if mirror else {"left_hand": 0, "right_hand": 1}

    points = np.full((len(frames), 2, NUM_POINTS, 3), np.nan)
    f_idx = np.searchsorted(frames, df["frame"].to_numpy())
    s_idx = df["type"].map(slot_of).to_numpy()
    l_idx = df["landmark_index"].to_numpy()
    points[f_idx, s_idx, l_idx] = df[["x", "y", "z"]].to_numpy(dtype=float)

    visible = ~np.isnan(points[..., :2]).any(axis=(2, 3))
    points[~visible] = 0.0
    points = np.nan_to_num(points)  # stray NaN z values on a visible hand

    raw = np.full((len(frames), 33, 3), np.nan)
    pose_df = pose_df[pose_df["frame"].isin(frames)]
    raw[np.searchsorted(frames, pose_df["frame"].to_numpy()), pose_df["landmark_index"].to_numpy()] = \
        pose_df[["x", "y", "z"]].to_numpy(dtype=float)
    pose = np.stack([(raw[:, 11] + raw[:, 12]) / 2, raw[:, 0]], axis=1)
    pose_visible = ~np.isnan(pose[..., :2]).any(axis=(1, 2))
    pose = np.nan_to_num(pose)

    ts = frames * 1000.0 / ASSUMED_FPS
    return ts, points, visible, pose, pose_visible


def make_take(path, row, label, mirror):
    """One parquet -> (take dict, visible slots), or None if hands are never visible."""
    ts, points, visible, pose, pose_visible = parquet_to_hands(path, mirror)
    any_vis = np.where(visible.any(axis=1))[0]
    if len(any_vis) < 2:
        return None
    # Trim leading/trailing frames without hands, like a segment.py segment would.
    a, b = any_vis[0], any_vis[-1]
    s = slice(a, b + 1)
    data, vis, _ = take_features(ts[s], points[s], visible[s], pose[s], pose_visible[s],
                                 ASSUMED_WIDTH, ASSUMED_HEIGHT)
    signer = str(row.participant_id)
    return {
        "id": f"{label}_{signer}_{row.sequence_id}",
        "signer": signer,
        "source": f"kaggle:{COMPETITION}/{row.path}",
        "start_ts": int(ts[a]),
        "end_ts": int(ts[b]),
        "data": np.round(data, 5).tolist(),
    }, vis


# --- Commands ---

def list_signs(train):
    counts = train["sign"].value_counts().sort_index()
    for sign, n in counts.items():
        print(f"  {sign:20s} {n}")
    print(f"{len(counts)} signs, {len(train)} sequences, {train['participant_id'].nunique()} participants")


def import_signs(train, args, cache):
    dataset_signs = set(train["sign"])
    summary = []
    for name in args.signs:
        label = resolve_sign(name, dataset_signs)
        if label is None:
            close = difflib.get_close_matches(name.lower(), dataset_signs, n=3)
            print(f"'{name}': not in the dataset (closest: {', '.join(close) or 'none'}); skipped")
            summary.append((name, "-", 0, 0, ""))
            continue
        if label != name:
            print(f"'{name}' -> dataset sign '{label}'")

        picked = pick_sequences(train[train["sign"] == label], args.max_takes)
        takes, missing, empty = [], 0, 0
        slot_frames = np.zeros(2)
        for i, row in enumerate(picked, 1):
            path = cached_file(row.path, cache, args.offline)
            if path is None:
                missing += 1
                continue
            result = make_take(path, row, label, args.mirror)
            if result is None:
                empty += 1
                continue
            take, vis = result
            takes.append(take)
            slot_frames += vis.sum(axis=0)
            print(f"\r  {label}: {i}/{len(picked)}", end="", flush=True)
        print()
        if missing:
            print(f"  {label}: {missing} parquet file(s) not in cache (--offline); skipped")
        if empty:
            print(f"  {label}: {empty} sequence(s) with no hands; skipped")

        if takes:
            lib = library_header(label, args.language, f"kaggle-{COMPETITION}")
            lib["takes"] = takes
            out_file = Path(args.out) / args.language / f"{label}.json"
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_text(json.dumps(lib))  # overwrites on rerun
        participants = len({t["signer"] for t in takes})
        right_share = f"{100 * slot_frames[1] / slot_frames.sum():.0f}%" if slot_frames.sum() else ""
        summary.append((name, label, len(takes), participants, right_share))

    print(f"\n{'sign':12s} {'dataset':12s} {'takes':>6s} {'participants':>13s} {'right slot':>11s}")
    for name, label, n, p, share in summary:
        print(f"{name:12s} {label:12s} {n:6d} {p:13d} {share:>11s}")
    print("(right slot = share of visible hand-frames in our right slot after normalise; "
          "left-only takes are always mirrored into it)")
    print(f"Wrote {Path(args.out) / args.language}")


# --- Main ---

def main():
    parser = argparse.ArgumentParser(description="Import Kaggle asl-signs sequences into the sign library.")
    parser.add_argument("--list", action="store_true", help="download train.csv only and print the sign labels")
    parser.add_argument("--signs", nargs="+", default=DEFAULT_SIGNS)
    parser.add_argument("--max-takes", type=int, default=50)  # TODO: raise for a bigger benchmark
    parser.add_argument("--language", default="ase")
    parser.add_argument("--mirror", dest="mirror", action="store_true", default=True,
                        help="(default) dataset is a mirrored selfie view: swap Holistic's left/right hand columns")
    parser.add_argument("--no-mirror", dest="mirror", action="store_false",
                        help="use the left_hand/right_hand columns as labelled")
    parser.add_argument("--offline", action="store_true", help="use the cache only, never call kaggle")
    parser.add_argument("--cache", default=str(HERE / "data" / "kaggle"))
    parser.add_argument("--out", default=str(HERE / "data" / "signs"))
    args = parser.parse_args()

    cache = Path(args.cache)
    train = load_train_csv(cache, args.offline)
    if args.list:
        list_signs(train)
    else:
        import_signs(train, args, cache)


if __name__ == "__main__":
    main()
