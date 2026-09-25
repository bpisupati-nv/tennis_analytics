"""Synthetic test samples with exact ground truth, made from approved references.

Each sample re-images an approved photo through a random perspective warp:
four points inside the photo are mapped to the corners of the output, which
acts like a camera moved, tilted and zoomed in, with no empty borders. The
court is planar, so its ground truth is the warp composed with the approved
reference: exact by construction, with no fitting or human judgement.
Lighting, blur, noise and JPEG quality are varied on top.

Usage: synth.py [--per-photo N] [--seed S]
Output: dataset/synthetic/*.jpg and dataset/synthetic/manifest.json
"""
import argparse
import json
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from common import CL, CW, NET, PHOTO_DIR, REPORT_DIR  # noqa: E402

OUT_DIR = os.path.join(REPORT_DIR, "dataset", "synthetic")
MAX_INSET = 0.2        # of width/height, per output corner
MIN_NEAR_VISIBLE = 0.6  # of the near half's area, else resample


def near_visible(H, w, h):
    xs, ys = np.meshgrid(np.linspace(0, CW, 23), np.linspace(NET, CL, 25))
    world = np.stack([xs.ravel(), ys.ravel()], 1)
    px = cv2.perspectiveTransform(world.reshape(-1, 1, 2), H).reshape(-1, 2)
    return ((px[:, 0] >= 0) & (px[:, 0] < w) & (px[:, 1] >= 0) & (px[:, 1] < h)).mean()


def photometric(img, rng):
    out = img.astype(np.float32)
    out = out * rng.uniform(0.8, 1.2) + rng.uniform(-20, 20)       # contrast, brightness
    out = out * rng.uniform(0.92, 1.08, size=3)                      # white balance
    out = np.clip(out, 0, 255).astype(np.uint8)
    sigma = rng.uniform(0, 1.2)
    if sigma > 0.3:
        out = cv2.GaussianBlur(out, (0, 0), sigma)
    noise = rng.normal(0, rng.uniform(0, 5), out.shape)
    out = np.clip(out + noise, 0, 255).astype(np.uint8)
    quality = int(rng.integers(55, 95))
    ok, buf = cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return cv2.imdecode(buf, cv2.IMREAD_COLOR), {"blur_sigma": float(sigma), "jpeg_quality": quality}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-photo", type=int, default=8)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    rng = np.random.default_rng(args.seed)
    refs = json.load(open(os.path.join(REPORT_DIR, "references.json")))
    os.makedirs(OUT_DIR, exist_ok=True)
    for f in os.listdir(OUT_DIR):
        os.remove(os.path.join(OUT_DIR, f))

    manifest = []
    for photo, ref in refs.items():
        img = cv2.imread(os.path.join(PHOTO_DIR, photo))
        h, w = img.shape[:2]
        H_ref = np.array(ref["world_to_pixel"])
        made = 0
        while made < args.per_photo:
            inset = rng.uniform(0, MAX_INSET, size=(4, 2)) * [w, h]
            src = (np.float32([[0, 0], [w, 0], [w, h], [0, h]])
                   + inset * [[1, 1], [-1, 1], [-1, -1], [1, -1]]).astype(np.float32)
            dst = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
            warp = cv2.getPerspectiveTransform(src, dst).astype(np.float64)
            H = warp @ H_ref
            if near_visible(H, w, h) < MIN_NEAR_VISIBLE:
                continue
            out = cv2.warpPerspective(img, warp, (w, h), flags=cv2.INTER_LINEAR)
            out, photo_params = photometric(out, rng)
            name = f"{os.path.splitext(photo)[0]}_w{made:02d}.jpg"
            cv2.imwrite(os.path.join(OUT_DIR, name), out, [cv2.IMWRITE_JPEG_QUALITY, 95])
            manifest.append({
                "file": os.path.join("dataset", "synthetic", name),
                "base_photo": photo,
                "source": "synthetic warp of approved reference",
                "world_to_pixel": H.tolist(),
                "warp": warp.tolist(),
                **photo_params,
            })
            made += 1
    json.dump(manifest, open(os.path.join(OUT_DIR, "manifest.json"), "w"), indent=1)
    print(f"{len(manifest)} synthetic samples -> {OUT_DIR}")


if __name__ == "__main__":
    main()
