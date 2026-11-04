# Almero sign tools

Standalone Python scripts for building and testing a small sign-language library from
glasses camera frames. **Nothing here is connected to the Flutter app yet**; these are
offline tools for collecting data and trying out matching.

## Setup (macOS, Apple Silicon)

```sh
cd tools
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# MediaPipe models (gitignored)
mkdir -p models
curl -L -o models/holistic_landmarker.task \
  https://storage.googleapis.com/mediapipe-models/holistic_landmarker/holistic_landmarker/float16/latest/holistic_landmarker.task
# Optional fallback for frames where Holistic finds no hands (see extract.py, HAND_FALLBACK)
curl -L -o models/hand_landmarker.task \
  https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task
```

Check everything works with synthetic data (uses a temp folder, does not touch `data/`):

```sh
python selftest.py
python selftest_kaggle.py   # Kaggle import path on fabricated data
```

## Commands

1. **Extract** hand and body-pose landmarks from a folder of JPEG frames named with a
   millisecond timestamp (e.g. `frame_1762134567890.jpg`) with MediaPipe Holistic (Tasks API
   `HolisticLandmarker`, the same landmark model family as the Kaggle dataset):

   ```sh
   python extract.py recordings/hello_01 --out sequences/hello_01.json [--preview out.mp4]
   ```

   Writes the landmark sequence plus a preview video with the hand skeletons drawn
   (default `sequences/hello_01_preview.mp4`), and prints how often each hand and the pose
   (nose + both shoulders) were detected.

   Holistic labels hands by **body side** (`left` = the subject's own left hand, placed by the
   pose model). The glasses camera is not mirrored, so the labels are used as-is. Holistic
   finds hands via the body pose, so it finds no hands when no body is in view, which is the
   usual first-person glasses case. With `HAND_FALLBACK = True` (default) such frames are
   re-run through the old Hand Landmarker (if `models/hand_landmarker.task` exists); they get
   hands but no pose, so their location features are zero.

2. **Segment** a sequence into individual signs and append them to the library:

   ```sh
   python segment.py sequences/hello_01.json --label hello [--language nsl] [--signer godson] [--out data/signs]
   ```

   A sign starts when a hand comes into frame and ends when the hands leave the frame
   or hold still for more than 0.5 s. Each sign is normalised (wrist origin, fixed
   scale, left-hand-only signs mirrored into the right slot) and resampled to 32 frames,
   and the location features (wrist relative to the body, see Library layout) are added.
   Appending to a label file written with a different feature layout is refused.

3. **Match** a take against the library:

   ```sh
   python match.py data/signs/nsl data/signs/nsl/hello.json --take 0 [--dtw]
   python match.py data/signs/nsl --self-test [--dtw]
   python match.py --library data/signs/nsl --query recordings/hello_01        # frames folder
   python match.py --library data/signs/nsl --query sequences/hello_01.json    # extract.py output
   python match.py --library data/signs/ase --self-test --dtw --k 5            # 5-nearest voting
   python match.py --library data/signs/ase --self-test --no-location          # hand shape only
   ```

   Prints the top 3 labels with a confidence, or with `--self-test` a leave-one-out
   confusion table, per-label accuracy and overall accuracy over the whole library.
   `--query` accepts a single take json, a `label.json` (with `--take N`), an `extract.py`
   `sequence.json`, or a folder of glasses JPEG frames; sequences and folders are run
   through the extract/segment logic and every detected sign is matched separately.
   Default metric is cosine similarity; `--dtw` uses dynamic time warping. Always point
   `--library` at one language folder (`data/signs/nsl`, `data/signs/ase`).

   `--k N` (default 1) predicts by majority vote over the N nearest takes instead of the best
   take per label; ties are broken by the label's best score and the confidence is the vote
   share. `--no-location` drops the 12 location columns from library and query, so before/after
   comparisons run on the same files. A library that mixes feature layouts (e.g. old 126-value
   files with new 138-value ones) is refused unless `--no-location` is given.

## Benchmark: Kaggle "asl-signs" (American Sign Language)

`import_kaggle.py` builds an `ase` library from the Kaggle competition
[Google - Isolated Sign Language Recognition](https://www.kaggle.com/competitions/asl-signs)
(250 signs, MediaPipe Holistic landmarks per frame). Only `train.csv` and the individual
parquet files for the chosen sequences are downloaded (never the ~40 GB full dataset);
they are cached under `data/kaggle/` (gitignored) in the competition layout.

**Credentials (one-time):**

1. Sign in to Kaggle and accept the rules at https://www.kaggle.com/competitions/asl-signs/rules
   (without this every download returns 403).
2. Create an API token at https://www.kaggle.com/settings/api and save it:
   `mkdir -p ~/.kaggle && mv ~/Downloads/kaggle.json ~/.kaggle/ && chmod 600 ~/.kaggle/kaggle.json`
   (the CLI also accepts `~/.kaggle/access_token`, `KAGGLE_API_TOKEN`, or `kaggle auth login`).
3. Alternatively download the files by hand into `data/kaggle/train.csv` and
   `data/kaggle/train_landmark_files/<participant_id>/<sequence_id>.parquet` and add `--offline`.

**Commands:**

```sh
python import_kaggle.py --list                        # downloads train.csv, prints all signs with counts
python import_kaggle.py                               # default signs, up to 50 takes each -> data/signs/ase/
python import_kaggle.py --signs hello yes no --max-takes 50 [--no-mirror] [--offline]
python match.py --library data/signs/ase --self-test [--dtw] [--k 5] [--no-location]
```

Leave-one-out on the 8 default signs that exist in the dataset (391 takes, 21 participants):

| | cosine | DTW |
|---|---|---|
| hand shape only (`--no-location`) | 54.5% | 61.4% |
| + location | 62.1% | 66.5% |
| + location, `--k 5` | 65.5% | 69.3% |

The default sign list is `hello "thank you" yes no please help water more mother father`.
Names are matched ignoring case and spaces (`thank you` -> `thankyou`), plus a small alias
table (`mother` -> `mom`, `father` -> `dad`); signs that are not among the 250 are reported
and skipped (with the closest dataset names), so check `--list`. Library files use the
dataset's sign name (`thankyou.json`). Takes are picked round-robin across participants so no
signer dominates, each take's `signer` is the participant id, and files for the chosen signs
are overwritten on every run. Each sequence is trimmed to the frames that have a hand,
normalised and resampled with the same `segment.py` functions as our own recordings
(`take_features()`), including the location features from the parquet `pose` rows
(nose = landmark 0, shoulder midpoint = landmarks 11 + 12).
Frame index -> timestamp assumes 30 fps and the frame size is assumed to be 504x896 for
`normalise()` (both `# TODO` in `import_kaggle.py`).

`python selftest_kaggle.py` checks the whole path on fabricated parquet files without any
Kaggle account (temporary folder only).

**Handedness (`--mirror`, the default):** the dataset was recorded with a selfie (mirrored)
webcam and labelled by MediaPipe Holistic, whose hand labels follow the pose model. In a
mirrored image the signer's physical right hand looks like the *left* hand of a person facing
the camera, so it is stored in the `left_hand` column. `--mirror` swaps the columns so the
signer's physical right hand goes into our right slot. x is not flipped: in a mirrored selfie
the signer's right hand is already on the right side of the image, as it is in the glasses'
first-person view. `--no-mirror` uses the columns as labelled. The import summary prints the
share of hand frames in the right slot; with mostly right-handed signers it should be high on
two-handed signs too. One-handed takes end up in the right slot either way (left-only takes
are mirrored by `normalise()`), so the flag mainly matters for two-handed signs.

**Caveat:** this is a benchmark of the matching method, not of glasses footage. The dataset is
a webcam selfie view (camera in front, facing the signer, whole upper body in frame); the
glasses are a first-person view from behind the hands, where hands often leave the frame and
depth movements point away from the camera. Accuracy on `ase` is an upper bound for what to
expect from the same method on glasses recordings, and `ase` takes should not be mixed into
the glasses libraries without testing.

Thresholds marked `# TODO` in `segment.py` and `match.py` still need tuning on real footage.
The location features need the signer's body in view; on first-person glasses footage they
will mostly be zero, so they help mainly for camera-facing recordings like the Kaggle data.

## Library layout

```
data/signs/<language>/<label>.json
```

```json
{
  "label": "hello",
  "language": "nsl",
  "signer": "godson",
  "features": "hands126+location12",
  "location_weight": 0.8,
  "takes": [
    {"id": "hello_godson_001", "signer": "godson", "source": "...", "start_ts": 1762134567890, "end_ts": 1762134568890,
     "data": [[138 floats], ... 32 frames]}
  ]
}
```

Each frame is 138 values:

| columns | content |
|---|---|
| 0..62 | left hand, 21 points x `x, y, z` (wrist origin of the first frame, / `REFERENCE_SCALE_PX`) |
| 63..125 | right hand, same |
| 126..131 | left wrist - shoulder midpoint (`x, y, z`), left wrist - nose (`x, y, z`) |
| 132..137 | right wrist - shoulder midpoint, right wrist - nose |

A hand that is not visible is all zeros, and its location values are zero when the hand or the
pose is not visible. Location values use the same pixel scale as the hands and are multiplied
by `LOCATION_WEIGHT` (`segment.py`, measured so location is ~30% of the vector norm); z is
always 0 for now (hand and pose depth are on different scales). Files without a `features`
field are the old 126-value layout (`hands126`); re-import / re-segment them.

## sequence.json (output of extract.py)

```json
{"source": "...", "width": 504, "height": 896,
 "frames": [{"ts": 1762134567890,
             "hands": {"left":  {"visible": true,  "points": [[x, y, z], ... 21]},
                       "right": {"visible": false, "points": [[0, 0, 0], ... 21]}},
             "pose": {"nose": [x, y, z], "shoulder_mid": [x, y, z], "visible": true}}]}
```

`pose.visible` is true when Holistic found a body with the nose and both shoulders visible
(`POSE_MIN_VISIBILITY`). Older sequence files without `pose` still load (no location features).

Points are MediaPipe normalised image coordinates (x, y in 0..1; z relative to the wrist).
