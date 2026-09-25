"""
Player tracker: wraps YOLOv8 + ByteTrack to detect and track persons.
Returns per-frame list of (track_id, bbox, foot_position_pixel).
"""

from __future__ import annotations

import numpy as np
from ultralytics import YOLO

PERSON_CLASS = 0  # COCO class index for "person"


class PlayerTracker:
    def __init__(self, model_path: str = "yolov8n.pt", conf: float = 0.4):
        self._model = YOLO(model_path)
        self._conf = conf

    def process_frame(self, frame: np.ndarray) -> list[dict]:
        """
        Run detection + tracking on one frame.

        Returns list of dicts:
            {
                "track_id": int,
                "bbox": (x1, y1, x2, y2),   # pixels
                "foot": (cx, y2),            # bottom-center of bbox
                "conf": float,
            }
        """
        results = self._model.track(
            frame,
            persist=True,
            conf=self._conf,
            classes=[PERSON_CLASS],
            verbose=False,
        )

        detections = []
        if results and results[0].boxes is not None:
            boxes = results[0].boxes
            for box in boxes:
                if box.id is None:
                    continue
                track_id = int(box.id.item())
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                conf = float(box.conf.item())
                cx = (x1 + x2) / 2
                foot = (cx, y2)  # bottom-center approximates ground contact
                detections.append({
                    "track_id": track_id,
                    "bbox": (x1, y1, x2, y2),
                    "foot": foot,
                    "conf": conf,
                })

        return detections
