"""Records laptop-webcam frames in the app's Record-mode layout (frame_<ms>.jpg, portrait 504x896).

  python tests/capture.py <out_folder> [--seconds 4] [--camera 0]
"""
import argparse
import time
from pathlib import Path

import cv2
import numpy as np

W, H = 504, 896


def main():
    p = argparse.ArgumentParser()
    p.add_argument("out")
    p.add_argument("--seconds", type=float, default=4)
    p.add_argument("--camera", type=int, default=0)
    a = p.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(a.camera)
    if not cap.isOpened():
        raise SystemExit("webcam not available (check camera permission for the terminal)")
    for i in range(3, 0, -1):
        print(f"starting in {i}...")
        time.sleep(1)
    print("recording: wave at the camera")
    n, t0 = 0, time.time()
    while time.time() - t0 < a.seconds:
        ok, img = cap.read()
        if not ok:
            break
        h, w = img.shape[:2]
        scaled = cv2.resize(img, (W, int(h * W / w)))  # keep the whole webcam view, letterboxed to portrait
        canvas = np.zeros((H, W, 3), np.uint8)
        y0 = (H - scaled.shape[0]) // 2
        canvas[y0:y0 + scaled.shape[0]] = scaled
        img = canvas
        cv2.imwrite(str(out / f"frame_{int(time.time() * 1000)}.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 70])
        n += 1
        time.sleep(0.05)
    cap.release()
    print(f"saved {n} frames to {out}")


if __name__ == "__main__":
    main()
