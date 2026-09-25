"""Calibrate a tennis court image or video: homography JSON plus an overlay to check.

Usage:
  calibrate_court.py INPUT [--out-dir DIR] [--points X,Y ...]
                           [--corners X,Y X,Y X,Y X,Y] [--court PATH]

INPUT is an image or a video. For a video, several early frames are tried and
the best calibration is kept.
--points     pixel positions to convert to court metres, e.g. --points 850,620 400,300
--corners    manual fallback: pixel positions of the four doubles corners in the
             order far-left, far-right, near-right, near-left
--court      court.py to use. Default: $TENNIS_COURT_PY, else the tennis_analytics
             checkout this skill lives in (symlinked installs resolve to it too)

Writes <out-dir>/<name>_calibration.json and <name>_overlay.jpg
(out-dir defaults to the input's folder).
Exit code: 0 calibrated, 2 automatic calibration refused, 1 error.
"""
import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path

import cv2
import numpy as np

VIDEO_SUFFIXES = {".mp4", ".mov", ".avi", ".mkv", ".m4v", ".webm"}


def default_court_path():
    if os.environ.get("TENNIS_COURT_PY"):
        return Path(os.environ["TENNIS_COURT_PY"])
    # scripts/ -> tennis-court-calibration/ -> skills/ -> tennis_analytics/
    return Path(__file__).resolve().parents[3] / "court.py"


def load_court(path):
    spec = importlib.util.spec_from_file_location("court_calibration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_frames(path):
    """(frame_index, frame) pairs: one for an image, early frames for a video."""
    if Path(path).suffix.lower() not in VIDEO_SUFFIXES:
        frame = cv2.imread(str(path))
        if frame is None:
            sys.exit(f"error: cannot read image {path}")
        return [(None, frame)]
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        sys.exit(f"error: cannot open video {path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    end = min(max(total - 1, 0), max(int(fps * 3), 1))
    frames = []
    for index in sorted({int(end * i / 5) for i in range(6)}):
        cap.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, frame = cap.read()
        if ok:
            frames.append((index, frame))
    cap.release()
    if not frames:
        sys.exit(f"error: no readable frames in {path}")
    return frames


def parse_points(values):
    points = []
    for value in values or []:
        x, y = value.split(",")
        points.append((float(x), float(y)))
    return points


def project(points, court_to_pixel):
    pts = cv2.perspectiveTransform(
        np.float64(points).reshape(-1, 1, 2), court_to_pixel).reshape(-1, 2)
    if np.isfinite(pts).all() and np.abs(pts).max() < 1e5:
        return pts
    return None


def draw_overlay(frame, court_to_pixel, court, text, colour):
    vis = frame.copy()
    thick = max(2, round(frame.shape[1] / 700))
    if court_to_pixel is not None:
        for start, end, _ in court.COURT_LINES:
            pts = project([start, end], court_to_pixel)
            if pts is not None:
                cv2.line(vis, tuple(np.int32(pts[0])), tuple(np.int32(pts[1])),
                         (255, 0, 255), thick, cv2.LINE_AA)
        net = project([[0, court.COURT_LENGTH / 2],
                       [court.COURT_WIDTH, court.COURT_LENGTH / 2]], court_to_pixel)
        if net is not None:
            for k in range(0, 24, 2):
                p = net[0] + (net[1] - net[0]) * k / 24
                q = net[0] + (net[1] - net[0]) * (k + 1) / 24
                cv2.line(vis, tuple(np.int32(p)), tuple(np.int32(q)),
                         (255, 255, 0), thick, cv2.LINE_AA)
    scale = frame.shape[1] / 1600
    cv2.rectangle(vis, (0, 0), (frame.shape[1], int(44 * scale)), (0, 0, 0), -1)
    cv2.putText(vis, text, (int(10 * scale), int(31 * scale)), cv2.FONT_HERSHEY_SIMPLEX,
                0.9 * scale, colour, max(1, int(2 * scale)), cv2.LINE_AA)
    return vis


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("--out-dir")
    ap.add_argument("--points", nargs="*")
    ap.add_argument("--corners", nargs=4)
    ap.add_argument("--court", default=str(default_court_path()))
    args = ap.parse_args()

    if not Path(args.court).is_file():
        sys.exit(f"error: court.py not found at {args.court}; "
                 "pass --court or set TENNIS_COURT_PY")
    court = load_court(args.court)
    frames = read_frames(args.input)
    out_dir = Path(args.out_dir or Path(args.input).resolve().parent)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(args.input).stem

    best, best_frame = None, frames[0]
    if args.corners:
        method = "manual corners"
        best = court.CourtMapper()
        best.set_corners(parse_points(args.corners))
    else:
        method = "automatic"
        for index, frame in frames:
            mapper = court.CourtMapper()
            if mapper.auto_calibrate(frame) and (
                    best is None or mapper.ranking_score > best.ranking_score):
                best, best_frame = mapper, (index, frame)

    index, frame = best_frame
    h, w = frame.shape[:2]
    result = {
        "input": str(Path(args.input).resolve()),
        "frame_index": index,
        "image_size": [w, h],
        "calibrated": best is not None,
        "method": method,
        "coordinate_system": (
            "metres; origin at the far-left doubles corner; x across the court "
            "(0 to 10.97), y along it (0 far baseline, 23.77 near baseline)"),
    }
    overlay_path = out_dir / f"{stem}_overlay.jpg"
    if best is None:
        result["reason"] = ("automatic calibration refused: no candidate court "
                            "matched the painted lines well enough")
        overlay = draw_overlay(frame, None, court, f"{stem}: NOT CALIBRATED", (0, 0, 255))
    else:
        pixel_to_court = np.asarray(best._H, np.float64)
        pixel_to_court /= pixel_to_court[2, 2]
        court_to_pixel = np.linalg.inv(pixel_to_court)
        court_to_pixel /= court_to_pixel[2, 2]
        result.update({
            "layout": best.model_name,
            "score": best.auto_score,
            "pixel_to_court": pixel_to_court.tolist(),
            "court_to_pixel": court_to_pixel.tolist(),
        })
        points = parse_points(args.points)
        if points:
            result["points"] = [
                {"pixel": list(p), "court_m": [round(v, 3) for v in best.to_world(p)]}
                for p in points
            ]
        label = f"{stem}: {method}, layout {best.model_name}"
        if best.auto_score is not None:
            label += f", score {best.auto_score:.2f}"
        overlay = draw_overlay(frame, court_to_pixel, court, label, (255, 255, 255))
    cv2.imwrite(str(overlay_path), overlay)
    result["overlay"] = str(overlay_path)
    json_path = out_dir / f"{stem}_calibration.json"
    with open(json_path, "w") as f:
        json.dump(result, f, indent=1)

    summary = {k: result[k] for k in
               ("calibrated", "method", "layout", "score", "points", "reason", "overlay")
               if k in result}
    summary["json"] = str(json_path)
    print(json.dumps(summary, indent=1))
    sys.exit(0 if best is not None else 2)


if __name__ == "__main__":
    main()
