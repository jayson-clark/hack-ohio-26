"""ArUco marker IDs and detection.

One dictionary for everything on the table. IDs 0-3 are the four corner
markers on the pinned board holders (their map positions are in terrain.json);
every other ID is a token, and its ID range decides the token type. The marker
sheets in assets/markers/ are generated from these constants, so change them
together.
"""

from dataclasses import dataclass

import cv2
import numpy as np

from protocol import TokenType

DICTIONARY = cv2.aruco.DICT_4X4_50

CORNER_IDS = {"NW": 0, "NE": 1, "SE": 2, "SW": 3}

# First marker ID of each token type; each type gets TOKEN_IDS_PER_TYPE IDs.
TOKEN_ID_START = {
    TokenType.CREW: 10,
    TokenType.FIREBREAK: 20,
    TokenType.WATER: 30,
    TokenType.BUS: 40,
}
TOKEN_IDS_PER_TYPE = 10


def token_type_for(marker_id: int) -> TokenType | None:
    for kind, start in TOKEN_ID_START.items():
        if start <= marker_id < start + TOKEN_IDS_PER_TYPE:
            return kind
    return None


@dataclass(frozen=True)
class Detection:
    id: int
    # (4, 2) float32 image pixels: the marker's own top-left, top-right,
    # bottom-right, bottom-left corners, in that order.
    corners: np.ndarray

    @property
    def center(self) -> np.ndarray:
        # Where the diagonals cross: the true centre even under perspective,
        # unlike the mean of the corners.
        p0, p1, p2, p3 = self.corners.astype(np.float64)
        d1, d2 = p2 - p0, p3 - p1
        denom = d1[0] * d2[1] - d1[1] * d2[0]
        if abs(denom) < 1e-9:
            return self.corners.mean(axis=0)
        t = ((p1[0] - p0[0]) * d2[1] - (p1[1] - p0[1]) * d2[0]) / denom
        return (p0 + t * d1).astype(np.float32)


def make_detector() -> cv2.aruco.ArucoDetector:
    params = cv2.aruco.DetectorParameters()
    # Sub-pixel corners steady the homography and the token angles.
    params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    return cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(DICTIONARY), params)


def detect(detector: cv2.aruco.ArucoDetector, gray: np.ndarray) -> list[Detection]:
    corners, ids, _ = detector.detectMarkers(gray)
    if ids is None:
        return []
    return [Detection(int(i), c.reshape(4, 2)) for i, c in zip(ids.ravel(), corners)]
