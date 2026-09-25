"""Ground truth for a photo with no human input: a slow offline solver with self-checks.

1. Proposals: the calibration's own candidate courts, from a wider search
   than it runs itself (more vanishing points), and many of them rather than
   only the best one.
2. Fit: each proposal seeds the line-by-line reference fit from reference.py,
   at full resolution with the stricter paint mask.
3. Checks, all independent of the calibration's score:
   - every court line that should be in view is found in the paint
   - every found line agrees with the fitted court to within a few pixels
   - enough lines, in both directions, to pin the court down
4. Uniqueness: every proposal that passes must describe the same court. If two
   different courts both pass, the photo is ambiguous and gets no ground truth.

A photo that fails is left without ground truth rather than given a doubtful one.

Usage: auto_reference.py [--synthetic] [PHOTO ...]
Output: dataset/auto_references.json (or dataset/auto_references_synthetic.json)
"""
import argparse
import json
import os
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
import reference as R  # noqa: E402
from common import (CL, CW, NET, PHOTO_DIR, PHOTOS, REPORT_DIR,  # noqa: E402
                    ground_error, load_court)

TOP_PROPOSALS = 30
VANISHING_POINTS = 5
MIN_LINES = 6            # of nine
MIN_EACH_DIRECTION = 2   # across and along
VISIBLE_FRACTION = 0.5   # a line counts as in view above this fraction in frame
MAX_LINE_DEVIATION = 0.004  # of image width, worst point of any found line
AGREEMENT_CM = 10.0


def proposals(img, court):
    """The calibration's candidate courts, best first, at full resolution."""
    court.VANISHING_POINTS_TRIED = VANISHING_POINTS
    m = court.CourtMapper()
    image, scale = m._working_image(img)
    h, w = image.shape[:2]
    mask = m._line_mask(image)
    families = m._detect_lines(mask, w, h)
    distance_map, _ = m._nearest_line_pixel(mask)
    samples = {mod.name: m._line_samples(mod.lines) for mod in court.COURT_MODELS}
    tolerance = max(2.5, w / 320.0)
    scored, seen = [], set()
    for transverse, longitudinal in families:
        for corners in m._candidate_quads(transverse, longitudinal, w, h):
            key = tuple(np.rint(corners).astype(int).ravel())
            if key in seen:
                continue
            seen.add(key)
            for mod in court.COURT_MODELS:
                H = cv2.getPerspectiveTransform(mod.quad, corners)
                s = m._score_projection(*samples[mod.name], H, distance_map, w, h, tolerance)
                if s is not None:
                    scored.append((s * mod.preference, H.astype(np.float64)))
    scored.sort(key=lambda item: item[0], reverse=True)
    upscale = np.diag([1 / scale, 1 / scale, 1.0])
    return [upscale @ H for _, H in scored[:TOP_PROPOSALS]], len(scored)


def check(H, info, shape):
    """Why this fit is not trustworthy, or None if it passes every check."""
    h, w = shape
    fitted = info["fitted"]
    segments = {**R.TRANSVERSE, **R.LONGITUDINAL}
    missing = []
    worst = 0.0
    for name, seg in segments.items():
        fraction, px = R.projected_span(H, seg, shape)
        in_view = fraction >= VISIBLE_FRACTION and len(px) > 1 and \
            np.linalg.norm(px[-1] - px[0]) >= 0.08 * w
        if name not in fitted:
            if in_view:
                missing.append(name)
            continue
        if len(px):
            line = fitted[name]
            worst = max(worst, float(np.abs(np.c_[px, np.ones(len(px))] @ line).max()))
    across = sum(n in fitted for n in R.TRANSVERSE)
    along = sum(n in fitted for n in R.LONGITUDINAL)
    if missing:
        return f"in view but not found: {', '.join(missing)}", worst
    if len(fitted) < MIN_LINES or min(across, along) < MIN_EACH_DIRECTION:
        return f"too few lines ({across} across, {along} along)", worst
    if worst > MAX_LINE_DEVIATION * w:
        return f"a line is {worst:.1f} px off the fitted court", worst
    return None, worst


def symmetric_error(H_a, H_b, shape):
    """Near-half median distance between two fits, allowing for court symmetry."""
    best = np.inf
    for flip in (np.diag([1.0, 1, 1]), np.array([[-1.0, 0, CW], [0, 1, 0], [0, 0, 1]]),
                 np.array([[1.0, 0, 0], [0, -1, CL], [0, 0, 1]]),
                 np.array([[-1.0, 0, CW], [0, -1, CL], [0, 0, 1]])):
        e = ground_error(H_a @ flip, H_b, shape)["near"]
        if e is not None:
            best = min(best, e["median_cm"])
    return best


def solve_photo(img, court):
    start = time.perf_counter()
    paint = R.Paint(R.paint_mask(img))
    band = max(8.0, img.shape[1] / 120)
    seeds, total = proposals(img, court)
    accepted, reasons = [], {}
    for H0 in seeds:
        try:
            H, lines, info = R.solve_detailed(paint, H0, [band * 2.5, band * 1.5, band, band * 0.7])
        except RuntimeError:
            reasons["fit failed"] = reasons.get("fit failed", 0) + 1
            continue
        reason, worst = check(H, info, img.shape[:2])
        if reason:
            key = reason.split(":")[0].split(" (")[0]
            reasons[key] = reasons.get(key, 0) + 1
            continue
        accepted.append((len(lines), -worst, H, lines, info, worst))
    result = {"proposals_total": total, "seeds_tried": len(seeds),
              "seeds_passed": len(accepted), "rejections": reasons,
              "seconds": round(time.perf_counter() - start, 1)}
    if not accepted:
        return {**result, "status": "rejected", "reason": "no proposal passed the checks"}
    accepted.sort(key=lambda item: item[:2], reverse=True)
    _, _, H, lines, info, worst = accepted[0]
    spread = max(symmetric_error(H, other[2], img.shape) for other in accepted)
    result.update({"world_to_pixel": H.tolist(), "lines": lines, "rms_px": info["rms_px"],
                   "worst_line_px": worst, "disagreement_cm": spread})
    if spread > AGREEMENT_CM:
        return {**result, "status": "ambiguous",
                "reason": f"passing proposals disagree by up to {spread:.0f} cm"}
    return {**result, "status": "accepted"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--synthetic", action="store_true", help="run on dataset/synthetic")
    ap.add_argument("--court", default=os.path.join(PHOTO_DIR, "court.py"),
                    help="court.py whose candidate courts seed the solver")
    ap.add_argument("--out")
    ap.add_argument("photos", nargs="*")
    args = ap.parse_args()
    court = load_court(args.court)
    if args.synthetic:
        manifest = json.load(open(os.path.join(REPORT_DIR, "dataset", "synthetic", "manifest.json")))
        items = [(s["file"], os.path.join(REPORT_DIR, s["file"])) for s in manifest]
        default_out = "auto_references_synthetic.json"
    else:
        names = args.photos or [p for p, _ in PHOTOS]
        items = [(p, os.path.join(PHOTO_DIR, p)) for p in names]
        default_out = "auto_references.json"
    out_path = args.out or os.path.join(REPORT_DIR, "dataset", default_out)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    results = {}
    for key, path in items:
        results[key] = solve_photo(cv2.imread(path), court)
        r = results[key]
        print(f"{key:58s} {r['status']:9s} passed {r['seeds_passed']:2d}/{r['seeds_tried']:2d} "
              f"{r.get('reason', '')} {r['seconds']}s", flush=True)
    json.dump(results, open(out_path, "w"), indent=1)


if __name__ == "__main__":
    main()
