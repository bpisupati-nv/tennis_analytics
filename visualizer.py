"""
Visualizer: draws tracking boxes, player IDs, and distance overlay onto frames.
"""

from __future__ import annotations

import cv2
import numpy as np

# Color palette per track ID (cycles)
_COLORS = [
    (0, 200, 255),   # yellow-ish
    (255, 80, 80),   # blue
    (80, 255, 80),   # green
    (255, 80, 255),  # magenta
    (80, 255, 255),  # cyan
]


def _color(track_id: int) -> tuple[int, int, int]:
    return _COLORS[track_id % len(_COLORS)]


def draw_detections(
    frame: np.ndarray,
    detections: list[dict],
    distances: dict[int, float],
    player_ids: set[int] | None = None,
) -> np.ndarray:
    """
    Draw bounding boxes and distance labels on frame.
    If player_ids is set, only annotate those track IDs.
    """
    out = frame.copy()
    for det in detections:
        tid = det["track_id"]
        if player_ids is not None and tid not in player_ids:
            continue
        x1, y1, x2, y2 = (int(v) for v in det["bbox"])
        color = _color(tid)
        cv2.rectangle(out, (x1, y1), (x2, y2), color, 2)

        dist = distances.get(tid, 0.0)
        label = f"P{tid}  {dist:.1f}m"
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.65, 2)
        cv2.rectangle(out, (x1, y1 - th - 8), (x1 + tw + 4, y1), color, -1)
        cv2.putText(out, label, (x1 + 2, y1 - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 0), 2)
    return out


def draw_scoreboard(
    frame: np.ndarray,
    distances: dict[int, float],
    player_ids: set[int] | None = None,
    elapsed_sec: float = 0.0,
) -> np.ndarray:
    """
    Draw a semi-transparent summary panel in the top-right corner.
    """
    out = frame.copy()
    h, w = out.shape[:2]

    panel_w, panel_h = 260, 30 + 28 * max(len(distances), 1) + 10
    x0, y0 = w - panel_w - 10, 10

    overlay = out.copy()
    cv2.rectangle(overlay, (x0, y0), (x0 + panel_w, y0 + panel_h), (30, 30, 30), -1)
    cv2.addWeighted(overlay, 0.6, out, 0.4, 0, out)

    cv2.putText(out, f"Distance Tracker  [{elapsed_sec:.0f}s]",
                (x0 + 6, y0 + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (220, 220, 220), 1)

    row = y0 + 44
    ids = sorted(distances.keys())
    for i, tid in enumerate(ids):
        if player_ids is not None and tid not in player_ids:
            continue
        color = _color(tid)
        dist = distances[tid]
        text = f"Player {tid}:  {dist:.2f} m  ({dist / 1000:.3f} km)"
        cv2.putText(out, text, (x0 + 8, row),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.52, color, 1)
        row += 28

    return out
