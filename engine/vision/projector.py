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

The pattern lands on terrain up to `relief_mm` tall, so it isn't one plane.
After the ring, the projector shows a grid of dots placed with the ring's flat
fit. Each dot's centre is one point at one height (the ring's corners are
lines fitted along whole edges that cross hills, so they aren't), so each
dot's camera ray, followed down to the heightmap, gives a 3D point and the
projector pixel that lit it. From those the vision thread solves where the
projector lens is (no tape needed; PROJECTOR_MM is only a starting guess) and
map -> projector for the marker plane (vision/geometry.py). The projector
shader offsets each vertex by its height to match, so calibration works with
the terrain in place. If the dots can't be seen, the ring alone is used.
"""

import base64
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

from protocol import Calibration, CalibrationPhase
from vision.geometry import Surface, Viewpoint, onto_surface, to_plane

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
OUTLIER_PX = 25.0  # RANSAC threshold on the flat fit, in pattern px: drops misreads, keeps parallax
MIN_INLIERS = 6  # of the ring's 8 corners
TIMEOUT_S = 30.0  # give up on a pattern the camera never finds

# The dot grid: dots across and down the map, kept DOT_MARGIN (of the map) from
# its edges, placed with the ring's flat fit.
DOT_GRID = (12, 9)
DOT_MARGIN = 0.06
DOT_RADIUS = 14  # pattern px
DOT_SETTLE_S = 0.5  # after switching to the dots, wait this long for the projector
DOT_MATCH_PX = 22  # camera px: a blob this close to where the flat fit expects a dot is that dot
DOT_AREA = (8, 3000)  # camera px^2
MIN_DOTS = 24
DOTS_TIMEOUT_S = 10.0  # then fall back to the ring alone
LENS_HEIGHT_MM = (150.0, 3000.0)  # plausible projector heights for the solve

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
    cam_to_proj: np.ndarray  # 3x3, camera px -> normalised projector coords, as if the board were flat
    error_px: float  # RMS residual of the flat fit, pattern px
    points: int
    cam: np.ndarray | None = None  # (n, 2) the inlier corners, camera px
    proj: np.ndarray | None = None  # (n, 2) where they are in the pattern, normalised


@dataclass(frozen=True)
class LensFit:
    """The dot grid's result."""

    map_to_proj: np.ndarray  # marker plane -> projector, with the height correction
    cam_to_proj: np.ndarray  # camera px -> projector, kept for following a moved board
    projector: Viewpoint | None  # the solved lens, None if the dots couldn't place it
    error_px: float  # RMS residual, pattern px
    flat_error_px: float  # the same dots fitted as if the board were flat
    points: int


@dataclass(frozen=True)
class PatternProgress:
    search: int  # which Calibrator.search this belongs to
    corners: int  # pattern corners (or dots) in the latest frame
    frames: int  # good frames so far, of FRAMES_NEEDED
    fit: PatternFit | None  # set once FRAMES_NEEDED frames are in (None if the fit failed)
    failed: bool = False
    dots: bool = False  # this is the dot grid's search
    lens: LensFit | None = None  # the dots' result


@dataclass(frozen=True)
class DotSearch:
    """What the vision thread needs for the dot grid (Calibrator.finding)."""

    search: int
    expected: np.ndarray  # (n, 2) camera px where the flat fit puts each dot
    solve: Callable[[np.ndarray], LensFit | None]  # run on the vision thread with the dots' camera px


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
        return PatternFit(normalize(PX_TO_NORM @ h), rms, int(inl.sum()), cam[inl], transform(PX_TO_NORM, proj[inl]))


def fit_on_terrain(fit: PatternFit, board: np.ndarray, surface: Surface, camera: Viewpoint | None,
                   projector: Viewpoint | None) -> tuple[np.ndarray, np.ndarray, float]:
    """The pattern fit with the terrain's height taken out. Returns map ->
    projector for the marker plane (what the shader applies, offsetting each
    vertex by its height), the matching camera -> projector (kept for
    following a moved board), and the RMS residual in pattern px.

    Each corner: camera px -> marker plane (the board homography) -> along the
    camera ray onto the terrain -> along the projector ray back to the marker
    plane. Without a camera pose the corners stay where the plane puts them;
    without a projector position it's taken as straight overhead."""
    if fit.cam is None or camera is None:
        return derive(fit.cam_to_proj, board), fit.cam_to_proj, fit.error_px
    ground, heights = onto_surface(camera, transform(board, fit.cam), surface)
    plane = ground if projector is None else to_plane(projector, ground, heights)
    target = fit.proj * PATTERN_SIZE
    h, _ = cv2.findHomography(plane, target, 0)
    if h is None:
        return derive(fit.cam_to_proj, board), fit.cam_to_proj, fit.error_px
    rms = float(np.sqrt(((transform(h, plane) - target) ** 2).sum(axis=1).mean()))
    map_to_proj = normalize(PX_TO_NORM @ h)
    return map_to_proj, normalize(map_to_proj @ board), rms


# --- The dot grid ---------------------------------------------------------------------

def dot_centres(map_to_proj: np.ndarray, window: tuple[int, int, int, int]) -> np.ndarray:
    """(n, 2) pattern px of the grid's dots over the print (`window`: x0, y0,
    width, height in map cells), through a flat map -> projector, keeping
    those well inside the projector frame."""
    nx, ny = DOT_GRID
    x0, y0, width, height = window
    xs = x0 + np.linspace(DOT_MARGIN, 1 - DOT_MARGIN, nx) * width
    ys = y0 + np.linspace(DOT_MARGIN, 1 - DOT_MARGIN, ny) * height
    grid = np.array([[x, y] for y in ys for x in xs])
    px = transform(map_to_proj, grid) * PATTERN_SIZE
    pad = 2 * DOT_RADIUS
    inside = (px[:, 0] > pad) & (px[:, 0] < PATTERN_SIZE[0] - pad) & (px[:, 1] > pad) & (px[:, 1] < PATTERN_SIZE[1] - pad)
    return px[inside]


def dots_png(centres: np.ndarray) -> bytes:
    img = np.zeros(PATTERN_SIZE[::-1], np.uint8)
    shift = 4  # sub-pixel centres
    for x, y in centres:
        # Pattern pixel edges -> OpenCV's pixel-centre coords.
        c = (round((x - 0.5) * (1 << shift)), round((y - 0.5) * (1 << shift)))
        cv2.circle(img, c, DOT_RADIUS << shift, PATTERN_WHITE, -1, cv2.LINE_AA, shift)
    return cv2.imencode(".png", img)[1].tobytes()


def find_dots(gray: np.ndarray, expected: np.ndarray) -> np.ndarray:
    """(n, 2) camera px of each expected dot's blob (brightness-weighted
    centre), NaN where none is close enough."""
    _, mask = cv2.threshold(cv2.GaussianBlur(gray, (3, 3), 0), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    out = np.full((len(expected), 2), np.nan)
    if n < 2:
        return out
    ys, xs = np.nonzero(labels)
    lab = labels[ys, xs]
    w = gray[ys, xs].astype(np.float64)
    sw = np.bincount(lab, w, n)
    cx = np.bincount(lab, w * xs, n) / np.maximum(sw, 1e-9)
    cy = np.bincount(lab, w * ys, n) / np.maximum(sw, 1e-9)
    area = stats[:, cv2.CC_STAT_AREA]
    keep = np.flatnonzero((area >= DOT_AREA[0]) & (area <= DOT_AREA[1]))
    keep = keep[keep > 0]  # 0 is the background
    if not len(keep):
        return out
    blobs = np.column_stack([cx[keep], cy[keep]])
    d = np.linalg.norm(expected[:, None, :] - blobs[None, :, :], axis=2)
    nearest_blob = d.argmin(axis=1)
    nearest_dot = d.argmin(axis=0)
    for i, j in enumerate(nearest_blob):
        if d[i, j] < DOT_MATCH_PX and nearest_dot[j] == i:  # mutual: no blob counts twice
            out[i] = blobs[j]
    return out


class DotFinder:
    """Collects the dots' camera positions over a few frames, then solves."""

    def __init__(self, request: DotSearch, background: np.ndarray | None = None) -> None:
        self.request = request
        self.search = request.search
        self._background = background
        self._seen: list[np.ndarray] = []
        self.last: np.ndarray | None = None
        self.progress = PatternProgress(request.search, 0, 0, None, dots=True)

    def feed(self, gray: np.ndarray) -> PatternProgress:
        if self.progress.lens is not None or self.progress.failed:
            return self.progress
        if self._background is not None and self._background.shape == gray.shape:
            gray = cv2.subtract(gray, self._background)
        dots = find_dots(gray, self.request.expected)
        found = int((~np.isnan(dots[:, 0])).sum())
        self.last = dots[~np.isnan(dots[:, 0])]
        if found >= MIN_DOTS:
            self._seen.append(dots)
        lens, failed = None, False
        if len(self._seen) >= FRAMES_NEEDED:
            stack = np.array(self._seen)
            seen = (~np.isnan(stack[:, :, 0])).sum(axis=0)
            med = np.nanmedian(np.where(seen[None, :, None] * 2 >= len(stack), stack, np.nan), axis=0)
            lens = self.request.solve(med)
            failed = lens is None
        self.progress = PatternProgress(self.search, found, len(self._seen), None, failed, dots=True, lens=lens)
        return self.progress


def solve_lens(cam: np.ndarray, target: np.ndarray, board: np.ndarray, surface: Surface, camera: Viewpoint | None,
               guess: Viewpoint | None) -> LensFit | None:
    """The projector lens and map -> projector from dots seen at `cam` (camera
    px, NaN where missed) that the projector drew at `target` (pattern px).

    For a trial lens, each dot's ground point (its camera ray onto the
    terrain) goes up the lens's ray to the marker plane, and a homography is
    fitted from there to the pattern. A pattern search over the lens's three
    coordinates, from a spread of starts, keeps the one with the smallest
    residual. A single lens explains how every dot's offset grows with its
    height, so the fit can tell lens positions apart."""
    ok = ~np.isnan(cam).any(axis=1)
    if ok.sum() < MIN_DOTS:
        return None
    cam, target = cam[ok], target[ok]
    flat, _ = cv2.findHomography(cam, target, 0)
    if flat is None:
        return None
    flat_rms = _rms(transform(flat, cam), target)
    flat_c2p = normalize(PX_TO_NORM @ flat)
    if camera is None:
        return LensFit(derive(flat_c2p, board), flat_c2p, None, flat_rms, flat_rms, len(cam))
    ground, heights = onto_surface(camera, transform(board, cam), surface)

    def err(lens: Viewpoint | None, pts=slice(None)) -> tuple[float, np.ndarray | None]:
        plane = ground[pts] if lens is None else to_plane(lens, ground[pts], heights[pts])
        h, _ = cv2.findHomography(plane, target[pts], 0)
        return (np.inf, None) if h is None else (_rms(transform(h, plane), target[pts]), h)

    def search(start: Viewpoint, pts=slice(None)) -> tuple[float, Viewpoint]:
        x = np.array([start.x, start.y, start.h])
        step = np.array([surface.width / 4, surface.height / 4, start.h / 4])
        best = err(start, pts)[0]
        for _ in range(400):
            moved = False
            for axis in range(3):
                for sign in (1, -1):
                    trial = x.copy()
                    trial[axis] += sign * step[axis]
                    trial[2] = np.clip(trial[2], *LENS_HEIGHT_MM)
                    e = err(Viewpoint(*trial), pts)[0]
                    if e < best:
                        best, x, moved = e, trial, True
            if not moved:
                step /= 2
                if step[0] < 0.05 and step[2] < 0.5:
                    break
        return best, Viewpoint(*x)

    x0, y0, w, h = surface.x0, surface.y0, surface.width, surface.height
    starts = [guess] if guess is not None else []
    starts += [Viewpoint(x0 + x, y0 + y, z) for x in (-0.5 * w, 0.5 * w, 1.5 * w) for y in (-0.5 * h, 0.5 * h, 1.5 * h)
               for z in (400.0, 900.0)]
    best_e, lens = min((search(s) for s in starts), key=lambda r: r[0])
    # Drop dots that don't fit (a blob from a reflection, a dot on a seam) and polish.
    plane = to_plane(lens, ground, heights)
    resid = np.linalg.norm(transform(err(lens)[1], plane) - target, axis=1)
    keep = resid < max(3 * np.median(resid), 4.0)
    if keep.sum() >= MIN_DOTS and not keep.all():
        best_e, lens = search(lens, keep)
    else:
        keep = np.ones(len(cam), bool)
    overhead_e = err(None, keep)[0]
    if lens.h <= LENS_HEIGHT_MM[0] + 1 or lens.h >= LENS_HEIGHT_MM[1] - 1 or best_e > 0.8 * overhead_e:
        # The dots couldn't place the lens: no better than straight overhead.
        log.warning("dot grid couldn't place the projector (%.1f px vs %.1f overhead); using %s", best_e, overhead_e,
                    "PROJECTOR_MM" if guess else "no height correction")
        lens = guess
        best_e = err(lens, keep)[0]
    e, hom = err(lens, keep)
    map_to_proj = normalize(PX_TO_NORM @ hom)
    return LensFit(map_to_proj, normalize(map_to_proj @ board), lens, e, _rms(transform(flat, cam[keep]), target[keep]),
                   int(keep.sum()))


def _rms(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.sqrt(((a - b) ** 2).sum(axis=1).mean()))


# --- Saved calibration -------------------------------------------------------------

@dataclass
class Saved:
    cam_to_proj: np.ndarray  # camera px -> projector, from the pattern
    board: np.ndarray  # camera px -> map, the board pose map_to_proj was derived with
    map_to_proj: np.ndarray  # what the projector applies
    error_px: float
    scenario: str
    projector: Viewpoint | None = None  # the solved lens, over the board as `board` sees it

    def save(self, path: Path) -> None:
        data = {
            "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "scenario": self.scenario,
            "pattern_size": PATTERN_SIZE,
            "error_px": round(self.error_px, 2),
            "cam_to_proj": self.cam_to_proj.tolist(),
            "board_cam_to_map": self.board.tolist(),
            "map_to_proj": self.map_to_proj.tolist(),
            "projector": None if self.projector is None else [self.projector.x, self.projector.y, self.projector.h],
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
                projector=Viewpoint(*map(float, d["projector"])) if d.get("projector") else None,
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
            saved.projector = None  # in the old scenario's map coords
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

    def __init__(self, scenario, path: Path = CALIBRATION_FILE, projector: Viewpoint | None = None) -> None:
        self.scenario = scenario
        self.path = path
        self.surface = Surface(scenario)
        # The guessed projector lens (PROJECTOR_MM), the dot grid's starting
        # point and fallback, relative to the board where it sits now. It's fixed to the rig, not the board, so it's
        # pinned to the camera pixel above its foot and moves with the rig
        # when the board is bumped.
        self._projector = projector
        self._projector_px: np.ndarray | None = None
        self.saved = Saved.load(path, scenario.name)
        self.phase = CalibrationPhase.CALIBRATED if self.saved else CalibrationPhase.NONE
        self.candidate: Saved | None = None  # in review
        self.message: str | None = None
        self.search = 0  # bumped per attempt, so a stale search's result is ignored
        self.progress = PatternProgress(0, 0, 0, None)
        self._started = 0.0
        self._before = self.phase  # where cancel returns to
        self._board_at_start: np.ndarray | None = None
        self._camera_at_start: Viewpoint | None = None
        # The dot grid's stage, after the ring: what to look for, its image,
        # when it went up, and the ring's result to fall back on.
        self._dots: DotSearch | None = None
        self._dots_png: str | None = None
        self._dots_since = 0.0
        self._ring_candidate: Saved | None = None
        self._drift_polls = 0
        self._png = "data:image/png;base64," + base64.b64encode(pattern_png()).decode()
        self._black = "data:image/png;base64," + base64.b64encode(black_png()).decode()
        self._corner_targets = len(pattern_corners())
        if self.saved and not self.saved.board.any():
            log.info("calibration.json is for another scenario: waiting for the board to re-derive it")
        elif self.saved:
            self._pin_projector(self.saved.board)

    def _pin_projector(self, board: np.ndarray) -> None:
        if self._projector is not None and self._projector_px is None:
            self._projector_px = transform(np.linalg.inv(board), self._projector.foot[None])[0]

    def projector(self, board: np.ndarray | None) -> Viewpoint | None:
        """The projector lens over the board seen as `board` (camera -> map)."""
        if self._projector is None or self._projector_px is None or board is None or not board.any():
            return self._projector
        x, y = transform(board, self._projector_px[None])[0]
        return Viewpoint(float(x), float(y), self._projector.h)

    @property
    def finding(self) -> int | DotSearch | None:
        """The search the vision thread should run (it leaves tokens alone
        meanwhile): the ring's search number, the dot grid, or None. While the
        projector switches to the dots it stays on the finished ring search,
        so no frame of the change is read as dots or as the background."""
        if self.phase != CalibrationPhase.PATTERN or self._board_at_start is None:
            return None
        if self._dots is not None and time.monotonic() - self._dots_since > DOT_SETTLE_S:
            return self._dots
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
        lens = None
        if h is not None and shown is not None:
            lens = shown.projector or self.projector(shown.board)
        pattern = None
        if self.phase == CalibrationPhase.PATTERN:
            pattern = self._black if self._board_at_start is None else self._dots_png or self._png
        return Calibration(
            phase=self.phase,
            map_to_proj=None if h is None else [float(v) for v in h.ravel()],
            projector=None if lens is None else [round(lens.x, 3), round(lens.y, 3), round(lens.h, 1)],
            pattern=pattern,
            corners_found=self.progress.corners,
            corners_total=len(self._dots.expected) if self._dots is not None else self._corner_targets,
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
                    self._dots = self._dots_png = self._ring_candidate = None
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

    def poll(self, progress: PatternProgress | None, board: np.ndarray | None, camera: Viewpoint | None = None) -> bool:
        """`progress`: the vision thread's pattern search (None when it isn't
        searching yet). `board`: camera -> map from a frame that saw all four
        corners, else None; `camera`: the camera's centre from that frame."""
        if self.phase == CalibrationPhase.PATTERN and self._board_at_start is None:
            return self._poll_board(board, camera)
        if self.phase == CalibrationPhase.PATTERN:
            return self._poll_pattern(progress)
        if self.phase == CalibrationPhase.CALIBRATED:
            return self._follow(board)
        return False

    def _poll_board(self, board: np.ndarray | None, camera: Viewpoint | None) -> bool:
        if board is not None and time.monotonic() - self._started > BLACK_SETTLE_S:
            self._board_at_start = board
            self._camera_at_start = camera
            self._pin_projector(board)
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
        if self._dots is not None:
            return self._poll_dots(progress)
        if progress.dots:
            return False
        if progress.fit is not None:
            fit, board, camera = progress.fit, self._board_at_start, self._camera_at_start
            guess = self.projector(board)
            map_to_proj, cam_to_proj, err = fit_on_terrain(fit, board, self.surface, camera, guess)
            self._ring_candidate = Saved(cam_to_proj, board, map_to_proj, err, self.scenario.name, guess)
            self.progress = progress
            log.info("projector ring fit: %d corners, %.1f px RMS; camera %s mm up", fit.points, fit.error_px,
                     "?" if camera is None else f"{camera.h:.0f}")
            # Then the dots, placed with the ring's flat fit.
            centres = dot_centres(derive(fit.cam_to_proj, board), self.scenario.print_window)
            if len(centres) < MIN_DOTS:
                return self._review(self._ring_candidate, "The dot grid doesn't fit on the board, so this uses the ring alone.")
            expected = transform(np.linalg.inv(fit.cam_to_proj), centres / PATTERN_SIZE)
            surface = self.surface
            self._dots = DotSearch(self.search, expected,
                                   lambda cam: solve_lens(cam, centres, board, surface, camera, guess))
            self._dots_png = "data:image/png;base64," + base64.b64encode(dots_png(centres)).decode()
            self._dots_since = time.monotonic()
            self.progress = PatternProgress(self.search, 0, 0, None, dots=True)
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

    def _poll_dots(self, progress: PatternProgress) -> bool:
        if not progress.dots:  # the ring's search, while the projector switches
            return False
        if progress.lens is not None:
            lens = progress.lens
            c = self._ring_candidate
            log.info("projector dot fit: %d dots, %.1f px RMS (%.1f px flat); lens %s", lens.points, lens.error_px,
                     lens.flat_error_px, "not placed" if lens.projector is None else
                     f"{lens.projector.h + self.scenario.terrain['markers']['marker_top_z_mm']:.0f} mm up")
            return self._review(Saved(lens.cam_to_proj, c.board, lens.map_to_proj, lens.error_px, c.scenario,
                                      lens.projector), None)
        if progress.failed or time.monotonic() - self._dots_since > DOTS_TIMEOUT_S:
            return self._review(self._ring_candidate,
                                "Couldn't see the dot grid, so this uses the ring alone (less accurate on hills).")
        changed = (progress.corners, progress.frames) != (self.progress.corners, self.progress.frames)
        self.progress = progress
        return changed

    def _review(self, candidate: Saved, message: str | None) -> bool:
        self.candidate = candidate
        self.phase = CalibrationPhase.REVIEW
        self.message = message
        self._dots = self._dots_png = None
        return True

    def _follow(self, board: np.ndarray | None) -> bool:
        if self.saved is None or board is None:
            self._drift_polls = 0
            return False
        if not self.saved.board.any():  # saved for another scenario: derive now
            self._pin_projector(board)
            self._accept(board)
            return True
        x0, y0, w, h = self.scenario.print_window
        corners = np.array([[x0, y0], [x0 + w, y0], [x0 + w, y0 + h], [x0, y0 + h]], np.float64)
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
        lens = self.saved.projector
        if lens is not None and self.saved.board.any():
            # The lens is fixed to the rig: it keeps its camera pixel as the board moves.
            x, y = transform(board @ np.linalg.inv(self.saved.board), lens.foot[None])[0]
            self.saved.projector = replace(lens, x=float(x), y=float(y))
        self.saved.board = board
        self.saved.map_to_proj = derive(self.saved.cam_to_proj, board)
        self.saved.save(self.path)
        self._drift_polls = 0
