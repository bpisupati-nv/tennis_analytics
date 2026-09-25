"""Animated GIFs and a methodology strip from figures/pipeline/<photo>/ panels.

Runs with any Python that has Pillow (the OpenCV venv does not).
"""
import os
import sys

from PIL import Image

here = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "figures", "pipeline")


def gif(frames, out, width=960, ms=1300, hold=3000):
    imgs = [Image.open(f).convert("RGB") for f in frames]
    imgs = [im.resize((width, int(im.height * width / im.width)), Image.LANCZOS) for im in imgs]
    durations = [ms] * (len(imgs) - 1) + [hold]
    imgs[0].save(out, save_all=True, append_images=imgs[1:], duration=durations, loop=0, optimize=True)


def strip(frames, out, width=700):
    imgs = [Image.open(f).convert("RGB") for f in frames]
    imgs = [im.resize((width, int(im.height * width / im.width)), Image.LANCZOS) for im in imgs]
    h = max(im.height for im in imgs)
    canvas = Image.new("RGB", (width * len(imgs) + 12 * (len(imgs) - 1), h), "white")
    for i, im in enumerate(imgs):
        canvas.paste(im, (i * (width + 12), 0))
    canvas.save(out, quality=85)


for photo in sys.argv[1:]:
    d = os.path.join(here, photo)
    files = sorted(f for f in os.listdir(d) if f[:2].isdigit())
    path = lambda f: os.path.join(d, f)  # noqa: E731
    search = [path(f) for f in files if not f.split("_", 1)[1].startswith("demo")]
    demo = [path(f) for f in files if f.split("_", 1)[1].startswith("demo")]
    gif(search, os.path.join(d, "pipeline.gif"))
    if demo:
        gif(demo, os.path.join(d, "refinement_demo.gif"))
    key = [f for f in files if any(k in f for k in ("paint_mask", "line_families", "rank20", "candidate_best"))]
    refine = [f for f in files if "refine_" in f]
    strip([path(f) for f in key + refine[-1:]], os.path.join(d, "strip.jpg"))
    print(photo, "->", sorted(f for f in os.listdir(d) if not f[:2].isdigit()))
