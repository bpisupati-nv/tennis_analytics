"""Shared paths, court-module loading, overlay drawing and error metrics."""
import importlib.util
import os
import sys
import uuid

import cv2
import numpy as np

REPORT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PHOTO_DIR = os.path.dirname(REPORT_DIR)

PHOTOS = [
    ("court.png", "Broadcast frame"),
    ("court_wimbledon_no1_grass.jpg", "Wimbledon No.1 (grass)"),
    ("court_delhi_centre_hard.jpg", "Delhi centre (hard)"),
    ("court_arthur_ashe_hard.jpg", "Arthur Ashe (hard)"),
    ("court_naples_universiade_clay.jpg", "Naples (clay)"),
    ("court_hanoi_times_city_hard.jpg", "Hanoi Times City (hard)"),
    ("court_val_doingt_hard.jpg", "Val-d'Oingt (hard)"),
]


def load_court(path):
    """Import a specific court.py snapshot under a unique module name."""
    name = f"court_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


CW, CL = 10.97, 23.77
SI, SY, NET = 1.37, 5.485, 23.77 / 2
L, R = SI, CW - SI
NEAR = [((L, CL), (R, CL)), ((L, NET), (L, CL)), ((R, NET), (R, CL)),
        ((L, CL - SY), (R, CL - SY)), ((CW / 2, NET), (CW / 2, CL - SY))]
FAR = [((L, 0), (R, 0)), ((L, 0), (L, NET)), ((R, 0), (R, NET)),
       ((L, SY), (R, SY)), ((CW / 2, SY), (CW / 2, NET))]
NET_LINE = [((0, NET), (CW, NET))]
CALIBRATED = (255, 0, 255)
EXTRAPOLATED = (0, 200, 255)
NET_COLOUR = (255, 255, 0)


def _draw(img, H, segs, colour, thick, dashed=False):
    for a, b in segs:
        pts = cv2.perspectiveTransform(
            np.float64([a, b]).reshape(-1, 1, 2), H).reshape(-1, 2)
        if not np.isfinite(pts).all() or np.abs(pts).max() > 1e5:
            continue
        n = 24 if dashed else 1
        step = 2 if dashed else 1
        for k in range(0, n, step):
            p = pts[0] + (pts[1] - pts[0]) * k / n
            q = pts[0] + (pts[1] - pts[0]) * (k + 1) / n
            cv2.line(img, tuple(np.int32(p)), tuple(np.int32(q)), colour, thick, cv2.LINE_AA)


def banner(img, text, colour=(255, 255, 255)):
    scale = img.shape[1] / 1600
    h = int(44 * scale)
    cv2.rectangle(img, (0, 0), (img.shape[1], h), (0, 0, 0), -1)
    cv2.putText(img, text, (int(10 * scale), int(31 * scale)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9 * scale, colour,
                max(1, int(2 * scale)), cv2.LINE_AA)


def singles_overlay(img, H, model_name, text):
    """Magenta: calibrated singles court. Orange dashed: extrapolated far half."""
    vis = img.copy()
    if H is not None:
        thick = max(2, round(img.shape[1] / 700))
        full = model_name == "full"
        _draw(vis, H, NEAR, CALIBRATED, thick)
        _draw(vis, H, FAR, CALIBRATED if full else EXTRAPOLATED, thick, dashed=not full)
        _draw(vis, H, NET_LINE, NET_COLOUR, thick, dashed=True)
    banner(vis, text, (255, 255, 255) if H is not None else (0, 0, 255))
    return vis


def ground_error(H_est, H_ref, shape):
    """Ground-position error (cm) over the court area visible in the photo.

    A 25 cm grid of court points is placed in the image with the reference
    homography; the calibration under test then maps those pixels back to the
    court, and the distance from the true point is the error.
    """
    h, w = shape[:2]
    xs = np.arange(0, CW + 1e-6, 0.25)
    out = {}
    for half, (y0, y1) in {"near": (NET, CL), "far": (0, NET)}.items():
        ys = np.arange(y0, y1 + 1e-6, 0.25)
        world = np.stack(np.meshgrid(xs, ys), -1).reshape(-1, 2)
        px = cv2.perspectiveTransform(world.reshape(-1, 1, 2), H_ref).reshape(-1, 2)
        vis = (px[:, 0] >= 0) & (px[:, 0] < w) & (px[:, 1] >= 0) & (px[:, 1] < h)
        if vis.mean() < 0.2:
            out[half] = None
            continue
        est = cv2.perspectiveTransform(
            px[vis].reshape(-1, 1, 2), np.linalg.inv(H_est)).reshape(-1, 2)
        err = np.linalg.norm(est - world[vis], axis=1) * 100
        out[half] = {"median_cm": float(np.median(err)),
                     "p95_cm": float(np.percentile(err, 95)),
                     "visible": float(vis.mean())}
    return out


def contact_sheet(paths, out_path, cols=3, tile_w=640):
    tiles = []
    for p in paths:
        im = cv2.imread(p)
        tiles.append(cv2.resize(im, (tile_w, int(im.shape[0] * tile_w / im.shape[1]))))
    th = max(t.shape[0] for t in tiles)
    tiles = [cv2.copyMakeBorder(t, 0, th - t.shape[0], 0, 0, cv2.BORDER_CONSTANT) for t in tiles]
    while len(tiles) % cols:
        tiles.append(np.zeros_like(tiles[0]))
    rows = [np.hstack(tiles[i:i + cols]) for i in range(0, len(tiles), cols)]
    cv2.imwrite(out_path, np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 88])
