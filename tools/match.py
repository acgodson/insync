# match.py - compare a sign take against the library and report the closest labels.
#
# Usage:
#   python match.py <library_dir> <query_take.json>                # file with a single take {"data": ...}
#   python match.py <library_dir> <label.json> --take N            # take N (0-based) from a library file
#   python match.py <library_dir> --self-test                      # leave-one-out over the whole library
#   python match.py --library data/signs/ase --self-test           # same, library given as an option
#   python match.py --library data/signs/nsl --query <path> [--take N]
#       <path> = a take json, a label.json (+ --take), an extract.py sequence.json, or a folder of
#       glasses JPEG frames; sequences and folders are segmented and every detected sign is matched.
#   add --dtw to use dynamic time warping instead of cosine similarity
#   add --k N to vote over the N nearest takes (default 1 = best take per label)
#   add --no-location to drop the 12 location columns (hand shape only, like the old 126-value layout)

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

from segment import HAND_VALUES, find_signs, sequence_arrays, take_features

# TODO: tune. Softmax temperatures that turn per-label scores into confidences.
# Cosine similarities of real takes sit close together (often 0.8-1.0), so a small
# temperature is needed to spread them; DTW scores are rescaled first (see below).
COSINE_TEMPERATURE = 0.05
DTW_TEMPERATURE = 0.1


# --- Loading ---

def load_library(library_dir):
    """Returns (takes, layouts): takes are dicts with label, id, data (32x138 array, or 32x126 for
    old files); layouts maps (features, location_weight) -> label files using it."""
    takes, layouts = [], {}
    for path in sorted(Path(library_dir).glob("*.json")):
        lib = json.loads(path.read_text())
        layout = (lib.get("features", "hands126"), lib.get("location_weight"))
        layouts.setdefault(layout, []).append(path.name)
        for take in lib["takes"]:
            takes.append({"label": lib["label"], "id": take["id"], "data": np.array(take["data"], dtype=float)})
    return takes, layouts


def check_layouts(layouts, no_location):
    """Refuse a library that mixes feature layouts (unless --no-location makes them comparable)."""
    if len(layouts) <= 1:
        return
    lines = "\n".join(f"  {f} (location_weight {w}): {', '.join(names)}" for (f, w), names in layouts.items())
    if no_location:
        print(f"Warning: mixed feature layouts, comparing hand columns only (--no-location):\n{lines}")
    else:
        sys.exit(f"Mixed feature layouts in the library:\n{lines}\n"
                 "Re-import / re-segment them, or compare hand shape only with --no-location.")


def load_queries(path, take_index):
    """Returns a list of (name, id_to_exclude, data 32x126) for every sign in the query."""
    path = Path(path)
    if path.is_dir():
        return signs_in_sequence(extract_folder(path), path.name)
    doc = json.loads(path.read_text())
    if "frames" in doc:
        return signs_in_sequence(doc, path.name)
    if "takes" in doc:
        take = doc["takes"][take_index]
        return [(take.get("id") or f"{path.name}[{take_index}]", take.get("id"), np.array(take["data"], dtype=float))]
    return [(doc.get("id") or path.name, doc.get("id"), np.array(doc["data"], dtype=float))]


def extract_folder(folder):
    """Run the extract.py Holistic landmarker over a frames folder -> sequence dict (no preview)."""
    import cv2  # imported here so plain matching doesn't pay for loading MediaPipe
    from extract import close_landmarker, detect, list_frames, make_landmarker

    landmarker = make_landmarker()
    frames, width, height, last_ts = [], None, None, -1
    for ts, frame_path in list_frames(folder):
        image = cv2.imread(str(frame_path))
        if image is None or ts <= last_ts:
            continue
        height, width = image.shape[:2]
        last_ts = ts
        frames.append({"ts": ts, **detect(landmarker, image, ts)})
    close_landmarker(landmarker)
    print(f"Extracted {len(frames)} frames from {folder}")
    return {"source": str(folder), "width": width or 504, "height": height or 896, "frames": frames}


def signs_in_sequence(seq, name):
    """Segment a sequence dict like segment.py does and return one query per detected sign."""
    if not seq["frames"]:
        print(f"Found 0 sign(s) in {name}")
        return []
    seq, ts, points, visible, pose, pose_visible = sequence_arrays(seq)
    signs = find_signs(ts, points, visible)
    print(f"Found {len(signs)} sign(s) in {name}")
    queries = []
    for k, (a, b) in enumerate(signs, 1):
        s = slice(a, b + 1)
        data, _, _ = take_features(ts[s], points[s], visible[s], pose[s], pose_visible[s],
                                   seq["width"], seq["height"])
        queries.append((f"sign {k} ({(ts[b] - ts[a]) / 1000:.2f}s, frames {a}-{b})", None, data))
    return queries


# --- Similarity (one query against every library take at once) ---

def cosine_scores(query, takes):
    """query (32, D), takes (N, 32, D) -> cosine similarity per take (N,)."""
    q = query.ravel()
    t = takes.reshape(len(takes), -1)
    denom = np.linalg.norm(t, axis=1) * np.linalg.norm(q)
    return np.divide(t @ q, denom, out=np.zeros(len(t)), where=denom > 0)


def dtw_distances(query, takes):
    """Classic DTW over frames with euclidean frame distance, normalised by n + m,
    computed for one query against all N takes at once (numpy over the take axis).
    Note: ~12 ms per query against 500 takes (M-series Mac), so a 500-take leave-one-out
    (250k pairs of 32 frames) takes ~6 s. For much larger libraries switch to a compiled
    DTW (e.g. numba) or prune candidates with cosine first."""
    n, m = len(query), takes.shape[1]
    # Squared distances via |a|^2 + |b|^2 - 2ab (one matrix product instead of an (N,32,32,126) array).
    sq = (query ** 2).sum(-1)[None, :, None] + (takes ** 2).sum(-1)[:, None, :] \
        - 2 * (takes @ query.T).transpose(0, 2, 1)
    cost = np.ascontiguousarray(np.sqrt(np.maximum(sq, 0.0)).transpose(1, 2, 0))  # (n, m, N)
    acc = np.full((n + 1, m + 1, len(takes)), np.inf)
    acc[0, 0] = 0.0
    # Fill one anti-diagonal (i + j = d) at a time: its cells only depend on the two previous diagonals.
    for d in range(2, n + m + 1):
        i = np.arange(max(1, d - m), min(n, d - 1) + 1)
        j = d - i
        acc[i, j] = cost[i - 1, j - 1] + np.minimum(np.minimum(acc[i - 1, j], acc[i, j - 1]), acc[i - 1, j - 1])
    return acc[n, m] / (n + m)


def scores_against(query, takes, use_dtw):
    """Higher is better for both metrics (DTW distance is negated)."""
    return -dtw_distances(query, takes) if use_dtw else cosine_scores(query, takes)


def rank_from_scores(scores, labels, use_dtw, k=1):
    """Best score per label, sorted best first, with confidences. k > 1: see vote_from_scores().

    Confidence = softmax over the per-label best scores divided by a temperature.
    For cosine the raw similarity is used. For DTW the negated distances are first
    divided by the mean distance, so the temperature does not depend on the
    absolute scale of the data. Confidences sum to 1 over all labels in the library,
    so they say how clearly the top label beats the others, not absolute certainty.
    Takes scored -inf (excluded) are ignored."""
    names = [l for l in sorted(set(labels)) if np.isfinite(scores[labels == l]).any()]
    if not names:
        return []
    best = np.array([scores[labels == l].max() for l in names])
    if k > 1:
        return vote_from_scores(scores, labels, names, best, k)
    if use_dtw:
        scaled = best / (np.abs(best).mean() or 1.0) / DTW_TEMPERATURE
    else:
        scaled = best / COSINE_TEMPERATURE
    conf = np.exp(scaled - scaled.max())
    conf /= conf.sum()
    order = np.argsort(-best)
    return [(names[i], best[i], conf[i]) for i in order]


def vote_from_scores(scores, labels, names, best, k):
    """k-nearest voting: every one of the k best takes votes for its label. Labels are sorted by
    votes, ties broken by the label's best score; confidence = vote share (votes / k)."""
    nearest = np.argsort(-scores)[:k]
    nearest = nearest[np.isfinite(scores[nearest])]
    votes = np.array([(labels[nearest] == l).sum() for l in names])
    order = np.lexsort((-best, -votes))
    return [(names[i], best[i], votes[i] / len(nearest)) for i in order]


def rank_labels(query, library, use_dtw, exclude_id=None, k=1):
    takes = np.stack([t["data"] for t in library])
    labels = np.array([t["label"] for t in library])
    scores = scores_against(query, takes, use_dtw)
    scores[[t["id"] == exclude_id for t in library]] = -np.inf  # a query can't match itself
    return rank_from_scores(scores, labels, use_dtw, k)


# --- Self test ---

def self_test(library, use_dtw, k=1):
    takes = np.stack([t["data"] for t in library])
    labels = np.array([t["label"] for t in library])
    names = sorted(set(labels))
    confusion = {t: {p: 0 for p in names} for t in names}
    started = time.time()
    for i in range(len(library)):
        scores = scores_against(takes[i], takes, use_dtw)
        scores[i] = -np.inf  # leave this take out
        ranked = rank_from_scores(scores, labels, use_dtw, k)
        if ranked:
            confusion[labels[i]][ranked[0][0]] += 1

    width = max(8, max(len(l) for l in names) + 1)
    print("Leave-one-out confusion (rows = true label, columns = predicted):")
    print("".ljust(width) + "".join(l[:width - 1].rjust(width) for l in names))
    for t in names:
        print(t.ljust(width) + "".join(str(confusion[t][p]).rjust(width) for p in names))

    print("\nPer-label accuracy:")
    for t in names:
        n = sum(confusion[t].values())
        print(f"  {t:{width}s} {confusion[t][t]:4d}/{n:<4d} {100.0 * confusion[t][t] / n:5.1f}%")
    correct = sum(confusion[t][t] for t in names)
    print(f"Accuracy: {correct}/{len(library)} = {100.0 * correct / len(library):.1f}%"
          f"  (chance {100.0 / len(names):.1f}%, {time.time() - started:.1f}s)")


# --- Main ---

def main():
    parser = argparse.ArgumentParser(description="Match a sign take against the library.")
    parser.add_argument("paths", nargs="*", help="[library_dir] [query]; or use --library / --query")
    parser.add_argument("--library", help="library dir for one language, e.g. data/signs/ase")
    parser.add_argument("--query", help="take json, label.json (+ --take), sequence.json or frames folder")
    parser.add_argument("--take", type=int, default=0, help="take index when the query is a label.json")
    parser.add_argument("--dtw", action="store_true", help="use DTW distance instead of cosine similarity")
    parser.add_argument("--self-test", action="store_true", help="leave-one-out over all takes in the library")
    parser.add_argument("--k", type=int, default=1,
                        help="vote over the k nearest takes (default 1: best take per label)")
    parser.add_argument("--no-location", action="store_true",
                        help="drop the location columns and compare hand shape only")
    args = parser.parse_args()

    paths = list(args.paths)
    library_dir = args.library or (paths.pop(0) if paths else None)
    query_path = args.query or (paths.pop(0) if paths else None)
    if not library_dir:
        parser.error("give a library dir (positional or --library)")

    library, layouts = load_library(library_dir)
    check_layouts(layouts, args.no_location)
    if args.no_location:
        for t in library:
            t["data"] = t["data"][:, :HAND_VALUES]
    metric = "DTW" if args.dtw else "cosine"
    extras = f", k={args.k}" if args.k > 1 else ""
    extras += ", no location" if args.no_location else ""
    print(f"Library: {len(library)} takes in {library_dir} (metric: {metric}{extras})")
    if not library:
        if any(p.is_dir() for p in Path(library_dir).glob("*")):
            print("  (no label files here; point at one language folder, e.g. data/signs/ase)")
        return

    if args.self_test:
        self_test(library, args.dtw, args.k)
        return
    if not query_path:
        parser.error("give a query (positional or --query) or --self-test")

    width = library[0]["data"].shape[1]
    for name, query_id, query in load_queries(query_path, args.take):
        if args.no_location:
            query = query[:, :HAND_VALUES]
        if query.shape[1] != width:
            sys.exit(f"{name}: {query.shape[1]} values per frame but the library has {width}; "
                     "re-import one of them or use --no-location.")
        ranked = rank_labels(query, library, args.dtw, exclude_id=query_id, k=args.k)
        print(f"Top matches for {name}:")
        for label, s, c in ranked[:3]:
            print(f"  {label:20s} score {s:+.4f}  confidence {100 * c:5.1f}%")


if __name__ == "__main__":
    main()
