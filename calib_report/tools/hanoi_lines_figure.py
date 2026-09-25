"""Figure: Hanoi line families from the angle split vs. from vanishing points."""
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from common import PHOTO_DIR, REPORT_DIR, load_court  # noqa: E402

court = load_court(os.path.join(REPORT_DIR, "stages", "08_stricter_bar_for_partial_views", "court.py"))
img = cv2.imread(os.path.join(PHOTO_DIR, "court_hanoi_times_city_hard.jpg"))
m = court.CourtMapper()
work, _ = m._working_image(img)
h, w = work.shape[:2]
mask = m._line_mask(work)
families = m._detect_lines(mask, w, h)
dist, _ = m._nearest_line_pixel(mask)
samples = {mod.name: m._line_samples(mod.lines) for mod in court.COURT_MODELS}
tol = max(2.5, w / 320)


def best_score(t, l):
    best = 0.0
    for corners in m._candidate_quads(t, l, w, h):
        for mod in court.COURT_MODELS:
            s = m._score_projection(*samples[mod.name], cv2.getPerspectiveTransform(mod.quad, corners), dist, w, h, tol)
            if s is not None:
                best = max(best, s * mod.preference)
    return best


scores = [best_score(t, l) for t, l in families]
winner = int(np.argmax(scores))


def draw(t, l, title):
    vis = (cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR) // 3 + work // 2)
    for lines, colour in ((t, (0, 0, 255)), (l, (0, 220, 0))):
        for a, b, c, _ in lines:
            if abs(b) > abs(a):
                p, q = (0, -c / b), (w, -(a * w + c) / b)
            else:
                p, q = (-c / a, 0), (-(b * h + c) / a, h)
            cv2.line(vis, tuple(np.int32(p)), tuple(np.int32(q)), colour, 2, cv2.LINE_AA)
    bar = np.full((44, w, 3), 255, np.uint8)
    cv2.putText(bar, title, (8, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 0, 0), 2, cv2.LINE_AA)
    return np.vstack([bar, vis])


left = draw(*families[0], f"Angle split: best candidate {scores[0]:.2f}")
right = draw(*families[winner], f"Vanishing-point families: best candidate {scores[winner]:.2f}")
out = np.hstack([left, np.full((left.shape[0], 12, 3), 255, np.uint8), right])
cv2.imwrite(os.path.join(REPORT_DIR, "figures", "hanoi_line_families.jpg"), cv2.resize(out, None, fx=0.6, fy=0.6), [cv2.IMWRITE_JPEG_QUALITY, 85])
print("families", len(families), "scores", np.round(scores, 3), "winner", winner)
