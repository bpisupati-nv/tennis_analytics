"""
Court mapper: detect court markings (or accept four manual corners) and compute
a homography to real-world tennis court coordinates in meters.

Standard court dimensions (doubles):
  Width:  10.97 m
  Length: 23.77 m

Automatic calibration understands two camera framings:

  * ``full``  — both baselines in view, e.g. an elevated side or corner camera.
  * ``half``  — net to near baseline only, as produced by a camera sitting
                behind one baseline. Distances remain correct because a
                homography extrapolates beyond its reference quad, but the far
                half is estimated rather than measured.

World coordinates are meters with the origin at the far-left doubles corner,
x across the court and y along its length.
"""

from __future__ import annotations

from itertools import combinations
from typing import NamedTuple

import cv2
import numpy as np


# Doubles court dimensions in meters
COURT_WIDTH = 10.97
COURT_LENGTH = 23.77
SINGLES_INSET = 1.37
SERVICE_LINE_Y = 5.485
NET_Y = COURT_LENGTH / 2

# World-space corners [TL, TR, BR, BL] in meters
WORLD_POINTS = np.float32([
    [0.0, 0.0],
    [COURT_WIDTH, 0.0],
    [COURT_WIDTH, COURT_LENGTH],
    [0.0, COURT_LENGTH],
])

# Painted court markings used to score automatic calibration candidates.
# The net is deliberately omitted because it is not a painted ground line.
COURT_LINES = [
    ((0.0, 0.0), (COURT_WIDTH, 0.0), 0.6),
    ((COURT_WIDTH, 0.0), (COURT_WIDTH, COURT_LENGTH), 0.6),
    ((COURT_WIDTH, COURT_LENGTH), (0.0, COURT_LENGTH), 0.6),
    ((0.0, COURT_LENGTH), (0.0, 0.0), 0.6),
    ((SINGLES_INSET, 0.0), (SINGLES_INSET, COURT_LENGTH), 1.0),
    ((COURT_WIDTH - SINGLES_INSET, 0.0),
     (COURT_WIDTH - SINGLES_INSET, COURT_LENGTH), 1.0),
    ((SINGLES_INSET, SERVICE_LINE_Y),
     (COURT_WIDTH - SINGLES_INSET, SERVICE_LINE_Y), 1.25),
    ((SINGLES_INSET, COURT_LENGTH - SERVICE_LINE_Y),
     (COURT_WIDTH - SINGLES_INSET, COURT_LENGTH - SERVICE_LINE_Y), 1.25),
    ((COURT_WIDTH / 2, SERVICE_LINE_Y),
     (COURT_WIDTH / 2, COURT_LENGTH - SERVICE_LINE_Y), 1.0),
]

# Markings of the near half only. The service line and centre service line
# carry extra weight: they are what distinguishes a true half-court fit from
# one that mistakes the service line for a baseline.
HALF_COURT_LINES = [
    ((0.0, COURT_LENGTH), (COURT_WIDTH, COURT_LENGTH), 0.6),
    ((0.0, NET_Y), (0.0, COURT_LENGTH), 0.6),
    ((COURT_WIDTH, NET_Y), (COURT_WIDTH, COURT_LENGTH), 0.6),
    ((SINGLES_INSET, NET_Y), (SINGLES_INSET, COURT_LENGTH), 1.0),
    ((COURT_WIDTH - SINGLES_INSET, NET_Y),
     (COURT_WIDTH - SINGLES_INSET, COURT_LENGTH), 1.0),
    ((SINGLES_INSET, COURT_LENGTH - SERVICE_LINE_Y),
     (COURT_WIDTH - SINGLES_INSET, COURT_LENGTH - SERVICE_LINE_Y), 1.5),
    ((COURT_WIDTH / 2, NET_Y),
     (COURT_WIDTH / 2, COURT_LENGTH - SERVICE_LINE_Y), 1.25),
]

HALF_WORLD_POINTS = np.float32([
    [0.0, NET_Y],
    [COURT_WIDTH, NET_Y],
    [COURT_WIDTH, COURT_LENGTH],
    [0.0, COURT_LENGTH],
])

# Service line to baseline. The service line is painted on the ground, so a
# quad anchored on it carries none of the net's height bias, at the cost of a
# shallower reference span. Its top corners are where the service line
# produced to the doubles sidelines meets them.
NEAR_WORLD_POINTS = np.float32([
    [0.0, COURT_LENGTH - SERVICE_LINE_Y],
    [COURT_WIDTH, COURT_LENGTH - SERVICE_LINE_Y],
    [COURT_WIDTH, COURT_LENGTH],
    [0.0, COURT_LENGTH],
])


class CourtModel(NamedTuple):
    """A candidate court layout that a detected quadrilateral may represent."""

    name: str
    quad: np.ndarray          # world corners matching the detected quad order
    lines: list               # [(start, end, weight)] scored against the image
    preference: float         # ranking bonus when two models fit equally well


# A full-court fit is preferred on near-ties: its reference quad spans the
# whole playing area, so player positions are interpolated rather than
# extrapolated. A half-court model must fit clearly better to win. Between the
# two half-court layouts, ``near`` edges out ``half`` because every corner of
# its quad sits on paint, whereas ``half`` borrows the net for its far edge.
COURT_MODELS = (
    CourtModel("full", WORLD_POINTS, COURT_LINES, 1.0),
    CourtModel("near", NEAR_WORLD_POINTS, HALF_COURT_LINES, 0.93),
    CourtModel("half", HALF_WORLD_POINTS, HALF_COURT_LINES, 0.92),
)

MIN_ACCEPTABLE_SCORE = 0.30

# Degrees from horizontal. From an off-centre camera a doubles sideline can
# lie flatter than 32 degrees, while baselines seen from a corner can be steeper,
# so no single cutoff separates the two. Segments inside this band are offered
# as both transverse and longitudinal, and whole-layout scoring picks the role.
AMBIGUOUS_ANGLE = (24.0, 40.0)

# Court paint covers a few percent of a frame. When far more of it passes the
# brightness test the image is washed out or heavily degraded, every candidate
# lands near some bright pixel, and the score stops discriminating between
# layouts. Refuse to calibrate rather than return a confident wrong answer.
MAX_MASK_DENSITY = 0.35


class CourtMapper:
    """Maps pixel coordinates to real-world court coordinates via homography."""

    def __init__(self):
        self._H = None
        self._pixel_corners = []
        self._auto_score = None
        self._model = None

    # ── Automatic calibration ──────────────────────────────────────────────

    def auto_calibrate(
        self,
        frame: np.ndarray,
        debug_path: str | None = None,
    ) -> bool:
        """
        Detect painted court lines and recover the court homography.

        Candidate quadrilaterals are built from pairs of transverse and
        longitudinal Hough lines. Each candidate is scored against every known
        court layout by projecting that layout's full set of markings and
        measuring their overlap with bright, low-saturation pixels. Scoring the
        complete layout, rather than only the quad outline, is what stops a
        service box or a single half from being mistaken for the full court.
        """
        if frame is None or frame.size == 0:
            return False

        image, scale = self._working_image(frame)
        h, w = image.shape[:2]

        mask = self._line_mask(image)
        if np.count_nonzero(mask) > MAX_MASK_DENSITY * mask.size:
            return False

        transverse, longitudinal = self._detect_lines(mask, w, h)
        if len(transverse) < 2 or len(longitudinal) < 2:
            return False

        distance_map, nearest = self._nearest_line_pixel(mask)
        samples = {
            model.name: self._line_samples(model.lines)
            for model in COURT_MODELS
        }
        tolerance = max(2.5, w / 320.0)

        best = None  # (adjusted_score, raw_score, model, corners)
        for corners in self._candidate_quads(transverse, longitudinal, w, h):
            for model in COURT_MODELS:
                world_to_pixel = cv2.getPerspectiveTransform(
                    model.quad, corners
                )
                points, weights = samples[model.name]
                score = self._score_projection(
                    points, weights, world_to_pixel, distance_map,
                    w, h, tolerance,
                )
                if score is None:
                    continue
                adjusted = score * model.preference
                if best is None or adjusted > best[0]:
                    best = (adjusted, score, model, corners)

        if best is None or best[1] < MIN_ACCEPTABLE_SCORE:
            return False

        _, score, model, corners = best
        world_to_pixel = cv2.getPerspectiveTransform(model.quad, corners)
        world_to_pixel, score = self._refine(
            world_to_pixel, model, samples[model.name], distance_map,
            nearest, w, h, tolerance, score,
        )

        # Undo the working-resolution downscale before storing the result.
        upscale = np.diag([1.0 / scale, 1.0 / scale, 1.0]).astype(np.float64)
        world_to_pixel = upscale @ world_to_pixel

        self._H = np.linalg.inv(world_to_pixel)
        self._model = model
        self._auto_score = score
        self._pixel_corners = [
            (float(x), float(y))
            for x, y in cv2.perspectiveTransform(
                model.quad.reshape(-1, 1, 2), world_to_pixel.astype(np.float32)
            ).reshape(-1, 2)
        ]
        if debug_path:
            self.save_debug_overlay(frame, debug_path)
        return True

    # ── Detection helpers ──────────────────────────────────────────────────

    @staticmethod
    def _working_image(frame: np.ndarray) -> tuple[np.ndarray, float]:
        scale = min(1.0, 960.0 / frame.shape[1])
        if scale < 1.0:
            return cv2.resize(
                frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA
            ), scale
        return frame.copy(), 1.0

    @staticmethod
    def _line_mask(image: np.ndarray) -> np.ndarray:
        """Thin, weakly saturated bright structures — court paint.

        Thresholding overall brightness is not enough at a real venue: a pale
        surround and banked seating are as bright as the paint and flood the
        mask, while paint on a dark surface is darker than both. A white
        top-hat responds only to structures narrower than its kernel, so broad
        bright regions drop out whatever their colour and the lines survive.
        """
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        # Kernel wider than any court line, so lines are kept and the regions
        # they are painted on are subtracted away.
        kernel_size = max(11, int(image.shape[1] * 0.022)) | 1
        tophat = cv2.morphologyEx(
            gray,
            cv2.MORPH_TOPHAT,
            cv2.getStructuringElement(
                cv2.MORPH_RECT, (kernel_size, kernel_size)
            ),
        )
        # Otsu adapts the contrast cutoff to indoor and outdoor courts.
        otsu_value, _ = cv2.threshold(
            tophat, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
        )
        saturation = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)[:, :, 1]
        mask = np.where(
            (tophat >= max(18, int(otsu_value))) & (saturation <= 120), 255, 0
        ).astype(np.uint8)
        mask = cv2.morphologyEx(
            mask,
            cv2.MORPH_CLOSE,
            cv2.getStructuringElement(cv2.MORPH_RECT, (5, 3)),
        )
        return CourtMapper._prune_speckle(
            mask, min_extent=max(12, int(image.shape[1] * 0.02))
        )

    @staticmethod
    def _prune_speckle(mask: np.ndarray, min_extent: int) -> np.ndarray:
        """Drop blobs too small to be a court line, so scoring stays honest."""
        count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
        if count <= 1:
            return mask
        extent = np.maximum(
            stats[:, cv2.CC_STAT_WIDTH], stats[:, cv2.CC_STAT_HEIGHT]
        )
        keep = (extent >= min_extent) & (stats[:, cv2.CC_STAT_AREA] >= 12)
        keep[0] = False  # background
        return np.where(keep[labels], 255, 0).astype(np.uint8)

    def _detect_lines(self, mask, w, h):
        segments = cv2.HoughLinesP(
            mask,
            1,
            np.pi / 360,
            threshold=max(35, int(w * 0.045)),
            minLineLength=max(35, int(w * 0.065)),
            maxLineGap=max(12, int(w * 0.025)),
        )
        if segments is None:
            return [], []

        transverse, longitudinal, ambiguous = [], [], []
        # OpenCV builds differ between (N, 1, 4) and (N, 4).
        for x1, y1, x2, y2 in segments.reshape(-1, 4).astype(float):
            dx, dy = x2 - x1, y2 - y1
            length = float(np.hypot(dx, dy))
            angle = abs(float(np.degrees(np.arctan2(dy, dx)))) % 180
            horizontal_deviation = min(angle, 180 - angle)
            line = self._line_from_points((x1, y1), (x2, y2), length)
            if horizontal_deviation < AMBIGUOUS_ANGLE[0]:
                transverse.append(line)
            elif horizontal_deviation <= AMBIGUOUS_ANGLE[1]:
                ambiguous.append((line, abs(dy) >= h * 0.055))
            elif abs(dy) >= h * 0.055:
                longitudinal.append(line)

        # Ambiguous lines only take slots left over by unambiguous ones: they
        # are often long sidelines that would otherwise crowd out a genuine,
        # shorter transverse line such as a service line.
        return (
            self._deduplicate_lines(
                transverse, 14, [line for line, _ in ambiguous]
            ),
            self._deduplicate_lines(
                longitudinal, 14, [line for line, tall in ambiguous if tall]
            ),
        )

    def _candidate_quads(self, transverse, longitudinal, w, h):
        """Yield plausible court outlines from every pair of line pairs."""
        for top_line, bottom_line in combinations(transverse, 2):
            if self._line_y(top_line, w / 2) > self._line_y(bottom_line, w / 2):
                top_line, bottom_line = bottom_line, top_line
            if (
                self._line_y(bottom_line, w / 2)
                - self._line_y(top_line, w / 2)
                < h * 0.16
            ):
                continue

            for left_line, right_line in combinations(longitudinal, 2):
                reference_y = h * 0.65
                if self._line_x(left_line, reference_y) > self._line_x(
                    right_line, reference_y
                ):
                    left_line, right_line = right_line, left_line
                if (
                    self._line_x(right_line, reference_y)
                    - self._line_x(left_line, reference_y)
                    < w * 0.14
                ):
                    continue

                corners = np.float32([
                    self._intersection(top_line, left_line),
                    self._intersection(top_line, right_line),
                    self._intersection(bottom_line, right_line),
                    self._intersection(bottom_line, left_line),
                ])
                if self._valid_corners(corners, w, h):
                    yield corners

    # ── Scoring and refinement ─────────────────────────────────────────────

    @staticmethod
    def _score_projection(
        points, weights, world_to_pixel, distance_map, w, h, tolerance,
    ) -> float | None:
        projected = cv2.perspectiveTransform(
            points.reshape(-1, 1, 2), world_to_pixel
        ).reshape(-1, 2)
        px = np.rint(projected[:, 0]).astype(int)
        py = np.rint(projected[:, 1]).astype(int)
        inside = (px >= 0) & (px < w) & (py >= 0) & (py < h)
        if inside.mean() < 0.97:
            return None
        np.clip(px, 0, w - 1, out=px)
        np.clip(py, 0, h - 1, out=py)
        closeness = np.exp(-np.square(distance_map[py, px] / tolerance))
        return float(np.average(closeness, weights=weights))

    def _refine(
        self, world_to_pixel, model, samples, distance_map, nearest,
        w, h, tolerance, score,
    ):
        """
        Snap the homography onto the detected paint.

        The initial fit comes from four line intersections, so any error in
        those two transverse lines propagates everywhere. Re-solving against
        every marking of the model spreads the residual across the whole court.
        For the half-court model this also removes the bias from using the
        raised net tape as the far edge, since the net is not a scored line.
        """
        points, weights = samples
        best_transform, best_score = world_to_pixel, score

        for iteration in range(3):
            radius = tolerance * (3.0 - 0.75 * iteration)
            projected = cv2.perspectiveTransform(
                points.reshape(-1, 1, 2), best_transform
            ).reshape(-1, 2)
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
            candidate, _ = cv2.findHomography(
                source, target, cv2.RANSAC, max(2.0, tolerance)
            )
            if candidate is None:
                break
            # A free homography can collapse the whole layout onto one patch
            # of paint and still score well, so hold it to the same outline
            # checks as the starting quads.
            outline = cv2.perspectiveTransform(
                model.quad.reshape(-1, 1, 2), candidate
            ).reshape(-1, 2)
            if not self._valid_corners(outline, w, h):
                break

            candidate_score = self._score_projection(
                points, weights, candidate.astype(np.float32),
                distance_map, w, h, tolerance,
            )
            if candidate_score is None or candidate_score <= best_score:
                break
            best_transform = candidate.astype(np.float32)
            best_score = candidate_score

        return best_transform, best_score

    @staticmethod
    def _nearest_line_pixel(mask):
        """Distance to the closest paint pixel, and where that pixel is."""
        inverse = cv2.bitwise_not(mask)
        distance_map, labels = cv2.distanceTransformWithLabels(
            inverse, cv2.DIST_L2, cv2.DIST_MASK_PRECISE,
            labelType=cv2.DIST_LABEL_PIXEL,
        )
        ys, xs = np.nonzero(mask)
        lookup = np.zeros((int(labels.max()) + 1, 2), np.float32)
        lookup[labels[ys, xs]] = np.stack([xs, ys], axis=1)
        return distance_map, lookup[labels]

    @staticmethod
    def _line_samples(lines):
        points, weights = [], []
        for start, end, weight in lines:
            count = 70
            x = np.linspace(start[0], end[0], count)
            y = np.linspace(start[1], end[1], count)
            points.extend(zip(x, y))
            weights.extend([weight] * count)
        return np.float32(points), np.float32(weights)

    # ── Line geometry ──────────────────────────────────────────────────────

    @staticmethod
    def _line_from_points(p1, p2, length):
        x1, y1 = p1
        x2, y2 = p2
        a, b = y1 - y2, x2 - x1
        norm = np.hypot(a, b)
        a, b = a / norm, b / norm
        c = -(a * x1 + b * y1)
        if a < 0 or (abs(a) < 1e-6 and b < 0):
            a, b, c = -a, -b, -c
        return (a, b, c, length)

    @staticmethod
    def _deduplicate_lines(lines, max_count, fallback=()):
        """Longest distinct lines first; ``fallback`` lines fill any room left."""
        unique = []
        ordered = (
            sorted(lines, key=lambda item: item[3], reverse=True)
            + sorted(fallback, key=lambda item: item[3], reverse=True)
        )
        for line in ordered:
            if len(unique) == max_count:
                break
            a, b, c, _ = line
            duplicate = any(
                abs(a * other[0] + b * other[1]) > np.cos(np.deg2rad(4))
                and abs(c - other[2]) < 12
                for other in unique
            )
            if not duplicate:
                unique.append(line)
        return unique

    @staticmethod
    def _intersection(line1, line2):
        a1, b1, c1, _ = line1
        a2, b2, c2, _ = line2
        determinant = a1 * b2 - a2 * b1
        if abs(determinant) < 1e-6:
            return (np.nan, np.nan)
        x = (b1 * c2 - b2 * c1) / determinant
        y = (c1 * a2 - c2 * a1) / determinant
        return (x, y)

    @staticmethod
    def _line_y(line, x):
        a, b, c, _ = line
        return -(a * x + c) / b if abs(b) > 1e-6 else np.inf

    @staticmethod
    def _line_x(line, y):
        a, b, c, _ = line
        return -(b * y + c) / a if abs(a) > 1e-6 else np.inf

    @staticmethod
    def _valid_corners(corners, width, height):
        if not np.isfinite(corners).all():
            return False
        margin_x, margin_y = width * 0.25, height * 0.25
        if (
            (corners[:, 0] < -margin_x).any()
            or (corners[:, 0] > width + margin_x).any()
            or (corners[:, 1] < -margin_y).any()
            or (corners[:, 1] > height + margin_y).any()
        ):
            return False
        contour = corners.reshape(-1, 1, 2)
        if not cv2.isContourConvex(contour):
            return False
        if cv2.contourArea(contour) < width * height * 0.055:
            return False
        top_width = np.linalg.norm(corners[1] - corners[0])
        bottom_width = np.linalg.norm(corners[2] - corners[3])
        if min(top_width, bottom_width) < width * 0.10:
            return False
        if not 0.45 < bottom_width / top_width < 5.0:
            return False
        return (
            corners[[0, 1], 1].mean() + height * 0.12
            < corners[[2, 3], 1].mean()
        )

    # ── Manual calibration ─────────────────────────────────────────────────

    def select_corners_interactive(self, frame: np.ndarray) -> None:
        """Open a window and let the user click the 4 court corners.

        Click order: top-left → top-right → bottom-right → bottom-left
        """
        self._pixel_corners = []
        clone = frame.copy()
        labels = ["Top-Left", "Top-Right", "Bottom-Right", "Bottom-Left"]

        instructions = "Click 4 court corners: TL -> TR -> BR -> BL. Press 'r' to reset."

        def mouse_cb(event, x, y, flags, param):
            if event == cv2.EVENT_LBUTTONDOWN and len(self._pixel_corners) < 4:
                self._pixel_corners.append((x, y))
                cv2.circle(clone, (x, y), 6, (0, 255, 0), -1)
                label = labels[len(self._pixel_corners) - 1]
                cv2.putText(clone, label, (x + 8, y - 8),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
                cv2.imshow("Select Court Corners", clone)

        cv2.namedWindow("Select Court Corners", cv2.WINDOW_NORMAL)
        cv2.imshow("Select Court Corners", clone)
        cv2.setMouseCallback("Select Court Corners", mouse_cb)

        cv2.putText(clone, instructions, (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)
        cv2.imshow("Select Court Corners", clone)

        while len(self._pixel_corners) < 4:
            key = cv2.waitKey(20) & 0xFF
            if key == ord('r'):
                self._pixel_corners = []
                clone = frame.copy()
                cv2.putText(clone, instructions, (10, 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)
                cv2.imshow("Select Court Corners", clone)
            elif key == 27:
                raise RuntimeError("Court selection cancelled.")

        cv2.destroyWindow("Select Court Corners")
        self._compute_homography()

    def set_corners(
        self,
        pixel_corners: list[tuple[int | float, int | float]],
        model: CourtModel | None = None,
    ) -> None:
        """Set corners programmatically (for testing or scripted use)."""
        assert len(pixel_corners) == 4
        self._pixel_corners = pixel_corners
        self._model = model or COURT_MODELS[0]
        self._compute_homography()

    def _compute_homography(self):
        src = np.float32(self._pixel_corners)
        model = self._model or COURT_MODELS[0]
        self._model = model
        self._H, _ = cv2.findHomography(src, model.quad)

    # ── Output ─────────────────────────────────────────────────────────────

    def to_world(self, pixel_pt: tuple[float, float]) -> tuple[float, float]:
        """Convert a pixel point to world coordinates (meters)."""
        p = np.float32([[pixel_pt]])
        world = cv2.perspectiveTransform(p, self._H)
        return float(world[0][0][0]), float(world[0][0][1])

    def save_debug_overlay(self, frame: np.ndarray, path: str) -> None:
        """Write the detected corners and projected court layout to an image."""
        if not self.ready:
            return
        overlay = frame.copy()
        model = self._model or COURT_MODELS[0]
        pixel_h = np.linalg.inv(self._H).astype(np.float32)
        for start, end, _ in model.lines:
            projected = cv2.perspectiveTransform(
                np.float32([[start, end]]), pixel_h
            )[0]
            p1, p2 = (tuple(np.rint(point).astype(int)) for point in projected)
            cv2.line(overlay, p1, p2, (0, 255, 0), 2, cv2.LINE_AA)
        for i, point in enumerate(self._pixel_corners):
            p = tuple(np.rint(point).astype(int))
            cv2.circle(overlay, p, 7, (0, 0, 255), -1)
            cv2.putText(
                overlay, str(i + 1), (p[0] + 8, p[1] - 8),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2,
            )
        cv2.imwrite(path, overlay)

    @property
    def ready(self) -> bool:
        return self._H is not None

    @property
    def auto_score(self) -> float | None:
        return self._auto_score

    @property
    def model_name(self) -> str | None:
        return self._model.name if self._model else None

    @property
    def ranking_score(self) -> float:
        """Score biased toward full-court fits, for comparing calibrations."""
        if self._auto_score is None or self._model is None:
            return -1.0
        return self._auto_score * self._model.preference
