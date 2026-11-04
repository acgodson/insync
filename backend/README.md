# InSync service

FastAPI service implementing the InSync message contract. Wraps `tools/` (feature builder,
segmenter, matcher) without copying it. Library lives in `tools/data/signs/<language>/`.

## Setup

```
cd backend
python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

The MediaPipe models must exist in `tools/models/` (`hand_landmarker.task`, `holistic_landmarker.task`;
see `tools/README.md`).

## Run the service

```
cd backend && .venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
```

Env: `CONFIDENCE_THRESHOLD` (default 0.6, set 0 for the skeleton), `TAKES_REQUIRED` (2),
`LIBRARY_DIR`, `MATCH_DTW=1` (DTW instead of cosine), `MATCH_K` (5).

## Replay recorded frames

Frame folders come from the app's Record mode (`frame_<ms>.jpg`, 504x896).

```
.venv/bin/python tests/replay.py --teach wave <take1_folder> <take2_folder> <query_folder>
.venv/bin/python tests/replay.py <frames_folder>
```

## Upload a video as one take

```
curl -F label=wave -F language=nsl -F file=@wave.mp4 http://localhost:8000/teach/upload
curl http://localhost:8000/library?language=nsl
```

Uploaded videos are deleted after processing; frames are never stored.
