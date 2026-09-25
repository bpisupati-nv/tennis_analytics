"""Run one court.py snapshot on every test photo and record overlays and errors.

Usage: run_stage.py STAGE_DIR [STAGE_DIR ...]
Each STAGE_DIR holds a court.py; results go next to it:
  overlays/<photo>_singles.jpg, sheet.jpg, metrics.json
"""
import json
import os
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from common import (PHOTOS, PHOTO_DIR, REPORT_DIR, contact_sheet,  # noqa: E402
                    ground_error, load_court, singles_overlay)


def fmt(e):
    return "  n/a " if e is None else f"{e['median_cm']:5.1f}/{e['p95_cm']:6.1f}"


def run(stage_dir):
    court = load_court(os.path.join(stage_dir, "court.py"))
    refs = json.load(open(os.path.join(REPORT_DIR, "references.json")))
    os.makedirs(os.path.join(stage_dir, "overlays"), exist_ok=True)
    metrics, sheet = {}, []
    print(f"== {os.path.basename(stage_dir)}   ground error cm (median/p95)")
    for name, title in PHOTOS:
        img = cv2.imread(os.path.join(PHOTO_DIR, name))
        mapper = court.CourtMapper()
        start = time.perf_counter()
        ok = mapper.auto_calibrate(img)
        elapsed = time.perf_counter() - start
        H = np.linalg.inv(mapper._H) if ok else None
        err = None
        if ok and name in refs:
            err = ground_error(H, np.array(refs[name]["world_to_pixel"]), img.shape)
        text = (f"{title}: {mapper.model_name} score {mapper.auto_score:.2f}"
                if ok else f"{title}: NOT CALIBRATED")
        if err and err["near"]:
            text += f" | near-half err {err['near']['median_cm']:.0f} cm"
        out = os.path.join(stage_dir, "overlays", os.path.splitext(name)[0] + "_singles.jpg")
        cv2.imwrite(out, singles_overlay(img, H, mapper.model_name, text),
                    [cv2.IMWRITE_JPEG_QUALITY, 90])
        sheet.append(out)
        metrics[name] = {
            "calibrated": ok, "model": mapper.model_name,
            "score": mapper.auto_score, "seconds": elapsed,
            "error": err, "world_to_pixel": H.tolist() if ok else None,
        }
        near = err["near"] if err else None
        far = err["far"] if err else None
        print(f"  {name:36s} {str(mapper.model_name):5s} "
              f"{(mapper.auto_score or 0):.3f}  near {fmt(near)}  far {fmt(far)}  {elapsed:.2f}s")
    json.dump(metrics, open(os.path.join(stage_dir, "metrics.json"), "w"), indent=1)
    contact_sheet(sheet, os.path.join(stage_dir, "sheet.jpg"))


if __name__ == "__main__":
    for d in sys.argv[1:]:
        run(os.path.abspath(d))
