"""Projector calibration: where each map cell lands in the projector's image.

PLAN.md, Calibration. The projector goes black until the camera sees all four
corner markers (projected light washes them out), then shows a pattern (a
white ring on black), and the camera finds the ring's corners in that frame
minus the black one. That gives camera
pixels -> projector coords; combined with the board's camera -> map homography
(the corner markers, vision/calibration.py) it gives map -> projector, the 3x3
matrix the projection shader applies. Python never warps images.

Projector coords are normalised to the projector window: (0, 0) is its
top-left, (1, 1) its bottom-right, y down. The matrix then doesn't depend on
the projector's resolution or pixel ratio; the window just has to stay the
size it was calibrated at (fullscreen).

The pattern is big plain shapes, not markers: a projector blooms its whites
several camera px, enough to erase a small marker's bits, but a big shape just
grows. The ring's outer edges grow outward and its inner edges inward, so a fit
over both mostly cancels the bloom.

Camera -> projector is saved too. With the camera and projector on one mount, a
bumped table only moves the board in the camera, so map -> projector is
re-derived from the saved camera -> projector and the board's new position
(Calibrator.follow), with no recalibration. If the camera moves relative to the
projector, recalibrate.

The fit is a plain homography for one plane, but the pattern lands on terrain
up to `relief_mm` tall, so its error includes some parallax (PLAN.md, Height
parallax). A least-squares fit over the whole board averages it out.
"""

import base64
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

from protocol import Calibration, CalibrationPhase

PATTERN_SIZE = (1920, 1080)  # px; the projector stretches it to fill its window
# The pattern, in pattern px (x0, y0, x1, y1): a thick white ring on black and
# a white dot in its hole by the top-left corner. The dot says which corner is
# which, so the camera can sit at any rotation (but not see a mirror image).
# The ring stays in the middle of the frame so it lands on the board, not the
# floor around it: on a darker surface its edge would read as the board's edge.
RING_OUTER = (360, 170, 1560, 910)
RING_INNER = (500, 300, 1420, 780)
DOT = (580, 370, 660, 440)
# Dim: full white blows out a webcam exposed for the room and blooms into the hole.
PATTERN_WHITE = 80
BLACK_SETTLE_S = 0.5  # after Calibrate, wait this long for the projector to go black

MIN_AREA = 0.005  # of the camera frame: smaller shapes aren't the ring
FRAMES_NEEDED = 8  # good frames averaged into one fit
OUTLIER_PX = 25.0  # RANSAC threshold, in pattern px: drops misreads, keeps parallax
MIN_INLIERS = 6  # of the ring's 8 corners
TIMEOUT_S = 30.0  # give up on a pattern the camera never finds

# Follow a moved board once it has shifted the projection by more than this
# (pattern px) for FOLLOW_POLLS polls in a row; smaller shifts are jitter.
FOLLOW_PX = 4.0
FOLLOW_POLLS = 5

CALIBRATION_FILE = Path(__file__).resolve().parents[2] / "calibration.json"

log = logging.getLogger("vision")


def pattern_png() -> bytes:
    img = np.zeros(PATTERN_SIZE[::-1], np.uint8)
    for (x0, y0, x1, y1), v in ((RING_OUTER, 255), (RING_INNER, 0), (DOT, 255)):
        img[y0:y1, x0:x1] = v * PATTERN_WHITE // 255
    return cv2.imencode(".png", img)[1].tobytes()


def black_png() -> bytes:
    return cv2.imencode(".png", np.zeros((8, 8), np.uint8))[1].tobytes()


def _rect_corners(r: tuple[int, int, int, int]) -> list[list[int]]:
    x0, y0, x1, y1 = r
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]  # clockwise from top-left


def pattern_corners() -> np.ndarray:
    """(8, 2) the ring's outer then inner corners, clockwise from top-left, in
    pattern pixels (edges, not pixel centres)."""
    return np.array(_rect_corners(RING_OUTER) + _rect_corners(RING_INNER), np.float64)


# Pattern px -> normalised projector coords.
PX_TO_NORM = np.diag([1 / PATTERN_SIZE[0], 1 / PATTERN_SIZE[1], 1.0])


def normalize(h: np.ndarray) -> np.ndarray:
    return h / h[2, 2]


def transform(h: np.ndarray, pts: np.ndarray) -> np.ndarray:
    return cv2.perspectiveTransform(np.asarray(pts, np.float64).reshape(-1, 1, 2), h).reshape(-1, 2)


# --- Finding the pattern (vision thread) ----------------------------------------

def find_ring(gray: np.ndarray) -> np.ndarray | None:
    """The ring's 8 corners in camera px, ordered like pattern_corners(), or None."""
    _, mask = cv2.threshold(cv2.GaussianBlur(gray, (5, 5), 0), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    contours, hier = cv2.findContours(mask, cv2.RETR_TREE, cv2.CHAIN_APPROX_NONE)
    if hier is None:
        return None
    hier = hier[0]  # per contour: next, previous, first child, parent

    def children(i: int):
        j = hier[i][2]
        while j != -1:
            yield j
            j = hier[j][0]

    best, best_area = None, MIN_AREA * gray.size
    for i, c in enumerate(contours):
        area = cv2.contourArea(c)
        if area <= best_area or (outer := _quad(c)) is None:
            continue
        for j in children(i):
            dots = list(children(j))
            if cv2.contourArea(contours[j]) < 0.1 * area or not dots or (inner := _quad(contours[j])) is None:
                continue
            m = cv2.moments(max((contours[k] for k in dots), key=cv2.contourArea))
            if m["m00"] == 0:
                continue
            inner = _refine(_clockwise(inner, (m["m10"] / m["m00"], m["m01"] / m["m00"])), contours[j])
            outer = _refine(_clockwise(outer, inner[0]), c)
            best, best_area = np.vstack([outer, inner]), area
            break
    return best


def _quad(contour: np.ndarray) -> np.ndarray | None:
    hull = cv2.convexHull(contour)
    approx = cv2.approxPolyDP(hull, 0.02 * cv2.arcLength(hull, True), True)
    return approx.reshape(4, 2).astype(np.float64) if len(approx) == 4 else None


def _clockwise(quad: np.ndarray, first_near) -> np.ndarray:
    """Clockwise on screen (y down), starting at the corner nearest `first_near`."""
    c = quad.mean(axis=0)
    quad = quad[np.argsort(np.arctan2(quad[:, 1] - c[1], quad[:, 0] - c[0]))]
    return np.roll(quad, -int(np.argmin(np.linalg.norm(quad - first_near, axis=1))), axis=0)


def _refine(quad: np.ndarray, contour: np.ndarray) -> np.ndarray:
    """Sub-pixel corners: fit a line to each edge's contour points and intersect them."""
    pts = contour.reshape(-1, 2).astype(np.float64)
    lines = []
    for a, b in zip(quad, np.roll(quad, -1, axis=0)):
        length = np.linalg.norm(b - a)
        u = (b - a) / length
        t = (pts - a) @ u
        off = np.abs((pts - a) @ np.array([-u[1], u[0]]))
        edge = pts[(t > 0.1 * length) & (t < 0.9 * length) & (off < 0.05 * length + 3)]
        if len(edge) < 5:
            return quad
        vx, vy, x, y = cv2.fitLine(edge.astype(np.float32), cv2.DIST_HUBER, 0, 0.01, 0.01).ravel()
        lines.append(np.cross([x, y, 1.0], [x + vx, y + vy, 1.0]))
    corners = [np.cross(lines[i - 1], lines[i]) for i in range(4)]  # corner i joins edges i-1 and i
    return np.array([p[:2] / p[2] for p in corners])


@dataclass(frozen=True)
class PatternFit:
    cam_to_proj: np.ndarray  # 3x3, camera px -> normalised projector coords
    error_px: float  # RMS residual of the fit, pattern px
    points: int


@dataclass(frozen=True)
class PatternProgress:
    search: int  # which Calibrator.search this belongs to
    corners: int  # pattern corners in the latest frame
    frames: int  # good frames so far, of FRAMES_NEEDED
    fit: PatternFit | None  # set once FRAMES_NEEDED frames are in (None if the fit failed)
    failed: bool = False


class PatternFinder:
    """Collects pattern corners over a few frames and fits camera -> projector."""

    def __init__(self, search: int, background: np.ndarray | None = None) -> None:
        self.search = search
        self._background = background  # the table with the projector black, subtracted from each frame
        self._targets = pattern_corners()
        self._seen: dict[int, list[np.ndarray]] = {}
        self.frames = 0
        self.last: np.ndarray | None = None  # (n, 2) camera px of the latest frame's corners
        self.progress = PatternProgress(search, 0, 0, None)

    def feed(self, gray: np.ndarray) -> PatternProgress:
        if self.progress.fit is not None or self.progress.failed:
            return self.progress
        if self._background is not None and self._background.shape == gray.shape:
            gray = cv2.subtract(gray, self._background)
        corners = find_ring(gray)
        n = 0 if corners is None else len(corners)
        self.last = corners
        if corners is not None:
            for i, c in enumerate(corners):
                self._seen.setdefault(i, []).append(c)
            self.frames += 1
        fit, failed = None, False
        if self.frames >= FRAMES_NEEDED:
            fit = self._fit()
            failed = fit is None
        self.progress = PatternProgress(self.search, n, self.frames, fit, failed)
        return self.progress

    def _fit(self) -> PatternFit | None:
        ids = sorted(self._seen)
        cam = np.array([np.median(self._seen[i], axis=0) for i in ids], np.float64)
        proj = self._targets[ids].astype(np.float64)
        h, mask = cv2.findHomography(cam, proj, cv2.RANSAC, OUTLIER_PX)
        if h is None:
            return None
        inl = mask.ravel().astype(bool)
        if inl.sum() < MIN_INLIERS:
            return None
        h, _ = cv2.findHomography(cam[inl], proj[inl], 0)  # least squares on the inliers
        err = transform(h, cam[inl]) - proj[inl]
        rms = float(np.sqrt((err**2).sum(axis=1).mean()))
        return PatternFit(normalize(PX_TO_NORM @ h), rms, int(inl.sum()))


# --- Saved calibration -------------------------------------------------------------

@dataclass
class Saved:
    cam_to_proj: np.ndarray  # camera px -> projector, from the pattern
    board: np.ndarray  # camera px -> map, the board pose map_to_proj was derived with
    map_to_proj: np.ndarray  # what the projector applies
    error_px: float
    scenario: str

    def save(self, path: Path) -> None:
        data = {
            "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "scenario": self.scenario,
            "pattern_size": PATTERN_SIZE,
            "error_px": round(self.error_px, 2),
            "cam_to_proj": self.cam_to_proj.tolist(),
            "board_cam_to_map": self.board.tolist(),
            "map_to_proj": self.map_to_proj.tolist(),
        }
        path.write_text(json.dumps(data, indent=2) + "\n")

    @staticmethod
    def load(path: Path, scenario: str) -> "Saved | None":
        try:
            d = json.loads(path.read_text())
            saved = Saved(
                cam_to_proj=np.array(d["cam_to_proj"], np.float64).reshape(3, 3),
                board=np.array(d["board_cam_to_map"], np.float64).reshape(3, 3),
                map_to_proj=np.array(d["map_to_proj"], np.float64).reshape(3, 3),
                error_px=float(d["error_px"]),
                scenario=d["scenario"],
            )
        except FileNotFoundError:
            return None
        except (ValueError, KeyError, TypeError) as e:
            log.warning("ignoring %s: %s", path, e)
            return None
        if saved.scenario != scenario:
            # The rig's camera -> projector still holds; the next board sighting
            # re-derives map -> projector for this scenario's corner positions.
            saved.board = np.zeros((3, 3))
            saved.scenario = scenario
        return saved


def derive(cam_to_proj: np.ndarray, cam_to_map: np.ndarray) -> np.ndarray:
    """map -> projector = (camera -> projector) . (map -> camera)."""
    return normalize(cam_to_proj @ np.linalg.inv(cam_to_map))


# --- The wizard (engine main loop) -------------------------------------------------

class Calibrator:
    """The calibration wizard's state: none -> pattern -> review -> calibrated.

    The engine calls step() for each calibration_step and poll() every tick
    with the vision thread's latest snapshot; both return True when the
    calibration message changed and should be broadcast.
    """

    def __init__(self, scenario, path: Path = CALIBRATION_FILE) -> None:
        self.scenario = scenario
        self.path = path
        self.saved = Saved.load(path, scenario.name)
        self.phase = CalibrationPhase.CALIBRATED if self.saved else CalibrationPhase.NONE
        self.candidate: Saved | None = None  # in review
        self.message: str | None = None
        self.search = 0  # bumped per attempt, so a stale search's result is ignored
        self.progress = PatternProgress(0, 0, 0, None)
        self._started = 0.0
        self._before = self.phase  # where cancel returns to
        self._board_at_start: np.ndarray | None = None
        self._drift_polls = 0
        self._png = "data:image/png;base64," + base64.b64encode(pattern_png()).decode()
        self._black = "data:image/png;base64," + base64.b64encode(black_png()).decode()
        self._corner_targets = len(pattern_corners())
        if self.saved and not self.saved.board.any():
            log.info("calibration.json is for another scenario: waiting for the board to re-derive it")

    @property
    def finding(self) -> int | None:
        """The search the vision thread should run (it leaves tokens alone meanwhile), or None."""
        if self.phase != CalibrationPhase.PATTERN or self._board_at_start is None:
            return None
        return self.search

    def map_to_proj(self) -> np.ndarray | None:
        if self.phase == CalibrationPhase.REVIEW and self.candidate is not None:
            return self.candidate.map_to_proj
        if self.phase in (CalibrationPhase.CALIBRATED, CalibrationPhase.REVIEW) and self.saved and self.saved.board.any():
            return self.saved.map_to_proj
        return None

    def message_model(self) -> Calibration:
        h = self.map_to_proj()
        shown = self.candidate if self.phase == CalibrationPhase.REVIEW and self.candidate else self.saved
        return Calibration(
            phase=self.phase,
            map_to_proj=None if h is None else [float(v) for v in h.ravel()],
            pattern=None if self.phase != CalibrationPhase.PATTERN else self._png if self._board_at_start is not None
            else self._black,
            corners_found=self.progress.corners,
            corners_total=self._corner_targets,
            frames=self.progress.frames,
            frames_needed=FRAMES_NEEDED,
            error_px=None if shown is None else round(shown.error_px, 2),
            message=self.message,
        )

    def step(self, action: str, has_camera: bool) -> bool:
        self.message = None
        match action:
            case "start":
                if not has_camera:
                    self.message = "Calibration needs the camera: set CAMERA in .env and restart the engine."
                else:
                    if self.phase != CalibrationPhase.PATTERN:
                        self._before = CalibrationPhase.CALIBRATED if self.saved else CalibrationPhase.NONE
                    self.phase = CalibrationPhase.PATTERN
                    self.candidate = None
                    self.search += 1
                    self.progress = PatternProgress(self.search, 0, 0, None)
                    # The projector goes black until the camera sees all four
                    # corners, then shows the pattern (see the module docstring).
                    self._board_at_start = None
                    self._started = time.monotonic()
                    self.message = "Looking for the four corner markers…"
            case "save":
                if self.phase == CalibrationPhase.REVIEW:
                    if self.candidate is not None:
                        self.saved = self.candidate
                        self.saved.save(self.path)
                        log.info("projector calibration saved to %s (%.1f px)", self.path, self.saved.error_px)
                    self.candidate = None
                    self.phase = CalibrationPhase.CALIBRATED
            case "check":
                if self.phase == CalibrationPhase.CALIBRATED and self.map_to_proj() is not None:
                    self.candidate = None
                    self.phase = CalibrationPhase.REVIEW
            case "cancel":
                if self.phase in (CalibrationPhase.PATTERN, CalibrationPhase.REVIEW):
                    self.candidate = None
                    self.phase = CalibrationPhase.CALIBRATED if self.saved else CalibrationPhase.NONE
            case "clear":
                self.saved = self.candidate = None
                self.path.unlink(missing_ok=True)
                self.phase = CalibrationPhase.NONE
        return True

    def poll(self, progress: PatternProgress | None, board: np.ndarray | None) -> bool:
        """`progress`: the vision thread's pattern search (None when it isn't
        searching yet). `board`: camera -> map from a frame that saw all four
        corners, else None."""
        if self.phase == CalibrationPhase.PATTERN and self._board_at_start is None:
            return self._poll_board(board)
        if self.phase == CalibrationPhase.PATTERN:
            return self._poll_pattern(progress)
        if self.phase == CalibrationPhase.CALIBRATED:
            return self._follow(board)
        return False

    def _poll_board(self, board: np.ndarray | None) -> bool:
        if board is not None and time.monotonic() - self._started > BLACK_SETTLE_S:
            self._board_at_start = board
            self._started = time.monotonic()
            self.message = None
            return True
        if time.monotonic() - self._started > TIMEOUT_S:
            self.phase = self._before
            self.message = "The camera can't see all four corner markers. Are they on the table and in its view?"
            return True
        return False

    def _poll_pattern(self, progress: PatternProgress | None) -> bool:
        if progress is None or progress.search != self.search:
            return False
        if progress.fit is not None:
            fit = progress.fit
            self.candidate = Saved(fit.cam_to_proj, self._board_at_start, derive(fit.cam_to_proj, self._board_at_start),
                                   fit.error_px, self.scenario.name)
            self.progress = progress
            self.phase = CalibrationPhase.REVIEW
            log.info("projector pattern fit: %d corners, %.1f px RMS", fit.points, fit.error_px)
            return True
        if progress.failed or time.monotonic() - self._started > TIMEOUT_S:
            self.phase = self._before
            self.message = (
                "Couldn't fit the pattern. Check the projector window is fullscreen and the room isn't too bright."
                if progress.failed else
                "The camera can't see the pattern. Is the projector window open, fullscreen, and pointed at the board?"
            )
            return True
        changed = (progress.corners, progress.frames) != (self.progress.corners, self.progress.frames)
        self.progress = progress
        return changed

    def _follow(self, board: np.ndarray | None) -> bool:
        if self.saved is None or board is None:
            self._drift_polls = 0
            return False
        if not self.saved.board.any():  # saved for another scenario: derive now
            self._accept(board)
            return True
        corners = np.array([[0, 0], [self.scenario.width, 0], [self.scenario.width, self.scenario.height],
                            [0, self.scenario.height]], np.float64)
        now = transform(derive(self.saved.cam_to_proj, board), corners)
        shift = np.abs(now - transform(self.saved.map_to_proj, corners)) * PATTERN_SIZE
        if shift.max() < FOLLOW_PX:
            self._drift_polls = 0
            return False
        self._drift_polls += 1
        if self._drift_polls < FOLLOW_POLLS:
            return False
        log.info("board moved %.0f px: following it", shift.max())
        self._accept(board)
        return True

    def _accept(self, board: np.ndarray) -> None:
        assert self.saved is not None
        self.saved.board = board
        self.saved.map_to_proj = derive(self.saved.cam_to_proj, board)
        self.saved.save(self.path)
        self._drift_polls = 0
