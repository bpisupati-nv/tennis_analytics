"""Step-by-step visualisation of one automatic calibration, for explaining the method.

Replays CourtMapper.auto_calibrate with the current court.py and saves a panel
per step: paint mask, detected line families, candidate courts from poor to
best, then each refinement pass. Every court panel is labelled with its score
and its ground error against the reference. The replay is checked against the
real auto_calibrate result so the pictures cannot drift from the code.

Usage: pipeline_steps.py PHOTO [PHOTO ...]
Output: figures/pipeline/<photo>/NN_step.jpg and grid.jpg
"""
import json
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from common import (PHOTO_DIR, PROJECT_DIR, REPORT_DIR, banner, ground_error,  # noqa: E402
                    load_court, singles_overlay)

court = load_court(os.path.join(PROJECT_DIR, "court.py"))
REFS = json.load(open(os.path.join(REPORT_DIR, "references.json")))
CANDIDATE_RANKS = (100, 20, 5, 2)
DEMO_NUDGE = 2.5  # corner offset for the convergence demo, in scoring tolerances


def inset(panel, H_from, H_to, frame_shape):
    """Magnify the spot where the fit moves most between two transforms."""
    CW, CL = 10.97, 23.77
    xs = np.linspace(1.37, CW - 1.37, 40)
    world = np.concatenate([np.stack([xs, np.full_like(xs, CL)], 1),
                            np.stack([xs, np.full_like(xs, CL - 5.485)], 1),
                            np.stack([np.full(40, 1.37), np.linspace(CL / 2, CL, 40)], 1),
                            np.stack([np.full(40, CW - 1.37), np.linspace(CL / 2, CL, 40)], 1)])
    a = cv2.perspectiveTransform(world.reshape(-1, 1, 2), H_from).reshape(-1, 2)
    b = cv2.perspectiveTransform(world.reshape(-1, 1, 2), H_to).reshape(-1, 2)
    h, w = frame_shape[:2]
    ok = (b[:, 0] > 0.1 * w) & (b[:, 0] < 0.9 * w) & (b[:, 1] > 0.15 * h) & (b[:, 1] < 0.9 * h)
    if not ok.any():
        return panel
    moved = np.linalg.norm(a - b, axis=1)
    centre = b[ok][np.argmax(moved[ok])]
    half = int(0.07 * w)
    x0 = int(np.clip(centre[0] - half, 0, w - 2 * half))
    y0 = int(np.clip(centre[1] - half, 0, h - 2 * half))
    crop = panel[y0:y0 + 2 * half, x0:x0 + 2 * half]
    size = int(0.34 * w)
    zoom = cv2.resize(crop, (size, size), interpolation=cv2.INTER_CUBIC)
    border = max(3, w // 400)
    zoom = cv2.copyMakeBorder(zoom, border, border, border, border, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    cv2.rectangle(panel, (x0, y0), (x0 + 2 * half, y0 + 2 * half), (255, 255, 255), border)
    py = h - zoom.shape[0] - border * 4
    px = border * 4 if centre[0] > w / 2 else w - zoom.shape[1] - border * 4
    panel[py:py + zoom.shape[0], px:px + zoom.shape[1]] = zoom
    return panel


def draw_lines(img, lines, colour, scale, thick):
    h, w = img.shape[:2]
    for a, b, c, _ in lines:
        c = c / scale
        if abs(b) > abs(a):
            p, q = (0, -c / b), (w, -(a * w + c) / b)
        else:
            p, q = (-c / a, 0), (-(b * h + c) / a, h)
        cv2.line(img, tuple(np.int32(p)), tuple(np.int32(q)), colour, thick, cv2.LINE_AA)


def replay_refine(m, world_to_pixel, model, samples, distance_map, nearest, w, h, tolerance, score):
    """CourtMapper._refine, recording the transform after every accepted pass."""
    points, weights = samples
    best_transform, best_score = world_to_pixel, score
    passes = []
    for iteration in range(3):
        radius = tolerance * (3.0 - 0.75 * iteration)
        projected = cv2.perspectiveTransform(points.reshape(-1, 1, 2), best_transform).reshape(-1, 2)
        px = np.rint(projected[:, 0]).astype(int)
        py = np.rint(projected[:, 1]).astype(int)
        valid = (px >= 0) & (px < w) & (py >= 0) & (py < h)
        if valid.sum() < 30:
            break
        px, py = px[valid], py[valid]
        close = distance_map[py, px] <= radius
        if close.sum() < 30:
            break
        source = points[valid][close]
        target = nearest[py[close], px[close]]
        candidate, _ = cv2.findHomography(source, target, cv2.RANSAC, max(2.0, tolerance))
        if candidate is None:
            break
        outline = cv2.perspectiveTransform(model.quad.reshape(-1, 1, 2), candidate).reshape(-1, 2)
        if not m._valid_corners(outline, w, h):
            break
        candidate_score = m._score_projection(
            points, weights, candidate.astype(np.float32), distance_map, w, h, tolerance)
        if candidate_score is None or candidate_score <= best_score:
            break
        best_transform = candidate.astype(np.float32)
        best_score = candidate_score
        passes.append((best_transform, best_score, int(close.sum())))
    return passes


def run(photo):
    frame = cv2.imread(os.path.join(PHOTO_DIR, photo))
    m = court.CourtMapper()
    image, scale = m._working_image(frame)
    h, w = image.shape[:2]
    mask = m._line_mask(image)
    families = m._detect_lines(mask, w, h)
    distance_map, nearest = m._nearest_line_pixel(mask)
    samples = {mod.name: m._line_samples(mod.lines) for mod in court.COURT_MODELS}
    tolerance = max(2.5, w / 320.0)

    scored, seen = [], set()
    for family_index, (transverse, longitudinal) in enumerate(families):
        for corners in m._candidate_quads(transverse, longitudinal, w, h):
            key = tuple(np.rint(corners).astype(int).ravel())
            if key in seen:
                continue
            seen.add(key)
            for mod in court.COURT_MODELS:
                H = cv2.getPerspectiveTransform(mod.quad, corners)
                s = m._score_projection(*samples[mod.name], H, distance_map, w, h, tolerance)
                if s is not None:
                    scored.append((s * mod.preference, s, mod, corners, family_index))
    best_index = max(range(len(scored)), key=lambda i: scored[i][0])
    ranked = sorted(scored, key=lambda item: item[0])
    _, best_score, model, corners, family_index = scored[best_index]
    start = cv2.getPerspectiveTransform(model.quad, corners)
    passes = replay_refine(m, start, model, samples[model.name], distance_map, nearest,
                           w, h, tolerance, best_score)

    upscale = np.diag([1 / scale, 1 / scale, 1.0])
    check = court.CourtMapper()
    assert check.auto_calibrate(frame)
    final = passes[-1][0] if passes else start
    assert np.allclose(np.linalg.inv(check._H), upscale @ final, rtol=1e-4, atol=1e-3), \
        "replay diverged from auto_calibrate"

    ref = np.array(REFS[photo]["world_to_pixel"]) if photo in REFS else None
    thick = max(2, round(frame.shape[1] / 700))

    def court_panel(H_work, mod, title, score):
        H = upscale @ H_work
        text = f"{title} | score {score:.2f}"
        if ref is not None:
            err = ground_error(H, ref, frame.shape)["near"]
            text += (f" | near-half error {err['median_cm'] / 100:.1f} m" if err["median_cm"] >= 100
                     else f" | near-half error {err['median_cm']:.0f} cm")
        print("   ", text)
        return singles_overlay(frame, H, mod.name, text)

    panels = []
    vis = frame.copy()
    big_mask = cv2.resize(mask, (frame.shape[1], frame.shape[0]), interpolation=cv2.INTER_NEAREST)
    vis[big_mask > 0] = (0.35 * vis[big_mask > 0] + 0.65 * np.array([0, 255, 255])).astype(np.uint8)
    banner(vis, f"1. Paint mask: thin, bright, unsaturated pixels ({(mask > 0).mean():.0%} of frame)")
    panels.append(("paint_mask", vis))

    vis = (frame * 0.6).astype(np.uint8)
    transverse, longitudinal = families[family_index]
    draw_lines(vis, transverse, (0, 0, 255), scale, thick)
    draw_lines(vis, longitudinal, (0, 220, 0), scale, thick)
    kind = "angle split" if family_index == 0 else "vanishing-point grouping"
    banner(vis, f"2. Line families ({kind}): red = across court, green = along court")
    panels.append(("line_families", vis))

    total = len(ranked)
    for k, rank in enumerate(r for r in CANDIDATE_RANKS if r <= total):
        adjusted, s, mod, c, _ = ranked[total - rank]
        title = f"3.{k + 1} Candidate ranked #{rank} of {total}"
        panels.append((f"candidate_rank{rank}",
                       court_panel(cv2.getPerspectiveTransform(mod.quad, c), mod, title, s)))

    def zoomed(panel, H_work):
        return inset(panel, upscale @ start, upscale @ final, frame.shape) if passes else panel

    panels.append(("candidate_best", zoomed(
        court_panel(start, model, f"4. Best candidate #1 ({model.name} layout)", best_score), start)))
    for i, (H, s, used) in enumerate(passes):
        panels.append((f"refine_{i + 1}", zoomed(
            court_panel(H, model, f"5.{i + 1} Refinement pass {i + 1} ({used} matched points)", s), H)))

    # Demonstration: nudge the final fit's corners and let the same refinement
    # pull it back, so the snapping is visible at a scale larger than its
    # few-centimetre effect on a real run.
    rng = np.random.default_rng(7)
    final_corners = cv2.perspectiveTransform(model.quad.reshape(-1, 1, 2), final).reshape(-1, 2)
    offsets = rng.normal(size=(4, 2))
    offsets *= DEMO_NUDGE * tolerance / np.linalg.norm(offsets, axis=1, keepdims=True)
    nudged = cv2.getPerspectiveTransform(model.quad, (final_corners + offsets).astype(np.float32))
    nudged_score = m._score_projection(
        *samples[model.name], nudged, distance_map, w, h, tolerance) or 0.0
    demo = replay_refine(m, nudged, model, samples[model.name], distance_map, nearest,
                         w, h, tolerance, nudged_score)
    demo_final = demo[-1][0] if demo else nudged

    def demo_zoom(panel, H_work):
        return inset(panel, upscale @ nudged, upscale @ demo_final, frame.shape)

    panels.append(("demo_0_nudged", demo_zoom(court_panel(
        nudged, model, "Demo: fit nudged off the paint", nudged_score), nudged)))
    for i, (H, s, used) in enumerate(demo):
        panels.append((f"demo_{i + 1}", demo_zoom(court_panel(
            H, model, f"Demo: refinement pass {i + 1} ({used} matched points)", s), H)))

    out_dir = os.path.join(REPORT_DIR, "figures", "pipeline", os.path.splitext(photo)[0])
    os.makedirs(out_dir, exist_ok=True)
    for f in os.listdir(out_dir):
        os.remove(os.path.join(out_dir, f))
    paths = []
    for i, (name, img) in enumerate(panels):
        p = os.path.join(out_dir, f"{i:02d}_{name}.jpg")
        cv2.imwrite(p, img, [cv2.IMWRITE_JPEG_QUALITY, 90])
        paths.append(p)

    tile_w = 800
    tiles = [cv2.resize(img, (tile_w, int(img.shape[0] * tile_w / img.shape[1]))) for _, img in panels]
    while len(tiles) % 3:
        tiles.append(np.full_like(tiles[0], 255))
    rows = [np.hstack(tiles[i:i + 3]) for i in range(0, len(tiles), 3)]
    cv2.imwrite(os.path.join(out_dir, "grid.jpg"), np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 85])
    print(f"{photo}: {len(panels)} panels, {total} candidates, {len(passes)} refinement passes -> {out_dir}")


if __name__ == "__main__":
    for p in sys.argv[1:]:
        run(p)
