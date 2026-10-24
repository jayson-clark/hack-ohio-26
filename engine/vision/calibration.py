"""Camera -> map homography from the four corner markers.

The corner holders are pinned to the board, so whenever the camera sees all
four corner markers it knows exactly where the map is. The homography is
re-solved on every such frame, so a bumped table or camera fixes itself; when
a hand covers a corner, the last good one is kept.

It's a plain plane-to-plane homography at the height of the corner markers.
Tokens sitting on hills are off that plane, so they read slightly outward
from the camera's axis (about h * d / camera height, the same parallax as the
projector; see PLAN.md, Calibration).
"""

import cv2
import numpy as np

from scenario import Scenario
from vision.markers import CORNER_IDS, Detection


class BoardHomography:
    def __init__(self, scenario: Scenario) -> None:
        corners = {c["corner"]: c["center_map"] for c in scenario.terrain["markers"]["corners"]}
        self._ids = list(CORNER_IDS.values())
        self._map_pts = np.array([corners[name] for name in CORNER_IDS], np.float32)
        self.width, self.height = scenario.width, scenario.height
        self.cam_to_map: np.ndarray | None = None  # 3x3 float64
        self.corners_seen: list[str] = []

    def update(self, detections: list[Detection]) -> bool:
        """Re-solve from this frame's detections. True if all four were seen."""
        by_id = {d.id: d for d in detections}
        self.corners_seen = [name for name, i in CORNER_IDS.items() if i in by_id]
        if len(self.corners_seen) < len(CORNER_IDS):
            return False
        cam_pts = np.array([by_id[i].center for i in self._ids], np.float32)
        self.cam_to_map = cv2.getPerspectiveTransform(cam_pts, self._map_pts)
        return True

    def to_map(self, pts: np.ndarray) -> np.ndarray:
        """(n, 2) image pixels -> (n, 2) map coords. Needs a solved homography."""
        assert self.cam_to_map is not None
        return cv2.perspectiveTransform(pts.reshape(-1, 1, 2).astype(np.float32), self.cam_to_map).reshape(-1, 2)

    def map_outline_in_camera(self) -> np.ndarray | None:
        """The map grid's border in image pixels, for the debug overlay."""
        if self.cam_to_map is None:
            return None
        w, h = self.width, self.height
        rect = np.array([[0, 0], [w, 0], [w, h], [0, h]], np.float32).reshape(-1, 1, 2)
        return cv2.perspectiveTransform(rect, np.linalg.inv(self.cam_to_map)).reshape(-1, 2)
