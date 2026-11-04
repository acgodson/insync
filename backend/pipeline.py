"""Frames -> landmarks -> live sign segments -> features / matches. Wraps tools/ for the live stream."""
import numpy as np

from toolkit import extract, match, segment
from config import FACE_WIDTH, MATCH_K, NOSE_ANCHOR, USE_DTW

SIDES = segment.SIDES
DROPOUT_MS = 300   # a hand lost for less than this does not end the sign (tracking flicker)  TODO: tune


# --- Landmarks ---

def make_hand_landmarker():
    return extract.vision.HandLandmarker.create_from_options(extract.vision.HandLandmarkerOptions(
        base_options=extract.BaseOptions(model_asset_path=str(extract.HAND_MODEL_PATH)),
        running_mode=extract.vision.RunningMode.VIDEO,
        num_hands=2,
    ))


def detect_hands(landmarker, image_bgr, ts_ms):
    """One frame -> {"left": {visible, points}, "right": {...}} in normalised image coordinates."""
    rgb = extract.cv2.cvtColor(image_bgr, extract.cv2.COLOR_BGR2RGB)
    mp_image = extract.mp.Image(image_format=extract.mp.ImageFormat.SRGB, data=rgb)
    return extract.detect_hands_fallback(landmarker, mp_image, ts_ms)


def head_relative(hands, width, height):
    """Image coordinates -> contract coordinates: origin at the nose, 1 unit = face width,
    x = wearer's right, y = up, z = forward. The glasses never see the wearer's face, so the nose
    and face width are fixed anchors from config (placeholders until measured per profile)."""
    # TODO(phase2): take NOSE_ANCHOR / FACE_WIDTH from the calibration profile
    face_px = FACE_WIDTH * width
    out = []
    for side in SIDES:
        h = hands[side]
        pts = np.array(h["points"], dtype=float)
        x = (pts[:, 0] - NOSE_ANCHOR[0]) * width / face_px
        y = -(pts[:, 1] - NOSE_ANCHOR[1]) * height / face_px
        z = pts[:, 2] * width / face_px
        out.append({"side": side, "visible": bool(h["visible"]),
                    "points": np.stack([x, y, z], axis=1).round(4).tolist() if h["visible"] else []})
    return out


# --- Live segmentation (incremental form of segment.find_signs) ---

class LiveSegmenter:
    """Feed frames one at a time; completed() returns a finished sign segment, if any."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.frames = []          # (ts, points (2,21,3), visible (2,)) since the sign started
        self.prev = None          # last (points, visible) seen, for motion
        self.prev_any = False
        self.still_since = None   # (ts, index into frames)
        self.lost_since = None    # ts when all hands disappeared mid-sign

    def flush(self):
        """Close an open sign when frames stop arriving (stream paused or ended)."""
        done, self.frames = self.frames, []
        self.prev, self.prev_any, self.still_since, self.lost_since = None, False, None, None
        if done and (done[-1][0] - done[0][0]) >= segment.MIN_SIGN_SECONDS * 1000:
            return done
        return None

    def push(self, ts, hands):
        points = np.array([hands[s]["points"] for s in SIDES], dtype=float)
        visible = np.array([hands[s]["visible"] for s in SIDES], dtype=bool)
        any_visible = bool(visible.any())
        moving = False
        if self.prev is not None:
            pts = np.stack([self.prev[0], points])
            vis = np.stack([self.prev[1], visible])
            moving = bool(segment.frame_motion(pts, vis)[1] > segment.MOTION_THRESHOLD)
        done = None

        if not self.frames:
            just_appeared = any_visible and not self.prev_any
            if any_visible and (just_appeared or moving):
                self.frames.append((ts, points, visible))
                self.still_since = None
        elif not any_visible:
            self.lost_since = self.lost_since or ts
            if ts - self.lost_since >= DROPOUT_MS:
                done = self.frames
                self.frames = []
                self.lost_since = None
        else:
            self.lost_since = None
            self.frames.append((ts, points, visible))
            if moving:
                self.still_since = None
            else:
                if self.still_since is None:
                    self.still_since = (ts, len(self.frames) - 1)
                elif ts - self.still_since[0] > segment.PAUSE_SECONDS * 1000:
                    done = self.frames[: self.still_since[1] + 1]
                    self.frames = []
                    self.still_since = None
                    self.lost_since = None

        self.prev = (points, visible)
        self.prev_any = any_visible
        if done and (done[-1][0] - done[0][0]) >= segment.MIN_SIGN_SECONDS * 1000:
            return done
        return None


def features_from_segment(frames, width, height):
    """Completed segment -> 32 x 138 feature array (location block zero: no pose from the glasses)."""
    ts = np.array([f[0] for f in frames], dtype=float)
    points = np.stack([f[1] for f in frames])
    visible = np.stack([f[2] for f in frames])
    pose = np.zeros((len(frames), 2, 3))
    pose_visible = np.zeros(len(frames), dtype=bool)
    data, _, _ = segment.take_features(ts, points, visible, pose, pose_visible, width, height)
    return data


# --- Library and matching ---

def load_library(library_dir, language):
    folder = library_dir / language
    if not folder.exists():
        return []
    takes, layouts = match.load_library(folder)
    if len(layouts) > 1:
        current = (segment.FEATURES, segment.LOCATION_WEIGHT)
        takes = [t for t in takes if t["data"].shape[1] == segment.HAND_VALUES + segment.LOCATION_VALUES]
        print(f"library {folder}: mixed layouts, using {len(takes)} takes with layout {current}")
    return takes


def rank(features, library):
    """-> [(label, confidence)] best first, or [] on an empty library."""
    if not library:
        return []
    k = min(MATCH_K, len(library))
    ranked = match.rank_labels(features, library, USE_DTW, k=k)
    return [(label, float(conf)) for label, _, conf in ranked]


def take_record(data, source, view):
    return {"source": source, "view": view, "start_ts": 0, "end_ts": 0, "data": data.round(5).tolist()}


# --- Uploaded video -> one take ---

def take_from_video(path, width_hint=None):
    """Runs the full extract + segment pipeline (Holistic + fallback) on a video file; longest sign wins."""
    cap = extract.cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise ValueError("could not open video")
    fps = cap.get(extract.cv2.CAP_PROP_FPS) or 30.0
    landmarker = extract.make_landmarker()
    frames, i = [], 0
    try:
        while True:
            ok, image = cap.read()
            if not ok:
                break
            ts = int(i * 1000 / fps)
            d = extract.detect(landmarker, image, ts)
            frames.append({"ts": ts, **d})
            i += 1
    finally:
        extract.close_landmarker(landmarker)
        cap.release()
    if not frames:
        raise ValueError("no frames in video")
    w, h = int(cap.get(extract.cv2.CAP_PROP_FRAME_WIDTH)) or image.shape[1], int(cap.get(extract.cv2.CAP_PROP_FRAME_HEIGHT)) or image.shape[0]
    _, ts, points, visible, pose, pose_visible = segment.sequence_arrays({"frames": frames})
    signs = segment.find_signs(ts, points, visible)
    if not signs:
        raise ValueError("no sign found in video (no hands, or too short)")
    a, b = max(signs, key=lambda s: ts[s[1]] - ts[s[0]])
    sl = slice(a, b + 1)
    data, _, _ = segment.take_features(ts[sl], points[sl], visible[sl], pose[sl], pose_visible[sl], w, h)
    return data, len(frames)
