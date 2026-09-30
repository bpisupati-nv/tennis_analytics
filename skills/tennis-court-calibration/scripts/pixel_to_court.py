"""Convert pixel positions to court metres using a saved calibration; no image needed.

Usage:
  pixel_to_court.py CALIBRATION_JSON X,Y [X,Y ...]

CALIBRATION_JSON is a <name>_calibration.json written by calibrate_court.py.
Pixels are in the full-resolution frame that was calibrated. Prints JSON with
each pixel and its court position in metres (origin at the far-left doubles
corner, x across the court 0 to 10.97, y along it 0 to 23.77).
Exit code: 0 converted, 2 the calibration file holds no homography, 1 error.
"""
import argparse
import json
import sys

import cv2
import numpy as np


def parse_point(value):
    try:
        x, y = value.split(",")
        return float(x), float(y)
    except ValueError:
        sys.exit(f"error: expected X,Y, got {value!r}")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("calibration")
    ap.add_argument("points", nargs="+")
    args = ap.parse_args()

    try:
        with open(args.calibration) as f:
            cal = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        sys.exit(f"error: cannot read calibration {args.calibration}: {exc}")
    if not cal.get("calibrated") or "pixel_to_court" not in cal:
        print(f"{args.calibration} holds no homography: {cal.get('reason', 'not calibrated')}",
              file=sys.stderr)
        sys.exit(2)

    pixels = [parse_point(p) for p in args.points]
    H = np.array(cal["pixel_to_court"], np.float64)
    court = cv2.perspectiveTransform(np.float64([pixels]), H)[0]
    print(json.dumps({
        "calibration": args.calibration,
        "points": [
            {"pixel": list(p), "court_m": [round(float(v), 3) for v in c]}
            for p, c in zip(pixels, court)
        ],
    }, indent=1))


if __name__ == "__main__":
    main()
