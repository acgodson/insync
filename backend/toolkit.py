"""Imports the shared feature builder, segmenter and matcher from tools/ (wrapped, never copied)."""
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import extract  # noqa: E402  (MediaPipe landmarkers + video decoding)
import match  # noqa: E402  (library loading, cosine / DTW ranking)
import segment  # noqa: E402  (find_signs, take_features, append_takes)

DEFAULT_LIBRARY_DIR = TOOLS_DIR / "data" / "signs"
