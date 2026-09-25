"""
Distance tracker: accumulates real-world distance per track ID across frames.
"""

from __future__ import annotations

import math
from collections import defaultdict


class DistanceTracker:
    def __init__(self):
        # track_id -> total distance in meters
        self._total: dict[int, float] = defaultdict(float)
        # track_id -> last known world position
        self._last_pos: dict[int, tuple[float, float]] = {}

    def update(self, track_id: int, world_pos: tuple[float, float]) -> float:
        """
        Update position for a track. Returns distance added this step (meters).
        """
        delta = 0.0
        if track_id in self._last_pos:
            px, py = self._last_pos[track_id]
            wx, wy = world_pos
            delta = math.hypot(wx - px, wy - py)
            # Ignore implausibly large jumps (>5 m per frame) — tracking glitch
            if delta < 5.0:
                self._total[track_id] += delta
            else:
                delta = 0.0
        self._last_pos[track_id] = world_pos
        return delta

    def get_distance(self, track_id: int) -> float:
        return self._total[track_id]

    def all_distances(self) -> dict[int, float]:
        return dict(self._total)

    def reset(self, track_id: int) -> None:
        self._total.pop(track_id, None)
        self._last_pos.pop(track_id, None)
