# extract.py - run MediaPipe Holistic Landmarker (hands + body pose) over a folder of timestamped frames.
#
# Usage:
#   python extract.py <frames_folder> --out <sequence.json> [--preview <preview.mp4>]

import argparse
import json
import re
import sys
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import vision
from mediapipe.tasks.python.core.base_options import BaseOptions

MODEL_PATH = Path(__file__).parent / "models" / "holistic_landmarker.task"
HAND_MODEL_PATH = Path(__file__).parent / "models" / "hand_landmarker.task"
NUM_POINTS = 21

# Holistic finds hands from the body pose (hand regions are cropped around the pose wrists), so it
# finds no hands when no body is in view, which is the normal case for the wearer's own hands in
# the first-person glasses view. When Holistic finds no hands in a frame and this is on, the old
# Hand Landmarker runs on that frame instead (if models/hand_landmarker.task exists); those frames
# get hands but no pose, so their location features are zero.
# TODO: check on real glasses footage how often Holistic sees a body / hands at all.
HAND_FALLBACK = True

# Pose landmarks used for the location features: nose 0, shoulders 11 + 12.
POSE_NOSE, POSE_LEFT_SHOULDER, POSE_RIGHT_SHOULDER = 0, 11, 12
POSE_MIN_VISIBILITY = 0.5  # TODO: tune. nose and both shoulders must be at least this visible

# Standard 21-point hand skeleton (wrist=0, thumb 1-4, index 5-8, middle 9-12, ring 13-16, pinky 17-20).
HAND_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (0, 17), (17, 18), (18, 19), (19, 20),
]

# BGR colours for the preview.
COLOURS = {"left": (255, 128, 0), "right": (0, 200, 255)}


# --- Frame listing ---

def frame_timestamp(path):
    """First long integer (>= 6 digits) in the file stem, e.g. frame_1762134567890.jpg -> 1762134567890."""
    match = re.search(r"\d{6,}", path.stem)
    return int(match.group()) if match else None


def list_frames(folder):
    frames = []
    for path in Path(folder).iterdir():
        if path.suffix.lower() not in (".jpg", ".jpeg"):
            continue
        ts = frame_timestamp(path)
        if ts is None:
            print(f"skipping {path.name}: no timestamp in name")
            continue
        frames.append((ts, path))
    frames.sort(key=lambda f: f[0])
    return frames


# --- Hand + pose detection ---

def make_landmarker():
    """Holistic landmarker (Tasks API), plus the Hand Landmarker fallback -> dict for detect()."""
    if not MODEL_PATH.exists():
        sys.exit(f"Model not found at {MODEL_PATH}. See README.md for the download command.")
    holistic = vision.HolisticLandmarker.create_from_options(vision.HolisticLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(MODEL_PATH)),
        running_mode=vision.RunningMode.VIDEO,
    ))
    hands = None
    if HAND_FALLBACK and HAND_MODEL_PATH.exists():
        hands = vision.HandLandmarker.create_from_options(vision.HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(HAND_MODEL_PATH)),
            running_mode=vision.RunningMode.VIDEO,
            num_hands=2,
        ))
    return {"holistic": holistic, "hands": hands}


def close_landmarker(landmarker):
    for model in landmarker.values():
        if model is not None:
            model.close()


def empty_hand():
    return {"visible": False, "points": [[0.0, 0.0, 0.0] for _ in range(NUM_POINTS)]}


def empty_pose():
    return {"visible": False, "nose": [0.0, 0.0, 0.0], "shoulder_mid": [0.0, 0.0, 0.0]}


def detect(landmarker, image_bgr, ts_ms):
    """One frame -> {"hands": {...}, "pose": {...}} (the per-frame sequence.json fields)."""
    rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    result = landmarker["holistic"].detect_for_video(mp_image, ts_ms)

    # Holistic labels hands by BODY SIDE: left_hand_landmarks is the subject's own left hand, as
    # placed by the pose model for an unmirrored image of a person (the same convention as the
    # Kaggle asl-signs columns, which look swapped there only because those videos are mirrored
    # selfies). The glasses camera is NOT mirrored (unlike a selfie camera), so the labels are
    # used as-is. If frames ever come from a mirrored source, swap "left" and "right" here.
    hands = {"left": empty_hand(), "right": empty_hand()}
    for side, landmarks in (("left", result.left_hand_landmarks), ("right", result.right_hand_landmarks)):
        if landmarks:
            hands[side] = {"visible": True, "points": [[lm.x, lm.y, lm.z] for lm in landmarks]}

    pose = empty_pose()
    if result.pose_landmarks:
        lms = result.pose_landmarks
        refs = [lms[POSE_NOSE], lms[POSE_LEFT_SHOULDER], lms[POSE_RIGHT_SHOULDER]]
        nose, ls, rs = [[lm.x, lm.y, lm.z] for lm in refs]
        pose = {
            "visible": all((lm.visibility if lm.visibility is not None else 1.0) >= POSE_MIN_VISIBILITY for lm in refs),
            "nose": nose,
            "shoulder_mid": [(a + b) / 2 for a, b in zip(ls, rs)],
        }

    if landmarker["hands"] is not None and not any(h["visible"] for h in hands.values()):
        hands = detect_hands_fallback(landmarker["hands"], mp_image, ts_ms)
    return {"hands": hands, "pose": pose}


def detect_hands_fallback(hand_landmarker, mp_image, ts_ms):
    """Old Hand Landmarker path, used when Holistic sees no hands (e.g. no body in view)."""
    result = hand_landmarker.detect_for_video(mp_image, ts_ms)
    hands = {"left": empty_hand(), "right": empty_hand()}
    for landmarks, handedness in zip(result.hand_landmarks, result.handedness):
        # The glasses camera is NOT mirrored (unlike a selfie camera), so MediaPipe's
        # handedness label is used as-is. If frames ever come from a mirrored source,
        # swap "left" and "right" here.
        side = handedness[0].category_name.lower()
        if side not in hands or hands[side]["visible"]:
            continue  # unknown label, or a second hand with the same label: keep the first
        hands[side] = {
            "visible": True,
            "points": [[lm.x, lm.y, lm.z] for lm in landmarks],
        }
    return hands


# --- Preview video ---

def draw_hands(image, hands):
    h, w = image.shape[:2]
    for side, hand in hands.items():
        if not hand["visible"]:
            continue
        pts = [(int(x * w), int(y * h)) for x, y, _ in hand["points"]]
        for a, b in HAND_CONNECTIONS:
            cv2.line(image, pts[a], pts[b], COLOURS[side], 2)
        for p in pts:
            cv2.circle(image, p, 3, COLOURS[side], -1)
        cv2.putText(image, side, (pts[0][0] + 6, pts[0][1] + 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, COLOURS[side], 2)
    return image


def fps_from_timestamps(timestamps):
    if len(timestamps) < 2:
        return 10.0
    median_gap = float(np.median(np.diff(timestamps)))
    return 1000.0 / median_gap if median_gap > 0 else 10.0


# --- Main ---

def main():
    parser = argparse.ArgumentParser(description="Extract hand + pose landmarks from timestamped JPEG frames.")
    parser.add_argument("frames_folder")
    parser.add_argument("--out", required=True, help="output sequence.json")
    parser.add_argument("--preview", help="preview mp4 (default: <out stem>_preview.mp4)")
    args = parser.parse_args()

    out_path = Path(args.out)
    preview_path = Path(args.preview) if args.preview else out_path.with_name(out_path.stem + "_preview.mp4")

    frames = list_frames(args.frames_folder)
    landmarker = make_landmarker()
    print(f"Loaded model {MODEL_PATH.name}; {len(frames)} frames in {args.frames_folder}")

    width = height = None
    writer = None
    fps = fps_from_timestamps([ts for ts, _ in frames])
    out_frames = []
    last_ts = -1

    for ts, path in frames:
        image = cv2.imread(str(path))
        if image is None:
            print(f"skipping {path.name}: could not read")
            continue
        if width is None:
            height, width = image.shape[:2]
            preview_path.parent.mkdir(parents=True, exist_ok=True)
            writer = cv2.VideoWriter(str(preview_path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
        if ts <= last_ts:
            continue  # VIDEO mode requires strictly increasing timestamps
        last_ts = ts

        found = detect(landmarker, image, ts)
        out_frames.append({"ts": ts, **found})
        writer.write(draw_hands(image, found["hands"]))

    close_landmarker(landmarker)
    if writer is not None:
        writer.release()

    sequence = {
        "source": str(Path(args.frames_folder).resolve()),
        "width": width or 504,
        "height": height or 896,
        "frames": out_frames,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(sequence))

    n = len(out_frames)
    print(f"Wrote {out_path} ({n} frames)")
    if writer is not None:
        print(f"Wrote {preview_path} at {fps:.1f} fps")
    for side in ("left", "right"):
        seen = sum(f["hands"][side]["visible"] for f in out_frames)
        pct = 100.0 * seen / n if n else 0.0
        print(f"  {side:5s} hand detected in {pct:5.1f}% of frames ({seen}/{n})")
    seen = sum(f["pose"]["visible"] for f in out_frames)
    pct = 100.0 * seen / n if n else 0.0
    print(f"  pose (nose + shoulders) in {pct:5.1f}% of frames ({seen}/{n})")


if __name__ == "__main__":
    main()
