"""Summarise every stage's metrics.json into markdown tables and build figures."""
import json
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from common import PHOTOS, REPORT_DIR  # noqa: E402

WRONG_CM = 50.0
SHORT = {
    "court.png": "Broadcast", "court_wimbledon_no1_grass.jpg": "Wimbledon",
    "court_delhi_centre_hard.jpg": "Delhi", "court_arthur_ashe_hard.jpg": "Arthur Ashe",
    "court_naples_universiade_clay.jpg": "Naples", "court_hanoi_times_city_hard.jpg": "Hanoi",
    "court_val_doingt_hard.jpg": "Val-d'Oingt",
}


def cell(m, half="near"):
    if not m["calibrated"]:
        return "refused"
    e = m["error"]
    if e is None or e.get(half) is None:
        return "wrong fit*" if m.get("visually_wrong") else "calibrated, no ref"
    med = e[half]["median_cm"]
    if e["near"]["median_cm"] > WRONG_CM:
        return f"**wrong** ({med / 100:.1f} m)" if med < 1000 else f"**wrong** ({med / 100:.0f} m)"
    return f"{med:.0f} / {e[half]['p95_cm']:.0f}"


def stage_table(stages, meta):
    head = "| Stage | Kept | " + " | ".join(SHORT[p] for p, _ in PHOTOS) + " |"
    rows = [head, "|" + "---|" * (len(PHOTOS) + 2)]
    for name in stages:
        metrics = json.load(open(os.path.join(REPORT_DIR, "stages", name, "metrics.json")))
        for p, m in metrics.items():
            if p == "court_val_doingt_hard.jpg" and m["calibrated"]:
                m["visually_wrong"] = True
        rows.append(f"| {name[:2]} {meta[name]['title']} | {'yes' if meta[name]['kept'] else 'no'} | "
                    + " | ".join(cell(metrics[p]) for p, _ in PHOTOS) + " |")
    return "\n".join(rows)


def before_after(first, last):
    a = json.load(open(os.path.join(REPORT_DIR, "stages", first, "metrics.json")))
    b = json.load(open(os.path.join(REPORT_DIR, "stages", last, "metrics.json")))
    rows = ["| Photo | Before: near half | After: near half | Before: far half | After: far half |",
            "|---|---|---|---|---|"]
    for p, _ in PHOTOS:
        for m in (a[p], b[p]):
            if p == "court_val_doingt_hard.jpg" and m["calibrated"]:
                m["visually_wrong"] = True
        rows.append(f"| {SHORT[p]} | {cell(a[p])} | {cell(b[p])} | {cell(a[p], 'far')} | {cell(b[p], 'far')} |")
    return "\n".join(rows)


def captioned(path, caption, height=420):
    im = cv2.imread(path)
    im = cv2.resize(im, (int(im.shape[1] * height / im.shape[0]), height))
    bar = np.full((44, im.shape[1], 3), 255, np.uint8)
    cv2.putText(bar, caption, (8, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 0, 0), 2, cv2.LINE_AA)
    return np.vstack([bar, im])


def side_by_side(panels, out):
    tiles = [captioned(p, c) for p, c in panels]
    gap = np.full((tiles[0].shape[0], 12, 3), 255, np.uint8)
    row = tiles[0]
    for t in tiles[1:]:
        row = np.hstack([row, gap, t])
    cv2.imwrite(out, row, [cv2.IMWRITE_JPEG_QUALITY, 85])


def figures():
    fig = os.path.join(REPORT_DIR, "figures")
    os.makedirs(fig, exist_ok=True)

    def ov(stage, photo):
        return os.path.join(REPORT_DIR, "stages", stage, "overlays",
                            os.path.splitext(photo)[0] + "_singles.jpg")

    d, h, w, v = ("court_delhi_centre_hard.jpg", "court_hanoi_times_city_hard.jpg",
                  "court_wimbledon_no1_grass.jpg", "court_val_doingt_hard.jpg")
    side_by_side([(ov("00_baseline", d), "Stage 00: singles lines fitted as doubles"),
                  (ov("01_ambiguous_angle_band", d), "Stage 01: correct court")],
                 os.path.join(fig, "delhi_before_after.jpg"))
    side_by_side([(ov("00_baseline", h), "Stage 00: wrong court"),
                  (ov("05_score_partially_visible_courts", h), "Stage 05: still wrong"),
                  (ov("06_vanishing_point_line_families", h), "Stage 06: correct court")],
                 os.path.join(fig, "hanoi_progression.jpg"))
    side_by_side([(ov("02_x_refine_top8", w), "Stage 02: refinement collapsed"),
                  (ov("04_refine_outline_guard", w), "Stage 04: guarded refinement")],
                 os.path.join(fig, "wimbledon_collapse.jpg"))
    side_by_side([(ov("06_vanishing_point_line_families", v), "Stage 05-07: confident wrong fit"),
                  (ov("08_stricter_bar_for_partial_views", v), "Stage 08: refused again")],
                 os.path.join(fig, "val_doingt_guard.jpg"))
    for stage in ("00_baseline", "08_stricter_bar_for_partial_views"):
        src = cv2.imread(os.path.join(REPORT_DIR, "stages", stage, "sheet.jpg"))
        cv2.imwrite(os.path.join(fig, f"sheet_{stage[:2]}.jpg"),
                    cv2.resize(src, None, fx=0.75, fy=0.75), [cv2.IMWRITE_JPEG_QUALITY, 85])
    src = cv2.imread(os.path.join(REPORT_DIR, "references", "sheet.jpg"))
    cv2.imwrite(os.path.join(fig, "references.jpg"),
                cv2.resize(src, None, fx=0.75, fy=0.75), [cv2.IMWRITE_JPEG_QUALITY, 85])


def main():
    meta = json.load(open(os.path.join(REPORT_DIR, "stages.json")))
    stages = sorted(meta)
    with open(os.path.join(REPORT_DIR, "tables.md"), "w") as f:
        f.write("## Near-half ground error per stage (median / 95th percentile, cm)\n\n")
        f.write(stage_table(stages, meta) + "\n\n")
        f.write("## Baseline vs final\n\n")
        f.write(before_after(stages[0], stages[-1]) + "\n")
    figures()
    print(open(os.path.join(REPORT_DIR, "tables.md")).read())


if __name__ == "__main__":
    main()
