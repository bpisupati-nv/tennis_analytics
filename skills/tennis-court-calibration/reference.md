# Reference

## Court coordinates

Units are metres, measured on the ground plane.

- **Origin:** the far-left doubles corner, as seen from the camera.
- **x axis:** across the court, from 0 to 10.97 (doubles width). The singles sidelines are at 1.37 and 9.60.
- **y axis:** along the court, from 0 (far baseline) to 23.77 (near baseline).
- **Net:** y = 11.885. The service lines are at y = 5.485 and y = 18.285, and the centre service line is at x = 5.485.

The mapping is valid only for points on the ground. For a player, use the feet (bottom centre of the bounding box), not the box centre.

## Output JSON (`<name>_calibration.json`)

| Field | Meaning |
|---|---|
| `calibrated` | `true` if a homography was produced |
| `method` | `automatic` or `manual corners` |
| `layout` | `full` (whole court fitted), `near` (service line to near baseline), or `half` (net to near baseline) |
| `score` | fit quality from 0 to 1 (null for manual corners). Automatic calibration refuses below 0.30 |
| `pixel_to_court` | 3×3 homography from image pixels to court metres |
| `court_to_pixel` | its inverse, used to draw the court on the image |
| `image_size` | `[width, height]` of the frame the homography applies to |
| `frame_index` | the video frame used (null for images) |
| `points` | `--points` conversions: `pixel` and `court_m` |
| `reason` | why it was not calibrated, if applicable |
| `overlay` | path to the check image |

Both matrices are normalised so that the bottom-right entry is 1. They apply to the full-resolution input, not a resized copy.

## Accuracy

These figures come from the test images in `tennis_analytics/calib_report/` (six of the seven calibrate). Errors are the median ground-plane distance against a hand-approved reference.

- Full-court fits: 4–13 cm across the whole court.
- `near` or `half` fits: 5–11 cm on the near half. The far half is extrapolated from the near half, so its error ranges from 13 cm up to 1.2 m.
- The reference's own noise floor is about 5 cm.

## Known limits

- Fits that are consistent but wrong are possible, such as a service line taken for a baseline. The overlay check is the safeguard.
- It refuses when too little paint is visible, or on cluttered or heavily occluded courts (Val-d'Oingt in the test set is refused).
- It assumes a standard doubles court with white lines. Courts marked for other sports, such as overlaid pickleball lines, can confuse line detection.
- Each call calibrates one frame. For a moving camera, calibrate each shot separately.

## How it works

See `tennis_analytics/calib_report/methodology.md` for the method and `report.md` for the stage-by-stage improvements.
