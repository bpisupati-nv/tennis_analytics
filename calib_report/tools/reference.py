"""Build a ground-truth homography for each test photo, independent of auto-calibration.

Each painted court line is located on its own: pixels of paint inside a narrow
band around a rough initial guess are fitted with a robust straight line. The
reference homography is then solved from every intersection of a transverse
line with a longitudinal one. Because each line is fitted separately, a
mistake in the automatic line search or layout scoring cannot leak into it.
"""
import json
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from common import load_court, REPORT_DIR, PHOTO_DIR, PROJECT_DIR  # noqa: E402

court = load_court(os.path.join(PROJECT_DIR, "court.py"))
CW, CL = court.COURT_WIDTH, court.COURT_LENGTH
SI, SY = court.SINGLES_INSET, court.SERVICE_LINE_Y

TRANSVERSE = {
    "far baseline": ((0, 0), (CW, 0)),
    "far service": ((SI, SY), (CW - SI, SY)),
    "near service": ((SI, CL - SY), (CW - SI, CL - SY)),
    "near baseline": ((0, CL), (CW, CL)),
}
LONGITUDINAL = {
    "L doubles": ((0, 0), (0, CL)),
    "L singles": ((SI, 0), (SI, CL)),
    "centre": ((CW / 2, SY), (CW / 2, CL - SY)),
    "R singles": ((CW - SI, 0), (CW - SI, CL)),
    "R doubles": ((CW, 0), (CW, CL)),
}


def world_line(a, b):
    (x1, y1), (x2, y2) = a, b
    l = np.cross([x1, y1, 1.0], [x2, y2, 1.0])
    return l / np.hypot(l[0], l[1])


class Paint:
    """A paint mask with its pixel coordinates gathered once."""

    def __init__(self, mask):
        self.shape = mask.shape
        self.mask = mask

    def pixels_near(self, p0, p1, margin):
        """Paint pixels inside the box around a segment, grown by ``margin``."""
        h, w = self.shape
        x0 = int(max(0, np.floor(min(p0[0], p1[0]) - margin)))
        x1 = int(min(w, np.ceil(max(p0[0], p1[0]) + margin) + 1))
        y0 = int(max(0, np.floor(min(p0[1], p1[1]) - margin)))
        y1 = int(min(h, np.ceil(max(p0[1], p1[1]) + margin) + 1))
        ys, xs = np.nonzero(self.mask[y0:y1, x0:x1])
        return np.stack([xs + x0, ys + y0], 1).astype(np.float64)


def projected_span(H, seg, shape):
    """Fraction of a court line inside the frame, and its in-frame pixel ends."""
    h, w = shape
    world = np.linspace(seg[0], seg[1], 400)
    px = cv2.perspectiveTransform(world.reshape(-1, 1, 2), H).reshape(-1, 2)
    inside = (px[:, 0] >= 0) & (px[:, 0] < w) & (px[:, 1] >= 0) & (px[:, 1] < h)
    return inside.mean(), px[inside]


def snap_line(paint, H, seg, band):
    """Fit the paint around one projected court line; None if too little paint."""
    h, w = paint.shape
    world = np.linspace(seg[0], seg[1], 400)
    px = cv2.perspectiveTransform(world.reshape(-1, 1, 2), H).reshape(-1, 2)
    inside = (px[:, 0] >= 0) & (px[:, 0] < w) & (px[:, 1] >= 0) & (px[:, 1] < h)
    if inside.mean() < 0.15:
        return None
    px = px[inside]
    p0, p1 = px[0], px[-1]
    d = p1 - p0
    length = np.linalg.norm(d)
    if length < 40:
        return None
    d /= length
    n = np.array([-d[1], d[0]])
    pts = paint.pixels_near(p0, p1, band + 8)
    rel = pts - p0
    along = rel @ d
    across = rel @ n
    sel = (np.abs(across) <= band) & (along >= -5) & (along <= length + 5)
    if sel.sum() < max(40, 0.25 * length):
        return None
    candidates = pts[sel]
    along = along[sel]
    # Crossing lines and nearby clutter drag a single fit off the marking, so
    # keep refitting on the pixels closest to the previous fit only.
    for tight in (band / 2, band / 4, 3.0):
        vx, vy, x0, y0 = cv2.fitLine(
            candidates.astype(np.float32), cv2.DIST_HUBER, 0, 0.01, 0.01).ravel()
        l = np.cross([x0, y0, 1.0], [x0 + vx, y0 + vy, 1.0])
        l /= np.hypot(l[0], l[1])
        keep = np.abs(np.c_[candidates, np.ones(len(candidates))] @ l) <= max(tight, 3.0)
        if keep.sum() < 30:
            return None
        candidates, along = candidates[keep], along[keep]
    covered = np.unique(np.floor(along / (length / 50)).astype(int))
    if len(covered) < 15:
        return None
    vx, vy, x0, y0 = cv2.fitLine(
        candidates.astype(np.float32), cv2.DIST_HUBER, 0, 0.01, 0.01).ravel()
    l = np.cross([x0, y0, 1.0], [x0 + vx, y0 + vy, 1.0])
    return l / np.hypot(l[0], l[1])


def paint_mask(img):
    """Near-white, thin structures only.

    Deliberately stricter than the calibration's own mask: sand, clay and
    gravel surrounds are bright but saturated, and must not pull a line fit.
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    k = max(11, int(img.shape[1] * 0.02)) | 1
    tophat = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, cv2.getStructuringElement(cv2.MORPH_RECT, (k, k)))
    sat = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)[:, :, 1]
    return np.where((tophat >= 20) & (sat <= 90), 255, 0).astype(np.uint8)


def solve(paint, H0, bands):
    H, lines, _ = solve_detailed(paint, H0, bands)
    return H, lines


def solve_detailed(paint, H0, bands):
    """Like ``solve``, also returning the fitted lines and intersection residuals."""
    H = H0.copy()
    used = {}
    for band in bands:
        fitted = {}
        for name, seg in {**TRANSVERSE, **LONGITUDINAL}.items():
            l = snap_line(paint, H, seg, band)
            if l is not None:
                fitted[name] = l
        src, dst = [], []
        for tn in TRANSVERSE:
            for ln in LONGITUDINAL:
                if tn in fitted and ln in fitted:
                    wp = np.cross(world_line(*TRANSVERSE[tn]), world_line(*LONGITUDINAL[ln]))
                    pp = np.cross(fitted[tn], fitted[ln])
                    src.append(wp[:2] / wp[2])
                    dst.append(pp[:2] / pp[2])
        if len(src) < 4:
            raise RuntimeError(f"only {len(src)} intersections from {sorted(fitted)}")
        src, dst = np.float64(src), np.float64(dst)
        # A line snapped to the wrong marking corrupts all of its intersections;
        # RANSAC drops them before the final least-squares solve.
        H, inliers = cv2.findHomography(src, dst, cv2.RANSAC, max(4.0, band / 3))
        if H is None:
            raise RuntimeError("degenerate intersections")
        inliers = inliers.ravel().astype(bool)
        if inliers.sum() >= 4:
            H, _ = cv2.findHomography(src[inliers], dst[inliers], 0)
        used = fitted
    residual = np.linalg.norm(
        cv2.perspectiveTransform(src.reshape(-1, 1, 2), H).reshape(-1, 2) - dst, axis=1)
    info = {
        "fitted": used,
        "rms_px": float(np.sqrt(np.mean(np.square(residual[inliers])))),
        "intersections": int(len(src)),
        "inliers": int(inliers.sum()),
    }
    return H, sorted(used), info


def main(out_path=os.path.join(REPORT_DIR, "references.json")):
    seeds = json.load(open(os.path.join(REPORT_DIR, "reference_seeds.json")))
    out = {}
    for name, seed in seeds.items():
        img = cv2.imread(os.path.join(PHOTO_DIR, name))
        mask = Paint(paint_mask(img))
        if "points" in seed:
            world = np.float64([p["world"] for p in seed["points"]])
            pixel = np.float64([p["pixel"] for p in seed["points"]])
            H0, _ = cv2.findHomography(world, pixel, 0)
        else:
            H0 = np.array(seed["world_to_pixel"], np.float64)
        band = max(8.0, img.shape[1] / 120)
        H, lines = solve(mask, H0, [band * 2.5, band * 1.5, band, band * 0.7])
        out[name] = {"world_to_pixel": H.tolist(), "lines": lines}
        print(f"{name:40s} lines {len(lines)}: {', '.join(lines)}")
    json.dump(out, open(out_path, "w"), indent=1)


if __name__ == "__main__":
    main(*sys.argv[1:2])
