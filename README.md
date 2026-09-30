# Tennis analytics

## Court calibration

`court.py` provides `CourtMapper`, which finds the painted court lines in a photo or video frame and computes the **homography** between image pixels and court positions in metres. No human input is needed.

Court coordinates are in metres with the origin at the far-left doubles corner: x runs across the court (0–10.97 m) and y along it (0–23.77 m).

### Requirements

OpenCV and numpy (see `requirements.txt`).

### Usage

Run from the directory that contains `tennis_analytics/`:

```python
import cv2
from tennis_analytics.court import CourtMapper

frame = cv2.imread("my_court.jpg")
court = CourtMapper()
if court.auto_calibrate(frame, debug_path="my_court_check.jpg"):   # overlay to eyeball
    x, y = court.to_world((850, 620))        # pixel -> metres on court
    H_pixel_to_court = court._H              # 3x3 homography
    print(court.model_name, court.auto_score)
else:
    court.select_corners_interactive(frame)  # click 4 corners as fallback
```

- `auto_calibrate(frame, debug_path=None)` returns `True` on success. If `debug_path` is given, it writes the photo with the fitted court lines drawn on it.
- `to_world((x, y))` converts a pixel to court metres.
- `model_name` is the court layout that was fitted:
  - `full`: both baselines in view
  - `near`: near service line to near baseline
  - `half`: net to near baseline
- `auto_score`, from 0 to 1, is how well the fitted lines match the paint. It is **not** an accuracy measure: a wrong fit can score high.
- `_H` is the pixel-to-court homography. Invert it for court-to-pixel.
- If automatic calibration fails, `select_corners_interactive(frame)` lets you click the four court corners, or `set_corners(points)` sets them in code.

For video from a fixed camera, calibrate once and reuse the result for every frame. `main.py` does this: it tries automatic calibration on sampled frames and falls back to clicking corners.

### What to expect

- **Handled camera views:** behind a baseline (broadcast style), elevated side or corner views, overhead, and close club cameras with part of the court out of frame.
- **Accuracy on the test photos:** about 4–11 cm median error on the near half. The far half is worse when it has to be extrapolated, up to about 1.2 m for a very close, low camera.
- **It can refuse.** When it isn't confident, `auto_calibrate` returns `False` rather than a wrong answer. Always check the return value.
- **Check the `debug_path` overlay for any new venue.** The code has been tested on only seven photos, so treat new venues as unproven until you've seen the fit.

### Calibration error on the test photos

These are the results for the current `court.py` on the photos in `dataset/`. Error is the distance on the ground between where the calibration places a court point and where the hand-approved ground truth places it. It is sampled on a 25 cm grid over each half of the court, and the ground truth itself is accurate to about 5 cm. All errors are in centimetres.

| Photo | Layout fitted | Score | Near half, median (cm) | Near half, 95th percentile (cm) | Far half, median (cm) | Far half, 95th percentile (cm) | Near half, median before the improvements (cm) |
|---|---|---|---|---|---|---|---|
| Broadcast frame (`court.png`) | near | 0.90 | 9.0 | 16 | 13 | 35 | 9.0 |
| Wimbledon No.1, grass | full | 0.95 | 3.6 | 5.0 | 4.1 | 5.4 | 3.6 |
| Delhi centre, hard | full | 0.95 | 7.2 | 18 | 13 | 23 | 95 |
| Arthur Ashe, hard | full | 1.00 | 5.7 | 9.2 | 3.7 | 6.3 | 5.7 |
| Naples, clay | near | 0.95 | 5.3 | 18 | 31 | 58 | 5.3 |
| Hanoi Times City, hard | near | 0.77 | 11 | 42 | 120 | 213 | 826 |
| Val-d'Oingt, hard | refused | – | – | – | – | – | refused |

- **Near half:** every calibrated photo is within 11 cm (median). The improvements took Delhi from 95 cm to 7 cm and Hanoi from 8.3 m to 11 cm, and left the other four unchanged.
- **Far half:** `full` fits stay within 13 cm. `near` fits extrapolate the far half from the near half, so the error grows with how close and low the camera is, reaching 1.2 m for Hanoi.
- **Partly out of frame:** Hanoi has one corner out of frame, so only 84% of its near half is visible. Its error is measured on the visible part.
- **No ground truth:** Val-d'Oingt has none, and the calibrator refuses it rather than giving a wrong answer.

`calib_report/tables.md` has the same measurements for every stage of development.

### Command line and agent skill

`skills/tennis-court-calibration/` packages calibration as an agent skill. An AI agent reads `SKILL.md` and follows it: calibrate the image, check the overlay, report the homography, and fall back to manual corners if needed. Its script also works on its own:

```bash
python tennis_analytics/skills/tennis-court-calibration/scripts/calibrate_court.py my_court.jpg --points 850,620
```

This writes `my_court_calibration.json` (both homographies, layout, score, point conversions) and `my_court_overlay.jpg`. It exits with code 0 when calibrated and 2 when automatic calibration refuses. Pass `--corners` with the four doubles corners (far-left, far-right, near-right, near-left) to calibrate manually.

To convert more pixels later without recalibrating, pass the saved calibration to `pixel_to_court.py`. It reads only the JSON, not the image:

```bash
python tennis_analytics/skills/tennis-court-calibration/scripts/pixel_to_court.py my_court_calibration.json 850,620 400,300
```

To install the skill, symlink it so that the script can still find `court.py` in this checkout:

```bash
# for one project
mkdir -p .cursor/skills && ln -s "$PWD/tennis_analytics/skills/tennis-court-calibration" .cursor/skills/
# or for every project on your machine
mkdir -p ~/.cursor/skills && ln -s "$PWD/tennis_analytics/skills/tennis-court-calibration" ~/.cursor/skills/
```

If you copy the folder instead of symlinking it, set `TENNIS_COURT_PY=/path/to/tennis_analytics/court.py`. Claude Code users can link it into `.claude/skills/` in the same way.

### How it was built and evaluated

`calib_report/` holds the supporting evidence; you don't need it to use the code:

- `report.md` / `report.html`: results of each improvement stage
- `methodology.md`: how the algorithm works and how it was measured
- `references.json`: ground-truth homographies for the test photos
- `dataset/synthetic/`: warped test samples with exact ground truth. Not checked in; `python calib_report/tools/synth.py` regenerates the same 48 samples.

Per-stage overlays, per-step pipeline frames and the other regenerable outputs are also left out of git (see `.gitignore`). `tools/run_stage.py` and `tools/pipeline_steps.py` rebuild them.
