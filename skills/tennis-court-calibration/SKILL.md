---
name: tennis-court-calibration
description: Calibrates a tennis court image or video frame, producing the homography between image pixels and court coordinates in metres, plus an overlay image for checking the fit. Use when the user asks to calibrate a tennis court, compute a court homography, map pixels or player positions to court coordinates, or check whether court lines line up with a photo or broadcast frame.
---

# Tennis court calibration

Wraps `CourtMapper` from `tennis_analytics/court.py`. Automatic calibration finds the painted lines, fits a court model, and either returns a homography or refuses. It never guesses.

## Workflow

1. **Run the script** on the image or video. Use a Python that has `opencv-python` and `numpy` (`pip install -r tennis_analytics/requirements.txt`):

   ```bash
   python scripts/calibrate_court.py INPUT [--out-dir DIR] [--points X,Y ...]
   ```

   `scripts/` is relative to this skill's folder. `--points` converts pixel positions (for example a player's feet) to court metres. The script writes `<name>_calibration.json` and `<name>_overlay.jpg` next to the input, or into `--out-dir`, and prints a short summary.

   Exit code 0 means calibrated. 2 means the automatic calibration refused. 1 is an error, such as an unreadable input or `court.py` not found (then pass `--court PATH` or set `TENNIS_COURT_PY`).

2. **Look at the overlay before trusting the numbers.** Read `<name>_overlay.jpg`. Magenta lines are the court model projected with the homography, and the dashed cyan line is the net's footprint.
   - Good fit: the magenta lines sit on the white paint, above all the near baseline, the sidelines and the service line.
   - Wrong fit: magenta lines land on the grass, fences or net, or the court looks shifted by a whole service box. Treat it as not calibrated, even with exit code 0.
   - With layout `near` or `half`, only the near half is fitted. The far half can be off by up to about a metre; say so if the user cares about far-court positions.

3. **If refused or wrong**, fall back to manual corners. Ask the user for the pixel positions of the four doubles corners, in the order far-left, far-right, near-right, near-left, as seen from the camera. For video, `python -m tennis_analytics.main --input VIDEO --manual-court` opens an interactive corner picker. Then rerun and check the overlay again:

   ```bash
   python scripts/calibrate_court.py INPUT --corners X1,Y1 X2,Y2 X3,Y3 X4,Y4
   ```

   Do not invent corner coordinates from a visual impression of the image.

4. **Report back**: whether it calibrated, the layout and score, the paths to the overlay (embed it) and the JSON, and any `--points` conversions. Mention the far-half caveat for `near` or `half` layouts.

## Using the result

To convert more pixel positions later, reuse the saved calibration instead of calibrating again. This needs no image:

```bash
python scripts/pixel_to_court.py <name>_calibration.json X,Y [X,Y ...]
```

It prints each pixel with its `court_m` position. Exit code 2 means the file holds no homography because calibration was refused.

In the JSON, `pixel_to_court` maps pixels to metres; `court_to_pixel` is its inverse. Both are 3×3 matrices in the JSON:

```python
import json, cv2, numpy as np
cal = json.load(open("frame_calibration.json"))
H = np.array(cal["pixel_to_court"])
court_xy = cv2.perspectiveTransform(np.float64([[[800, 700]]]), H)[0, 0]  # metres
```

In code that already uses the project, call `CourtMapper().auto_calibrate(frame)` followed by `mapper.to_world((x, y))` directly.

For the coordinate convention, the JSON fields, accuracy figures and known limits, see [reference.md](reference.md).
