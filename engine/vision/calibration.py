"""Camera -> map homography from the four corner markers.

The corner holders are pinned to the board, so whenever the camera sees all
four corner markers it knows exactly where the map is. The homography is
re-solved on every such frame, so a bumped table or camera fixes itself; when
a hand covers a corner, the last good one is kept.

It's a plain plane-to-plane homography at the height of the corner markers.
Tokens sitting on hills are off that plane and would read outward from the
camera's axis (about h * d / camera height), so each solve also places the
camera (vision/geometry.py) and to_surface() follows the line of sight down to
the terrain.
"""

import logging

import cv2
import numpy as np

from scenario import Scenario
from vision.geometry import Surface, Viewpoint, camera_viewpoint, onto_surface, orthophoto_remap
from vision.markers import CORNER_IDS, Detection

log = logging.getLogger("vision")


class BoardHomography:
    def __init__(self, scenario: Scenario) -> None:
        corners = {c["corner"]: c["center_map"] for c in scenario.terrain["markers"]["corners"]}
        self._ids = list(CORNER_IDS.values())
        self._map_pts = np.array([corners[name] for name in CORNER_IDS], np.float32)
        self.width, self.height = scenario.width, scenario.height
        self.cam_to_map: np.ndarray | None = None  # 3x3 float64
        self.camera: Viewpoint | None = None  # placed with cam_to_map
        self.surface = Surface(scenario)
        self.corners_seen: list[str] = []
        self.misplaced = False  # all four seen, but not in order round the board

    def update(self, detections: list[Detection], frame_size: tuple[int, int] = (1920, 1080)) -> bool:
        """Re-solve from this frame's detections. True if all four were seen."""
        by_id = {d.id: d for d in detections}
        self.corners_seen = [name for name, i in CORNER_IDS.items() if i in by_id]
        if len(self.corners_seen) < len(CORNER_IDS):
            return False
        cam_pts = np.array([by_id[i].center for i in self._ids], np.float32)
        if not cv2.isContourConvex(cam_pts.reshape(-1, 1, 2)):
            # Two corner markers swapped (NW, NE, SE, SW should go round the
            # board): the solve would fold the map over itself.
            if not self.misplaced:
                log.warning("corner markers out of order (%s): two are swapped", ", ".join(self.corners_seen))
            self.misplaced = True
            return False
        self.misplaced = False
        self.cam_to_map = cv2.getPerspectiveTransform(cam_pts, self._map_pts).astype(np.float64)
        self.camera = camera_viewpoint(self.cam_to_map, self._map_pts, frame_size, self.surface.cell_mm)
        return True

    def to_map(self, pts: np.ndarray) -> np.ndarray:
        """(n, 2) image pixels -> (n, 2) map coords. Needs a solved homography."""
        assert self.cam_to_map is not None
        return cv2.perspectiveTransform(pts.reshape(-1, 1, 2).astype(np.float32), self.cam_to_map).reshape(-1, 2)

    def to_surface(self, pts: np.ndarray, lift_mm: float = 0.0) -> np.ndarray:
        """(n, 2) image pixels of points on the terrain, raised `lift_mm` (a
        token's top) -> (n, 2) map coords of the ground under them."""
        plane = self.to_map(pts)
        if self.camera is None:
            return plane
        return onto_surface(self.camera, plane, self.surface, lift_mm)[0].astype(np.float32)

    def map_outline_in_camera(self) -> np.ndarray | None:
        """The map grid's border in image pixels, for the debug overlay."""
        if self.cam_to_map is None:
            return None
        w, h = self.width, self.height
        rect = np.array([[0, 0], [w, 0], [w, h], [0, h]], np.float32).reshape(-1, 1, 2)
        return cv2.perspectiveTransform(rect, np.linalg.inv(self.cam_to_map)).reshape(-1, 2)

    def orthophoto_remap(self, out_size: tuple[int, int]) -> np.ndarray | None:
        """A cv2.remap table (h, w, 2) that rectifies the camera frame to a
        top-down view of the whole board at `out_size` (width, height) px, or
        None if there's no board lock yet. Uses the camera pose when it has one,
        so hills don't lean outward."""
        if self.cam_to_map is None:
            return None
        return orthophoto_remap(self.cam_to_map, self.camera, self.surface, out_size)

    def map_to_ortho(self, pts: np.ndarray, out_size: tuple[int, int]) -> np.ndarray:
        """(n, 2) map coords -> (n, 2) pixels in an orthophoto of `out_size`
        (width, height). The straight scale from cells to output pixels, so
        tokens and places drawn here land where the rectified terrain shows
        them."""
        pts = np.asarray(pts, np.float64).reshape(-1, 2)
        out_w, out_h = out_size
        return (pts * [out_w / self.width, out_h / self.height]).astype(np.float32)
