"""Recreate court.py as it was at each stage of the Delhi work, from the current file.

No version control exists for court.py, so each earlier stage is produced by
undoing the later edits textually. Every replacement must match exactly once.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from common import REPORT_DIR, PHOTO_DIR  # noqa: E402


def sub(text, old, new):
    assert text.count(old) == 1, f"expected one match for:\n{old}"
    return text.replace(old, new)


GUARD = """            # A free homography can collapse the whole layout onto one patch
            # of paint and still score well, so hold it to the same outline
            # checks as the starting quads.
            outline = cv2.perspectiveTransform(
                model.quad.reshape(-1, 1, 2), candidate
            ).reshape(-1, 2)
            if not self._valid_corners(outline, w, h):
                break

"""

FALLBACK_DETECT = """        # Ambiguous lines only take slots left over by unambiguous ones: they
        # are often long sidelines that would otherwise crowd out a genuine,
        # shorter transverse line such as a service line.
        return (
            self._deduplicate_lines(
                transverse, 14, [line for line, _ in ambiguous]
            ),
            self._deduplicate_lines(
                longitudinal, 14, [line for line, tall in ambiguous if tall]
            ),
        )"""
NAIVE_DETECT = """        for line, tall in ambiguous:
            transverse.append(line)
            if tall:
                longitudinal.append(line)
        return (
            self._deduplicate_lines(transverse, 14),
            self._deduplicate_lines(longitudinal, 14),
        )"""

FALLBACK_DEDUP = '''    def _deduplicate_lines(lines, max_count, fallback=()):
        """Longest distinct lines first; ``fallback`` lines fill any room left."""
        unique = []
        ordered = (
            sorted(lines, key=lambda item: item[3], reverse=True)
            + sorted(fallback, key=lambda item: item[3], reverse=True)
        )
        for line in ordered:
            if len(unique) == max_count:
                break'''
PLAIN_DEDUP = '''    def _deduplicate_lines(lines, max_count):
        unique = []
        for line in sorted(lines, key=lambda item: item[3], reverse=True):
            if len(unique) == max_count:
                break'''

BAND_CLASSIFY = """            if horizontal_deviation < AMBIGUOUS_ANGLE[0]:
                transverse.append(line)
            elif horizontal_deviation <= AMBIGUOUS_ANGLE[1]:
                ambiguous.append((line, abs(dy) >= h * 0.055))
            elif abs(dy) >= h * 0.055:"""
CUTOFF_CLASSIFY = """            if horizontal_deviation < 32:
                transverse.append(line)
            elif abs(dy) >= h * 0.055:"""

SINGLE_REFINE = """        _, score, model, corners = best
        world_to_pixel = cv2.getPerspectiveTransform(model.quad, corners)
        world_to_pixel, score = self._refine(
            world_to_pixel, model, samples[model.name], distance_map,
            nearest, w, h, tolerance, score,
        )
"""
TOPK_REFINE = """        ranked.sort(key=lambda item: item[0], reverse=True)
        best = None
        for _, score, model, corners in ranked[:8]:
            world_to_pixel = cv2.getPerspectiveTransform(model.quad, corners)
            world_to_pixel, score = self._refine(
                world_to_pixel, model, samples[model.name], distance_map,
                nearest, w, h, tolerance, score,
            )
            if best is None or score * model.preference > best[0]:
                best = (score * model.preference, score, model, world_to_pixel)
        _, score, model, world_to_pixel = best
"""


def main():
    current = open(os.path.join(PHOTO_DIR, "court.py")).read()
    no_guard = sub(current, GUARD, "")
    naive_band = sub(sub(no_guard, FALLBACK_DETECT, NAIVE_DETECT), FALLBACK_DEDUP, PLAIN_DEDUP)
    baseline = sub(naive_band, BAND_CLASSIFY, CUTOFF_CLASSIFY)
    topk = sub(naive_band, SINGLE_REFINE, TOPK_REFINE)
    topk = sub(topk, "                if best is None or adjusted > best[0]:\n"
                     "                    best = (adjusted, score, model, corners)\n",
               "                ranked.append((adjusted, score, model, corners))\n")
    topk = sub(topk, "        best = None  # (adjusted_score, raw_score, model, corners)\n",
               "        ranked = []  # (adjusted_score, raw_score, model, corners)\n")
    topk = sub(topk, "        if best is None or best[1] < MIN_ACCEPTABLE_SCORE:\n            return False\n\n",
               "        ranked = [r for r in ranked if r[1] >= MIN_ACCEPTABLE_SCORE]\n"
               "        if not ranked:\n            return False\n\n")

    stages = {
        "00_baseline": baseline,
        "01_ambiguous_angle_band": naive_band,
        "02_x_refine_top8": topk,
        "03_band_lines_fill_leftover_slots": no_guard,
        "04_refine_outline_guard": current,
    }
    for name, text in stages.items():
        d = os.path.join(REPORT_DIR, "stages", name)
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, "court.py"), "w").write(text)
        print("wrote", name)


if __name__ == "__main__":
    main()
