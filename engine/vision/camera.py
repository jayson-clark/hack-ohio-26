"""The webcam: capture, marker detection and token tracking, on its own thread.

Everything slow (reading frames, detection, JPEG encoding) happens here, so
the engine's main loop only ever picks up the latest finished snapshot. OpenCV
releases the GIL while it works, so this doesn't starve the asyncio loop.

The source comes from CAMERA in .env:
  unset/empty  vision off (virtual table only)
  0, 1, ...    a camera index (macOS AVFoundation order; see the vision-camera skill)
  path         a video or still image, looped, for working without the table

Run this file directly to check what a camera index sees:
    uv run python -m vision.camera 0    # from engine/; writes camera-0.jpg with the overlay
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from protocol import CameraState, Token, VisionStatus
from scenario import Scenario
from vision import uvc
from vision.calibration import BoardHomography
from vision.geometry import Viewpoint
from vision.markers import CORNER_IDS, Detection, detect, make_detector, token_type_for
from vision.projector import DotFinder, DotSearch, PatternFinder, PatternProgress
from vision.tracking import MarkerTracker, measure

CAPTURE_SIZE = (1920, 1080)
FEED_WIDTH = 960  # px, the console's camera feed
ORTHO_WIDTH = 960  # px, the rectified top-down feed (board fills the frame)
ORTHO_SHARPEN = 0.8  # unsharp-mask amount on the ortho feed; 0 turns it off
ORTHO_SHARPEN_SIGMA = 1.2  # px
ORTHO_JPEG_QUALITY = 85  # q70 smeared the fine contour lines; ~100 KB a frame
FEED_HZ = 10
FEED_JPEG_QUALITY = 70
RETRY_S = 2.0
FILE_FPS = 30  # pace for still images (and videos that don't say)
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp"}

log = logging.getLogger("vision")


@dataclass
class Snapshot:
    tokens: list[Token] = field(default_factory=list)
    status: VisionStatus | None = None
    feed_seq: int = 0  # bumps with every new feed JPEG
    feed_jpeg: bytes = b""
    feed_size: tuple[int, int] = (0, 0)
    # camera -> map from the latest frame, only if it saw all four corners.
    board: np.ndarray | None = None
    camera: Viewpoint | None = None  # the camera's centre, with `board`
    pattern: PatternProgress | None = None  # while a projector pattern search runs


class CameraVision:
    def __init__(self, source: str, scenario: Scenario) -> None:
        self.source = source
        self._board = BoardHomography(scenario)
        self._tracker = MarkerTracker(scenario.width, scenario.height)
        self._detector = make_detector()
        self._fps = 0.0
        self._frame_size = (0, 0)
        self._markers_seen = 0
        self._lock = threading.Lock()
        self._snap = Snapshot(status=self._status(CameraState.NO_SIGNAL))
        self._want_pattern: int | DotSearch | None = None  # set from the main thread
        self._finder: PatternFinder | DotFinder | None = None
        self._lock_gray: np.ndarray | None = None  # the latest frame that saw all four corners
        self._ortho = SteadyOrtho(ORTHO_WIDTH)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="vision", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)

    def snapshot(self) -> Snapshot:
        with self._lock:
            return self._snap

    def find_pattern(self, search: int | DotSearch | None) -> None:
        """Look for the projector's calibration pattern (Calibrator.finding).
        Meanwhile tokens and the board stay as they were: the pattern is
        projected over them."""
        self._want_pattern = search

    # --- Capture thread -------------------------------------------------

    def _run(self) -> None:
        while not self._stop.is_set():
            frames = _open(self.source)
            if frames is None:
                log.warning("camera %r: can't open, retrying (on macOS, check Camera permission for your terminal)", self.source)
                self._publish(state=CameraState.NO_SIGNAL)
                self._stop.wait(RETRY_S)
                continue
            log.info("camera %r: open", self.source)
            if self.source.isdigit():
                uvc.apply(uvc.settings_from_env())  # opening reset them
            try:
                self._loop(frames)
            finally:
                frames.close()
            if not self._stop.is_set():
                log.warning("camera %r: lost signal, reopening", self.source)
                self._publish(state=CameraState.NO_SIGNAL)
                self._stop.wait(RETRY_S)

    def _loop(self, frames: "_Frames") -> None:
        last = time.monotonic()
        next_feed = 0.0
        while not self._stop.is_set():
            frame = frames.read()
            if frame is None:
                return
            now = time.monotonic()
            dt, last = now - last, now
            self._fps = 1 / dt if self._fps == 0 else 0.9 * self._fps + 0.1 / max(dt, 1e-3)
            self._frame_size = (frame.shape[1], frame.shape[0])

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
            search = self._want_pattern
            if search is not None:
                if isinstance(search, DotSearch):
                    if not isinstance(self._finder, DotFinder) or self._finder.request is not search:
                        self._finder = DotFinder(search, background=self._lock_gray)
                elif not isinstance(self._finder, PatternFinder) or self._finder.search != search:
                    # The calibrator starts the pattern only once it has a board
                    # lock with the projector black, so that lock's frame is
                    # the pattern's background.
                    self._finder = PatternFinder(search, background=self._lock_gray)
                progress = self._finder.feed(gray)
                feed = None
                if now >= next_feed:
                    next_feed = now + 1 / FEED_HZ
                    img = draw_pattern_overlay(frame, self._finder.last, progress, FEED_WIDTH)
                    feed = self._encode(img)
                self._publish(state=CameraState.OK, feed=feed, pattern=progress)
                continue
            self._finder = None

            detections = detect(self._detector, gray)
            self._markers_seen = len(detections)
            locked = self._board.update(detections, self._frame_size)
            if locked:
                self._lock_gray = gray
            sightings = measure(detections, self._board) if self._board.cam_to_map is not None else {}
            tokens = self._tracker.update(sightings)

            feed = None
            if now >= next_feed:
                next_feed = now + 1 / FEED_HZ
                # Any solve, even one held from an earlier frame: a corner
                # missed for a frame shouldn't flip the feed to the raw view.
                if self._board.cam_to_map is not None:
                    feed = self._encode(self._ortho.draw(frame, self._board, tokens), ORTHO_JPEG_QUALITY)
                else:
                    feed = self._encode(draw_overlay(frame, detections, self._board, tokens, FEED_WIDTH))
            board = self._board.cam_to_map.copy() if locked else None
            self._publish(state=CameraState.OK, tokens=tokens, feed=feed, board=board,
                          camera=self._board.camera if locked else None)

    def _publish(self, state: CameraState, tokens: list[Token] | None = None, feed: tuple[bytes, tuple[int, int]] | None = None,
                 board: np.ndarray | None = None, camera: Viewpoint | None = None,
                 pattern: PatternProgress | None = None) -> None:
        if state != CameraState.OK:
            self._fps = 0.0
            self._markers_seen = 0
            self._board.corners_seen = []
        with self._lock:
            prev = self._snap
            self._snap = Snapshot(
                # A lost camera keeps its last tokens, like a hand over the
                # table, rather than wiping every crew off the map.
                tokens=prev.tokens if tokens is None else tokens,
                status=self._status(state),
                feed_seq=prev.feed_seq + (feed is not None),
                feed_jpeg=feed[0] if feed else prev.feed_jpeg,
                feed_size=feed[1] if feed else prev.feed_size,
                board=board,
                camera=camera,
                pattern=pattern,
            )

    def _status(self, state: CameraState) -> VisionStatus:
        return VisionStatus(
            camera=state,
            source=self.source,
            fps=round(self._fps, 1),
            frame_width=self._frame_size[0],
            frame_height=self._frame_size[1],
            markers_seen=self._markers_seen,
            corners_seen=list(self._board.corners_seen),
            board_found=self._board.cam_to_map is not None,
        )

    def _encode(self, img: np.ndarray, quality: int = FEED_JPEG_QUALITY) -> tuple[bytes, tuple[int, int]]:
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
        return (buf.tobytes() if ok else b""), (img.shape[1], img.shape[0])


# --- Overlay ------------------------------------------------------------------

CORNER_COLOR = (255, 200, 0)  # BGR
TOKEN_COLOR = (0, 220, 255)
OTHER_COLOR = (160, 160, 160)
BOARD_COLOR = (80, 220, 80)
STALE_BOARD_COLOR = (0, 160, 255)


def draw_overlay(frame: np.ndarray, detections: list[Detection], board: BoardHomography, tokens: list[Token], width: int) -> np.ndarray:
    """A downscaled copy of `frame` with markers, the map outline and placed tokens."""
    scale = width / frame.shape[1]
    img = cv2.resize(frame, (width, round(frame.shape[0] * scale)), interpolation=cv2.INTER_AREA)
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)

    outline = board.map_outline_in_camera()
    if outline is not None:
        locked = len(board.corners_seen) == len(CORNER_IDS)
        cv2.polylines(img, [np.round(outline * scale).astype(np.int32)], True, BOARD_COLOR if locked else STALE_BOARD_COLOR, 2, cv2.LINE_AA)

    corner_names = {i: name for name, i in CORNER_IDS.items()}
    for d in detections:
        pts = np.round(d.corners * scale).astype(np.int32)
        if d.id in corner_names:
            color, label = CORNER_COLOR, corner_names[d.id]
        elif (kind := token_type_for(d.id)) is not None:
            color, label = TOKEN_COLOR, f"{kind.value} {d.id}"
        else:
            color, label = OTHER_COLOR, f"? {d.id}"
        cv2.polylines(img, [pts], True, color, 2, cv2.LINE_AA)
        cv2.circle(img, tuple(pts[0]), 3, color, -1, cv2.LINE_AA)  # marks the marker's top-left
        x, y = pts[:, 0].min(), pts[:, 1].min() - 6
        cv2.putText(img, label, (int(x), int(y)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(img, label, (int(x), int(y)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)

    # Placed (debounced) tokens, at their smoothed map position.
    if board.cam_to_map is not None and tokens:
        inv = np.linalg.inv(board.cam_to_map)
        pts = cv2.perspectiveTransform(np.array([[[t.x, t.y]] for t in tokens], np.float32), inv).reshape(-1, 2)
        for p in pts * scale:
            cv2.circle(img, (round(p[0]), round(p[1])), 10, TOKEN_COLOR, 2, cv2.LINE_AA)
    return img


def draw_ortho(frame: np.ndarray, board: BoardHomography, tokens: list[Token], width: int,
               table: np.ndarray | None = None) -> np.ndarray:
    """A top-down orthophoto of the board: the camera frame rectified and
    cropped to the map grid, terrain lean taken out, with placed tokens drawn
    at their map positions. `table` is a prebuilt remap (SteadyOrtho) at this
    width; otherwise it's built from `board`. Falls back to draw_overlay if
    the board can't be rectified."""
    out_h = round(width * board.height / board.width)
    out_size = (width, out_h)
    if table is None:
        table = board.orthophoto_remap(out_size)
    if table is None:
        return draw_overlay(frame, [], board, tokens, width)
    img = cv2.remap(frame, table[..., 0], table[..., 1], cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT)
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    # The board is only ~2.5 camera px per cell and the feed upsamples it ~1.5x,
    # so edges come out soft; a light unsharp mask brings back the contours and
    # labels (2.5x the edge detail on the real rig, under 1 ms).
    if ORTHO_SHARPEN > 0:
        blur = cv2.GaussianBlur(img, (0, 0), ORTHO_SHARPEN_SIGMA)
        img = cv2.addWeighted(img, 1 + ORTHO_SHARPEN, blur, -ORTHO_SHARPEN, 0)

    # Placed (debounced) tokens, at their smoothed map position.
    if tokens:
        pts = board.map_to_ortho(np.array([[t.x, t.y] for t in tokens], np.float64), out_size)
        for p in pts:
            cv2.circle(img, (round(p[0]), round(p[1])), 10, TOKEN_COLOR, 2, cv2.LINE_AA)
    return img


# How far (camera px) the board's outline must move before the feed re-warps.
# Corner centres jitter ~0.4 px frame to frame and the camera pose by ~2 cells,
# which re-warping every frame turns into a shimmer; a bumped board or camera
# moves several px and gets through.
ORTHO_DEADBAND_PX = 2.0


class SteadyOrtho:
    """The orthophoto feed with one warp held while the board stays put."""

    def __init__(self, width: int) -> None:
        self.width = width
        self.table: np.ndarray | None = None
        self.outline: np.ndarray | None = None  # board outline (camera px) the table was built from
        self.rebuilds = 0

    def update(self, board: BoardHomography) -> np.ndarray | None:
        outline = board.map_outline_in_camera()
        if outline is None:
            return self.table
        if self.table is None or np.abs(outline - self.outline).max() > ORTHO_DEADBAND_PX:
            self.table = board.orthophoto_remap((self.width, round(self.width * board.height / board.width)))
            self.outline = outline
            self.rebuilds += 1
        return self.table

    def draw(self, frame: np.ndarray, board: BoardHomography, tokens: list[Token]) -> np.ndarray:
        return draw_ortho(frame, board, tokens, self.width, self.update(board))


PATTERN_COLOR = (255, 0, 255)


def draw_pattern_overlay(frame: np.ndarray, corners: np.ndarray | None, progress: PatternProgress, width: int) -> np.ndarray:
    """The feed while the projector pattern is up: the pattern corners found this frame."""
    scale = width / frame.shape[1]
    img = cv2.resize(frame, (width, round(frame.shape[0] * scale)), interpolation=cv2.INTER_AREA)
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    if corners is not None:
        for p in corners * scale:
            cv2.circle(img, (round(p[0]), round(p[1])), 3, PATTERN_COLOR, -1, cv2.LINE_AA)
    label = f"{'dots' if progress.dots else 'pattern'}: {progress.corners} found, frame {progress.frames}"
    cv2.putText(img, label, (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 4, cv2.LINE_AA)
    cv2.putText(img, label, (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, PATTERN_COLOR, 2, cv2.LINE_AA)
    return img


# --- Frame sources --------------------------------------------------------------

class _Frames:
    def read(self) -> np.ndarray | None: ...
    def close(self) -> None: ...


class _Capture(_Frames):
    def __init__(self, cap: cv2.VideoCapture, pace_fps: float | None) -> None:
        self._cap = cap
        self._period = 1 / pace_fps if pace_fps else 0.0
        self._next = time.monotonic()

    def read(self) -> np.ndarray | None:
        ok, frame = self._cap.read()
        if not ok and self._period:  # a video file: loop it
            self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = self._cap.read()
        if self._period:
            self._next += self._period
            time.sleep(max(0.0, self._next - time.monotonic()))
        return frame if ok else None

    def close(self) -> None:
        self._cap.release()


class _Still(_Frames):
    def __init__(self, img: np.ndarray) -> None:
        self._img = img

    def read(self) -> np.ndarray | None:
        time.sleep(1 / FILE_FPS)
        return self._img

    def close(self) -> None:
        pass


def _open(source: str) -> _Frames | None:
    if source.isdigit():
        cap = cv2.VideoCapture(int(source), cv2.CAP_AVFOUNDATION)
        if not cap.isOpened():
            return None
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAPTURE_SIZE[0])
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAPTURE_SIZE[1])
        return _Capture(cap, None)
    path = Path(source).expanduser()
    if not path.is_absolute():
        # .env paths are written relative to the repo root.
        path = Path(__file__).resolve().parents[2] / path
    if path.suffix.lower() in IMAGE_EXTS:
        img = cv2.imread(str(path))
        return _Still(img) if img is not None else None
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return None
    return _Capture(cap, cap.get(cv2.CAP_PROP_FPS) or FILE_FPS)


def from_env(source: str | None, scenario: Scenario) -> CameraVision | None:
    if not source:
        return None
    vision = CameraVision(source, scenario)
    vision.start()
    return vision


if __name__ == "__main__":
    import sys

    from scenario import load_scenario

    src = sys.argv[1] if len(sys.argv) > 1 else "0"
    scen = load_scenario(sys.argv[2] if len(sys.argv) > 2 else "paradise")
    frames = _open(src)
    if frames is None:
        sys.exit(f"can't open camera {src!r}")
    if src.isdigit():
        uvc.apply(uvc.settings_from_env())
    board = BoardHomography(scen)
    detector = make_detector()
    # A few frames first: webcams return dark frames while auto-exposure settles.
    for _ in range(15):
        frame = frames.read()
    frames.close()
    if frame is None:
        sys.exit(f"camera {src!r} returned no frames")
    dets = detect(detector, cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
    board.update(dets, (frame.shape[1], frame.shape[0]))
    print(f"{frame.shape[1]}x{frame.shape[0]}, markers {sorted(d.id for d in dets)}, corners {board.corners_seen}")
    if board.camera is not None:
        cam, cell = board.camera, board.surface.cell_mm
        north = scen.terrain["model"]["height_mm"] - cam.y * cell
        print(f"  camera lens at about {cam.x * cell:.0f} mm east, {north:.0f} mm north of the terrain's SW corner, "
              f"{cam.h + scen.terrain['markers']['marker_top_z_mm']:.0f} mm up")
    if board.cam_to_map is not None:
        for i, s in measure(dets, board).items():
            print(f"  marker {i} ({token_type_for(i)}): map ({s.x:.1f}, {s.y:.1f}), angle {np.degrees(s.angle):.0f} deg")
    out = f"camera-{Path(src).stem}.jpg"
    cv2.imwrite(out, draw_overlay(frame, dets, board, [], frame.shape[1]))
    print(f"wrote {out}")
    if board.cam_to_map is not None:
        ortho = f"camera-{Path(src).stem}-ortho.jpg"
        cv2.imwrite(ortho, draw_ortho(frame, board, [], ORTHO_WIDTH))
        print(f"wrote {ortho} (top-down, terrain lean corrected)")
