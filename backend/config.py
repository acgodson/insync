"""Service settings (env overrides)."""
import os
from pathlib import Path

from toolkit import DEFAULT_LIBRARY_DIR

CONFIDENCE_THRESHOLD = float(os.environ.get("CONFIDENCE_THRESHOLD", "0.6"))
TAKES_REQUIRED = int(os.environ.get("TAKES_REQUIRED", "2"))
LIBRARY_DIR = Path(os.environ.get("LIBRARY_DIR", DEFAULT_LIBRARY_DIR))
UPLOAD_DIR = Path(__file__).parent / "uploads"

USE_DTW = os.environ.get("MATCH_DTW", "0") == "1"
MATCH_K = int(os.environ.get("MATCH_K", "5"))
SENTENCE_GAP_MS = 2000          # labels recognised within this window form one sentence
STATUS_INTERVAL_S = 2.0
IDLE_FLUSH_S = 0.6              # no frames for this long closes an open sign
DEFAULT_LANGUAGE = "nsl"

# Head-relative anchors for the glasses view, in normalised image units.
# TODO: measure. The wearer's nose sits above the top edge of the forward camera frame.
NOSE_ANCHOR = (0.5, -0.15)
FACE_WIDTH = 0.30               # face width as a fraction of frame width
