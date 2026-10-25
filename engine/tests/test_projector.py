import time

import cv2
import numpy as np
import pytest

from protocol import CalibrationPhase
from scenario import load_scenario
import vision.projector as projector
from vision.camera import CameraVision
from vision.projector import (
    FOLLOW_POLLS,
    FRAMES_NEEDED,
    PATTERN_SIZE,
    Calibrator,
    PatternFinder,
    PatternFit,
    PatternProgress,
    derive,
    pattern_png,
    transform,
)

# Where the projector frame's corners land in a 1920x1080 "camera" image:
# keystoned and off-centre, like a projector beside the webcam.
PROJ_QUAD = np.float32([[180, 90], [1760, 40], [1700, 1010], [240, 1050]])
# camera px -> map cells, for a board seen roughly where the projector lands.
BOARD = cv2.getPerspectiveTransform(
    np.float32([[300, 150], [1600, 140], [1580, 1000], [320, 990]]), np.float32([[0, 0], [256, 0], [256, 192], [0, 192]])
).astype(np.float64)


@pytest.fixture(scope="module")
def scenario():
    return load_scenario("paradise")


@pytest.fixture(autouse=True)
def no_settle(monkeypatch):
    monkeypatch.setattr(projector, "BLACK_SETTLE_S", 0.0)


def start(cal: Calibrator) -> None:
    """Calibrate, and see the board with the projector black."""
    cal.step("start", has_camera=True)
    cal.poll(None, BOARD)


def ring_only(cal: Calibrator) -> None:
    """The dot grid after the ring isn't seen: review falls back to the ring."""
    assert cal.finding == cal.search and cal.phase == CalibrationPhase.PATTERN
    cal.poll(PatternProgress(cal.search, 0, 0, None, failed=True, dots=True), None)


def proj_to_cam() -> np.ndarray:
    """Normalised projector coords -> camera px for PROJ_QUAD."""
    return cv2.getPerspectiveTransform(np.float32([[0, 0], [1, 0], [1, 1], [0, 1]]), PROJ_QUAD).astype(np.float64)


def render_pattern_seen() -> np.ndarray:
    """A grayscale camera frame of the projected pattern, a bit washed out."""
    pattern = cv2.imdecode(np.frombuffer(pattern_png(), np.uint8), cv2.IMREAD_GRAYSCALE)
    w, h = PATTERN_SIZE
    # Pattern pixel edges -> camera px (OpenCV: pixel i is centred on i).
    px_to_norm = np.diag([1 / w, 1 / h, 1.0])
    shift = np.array([[1, 0, 0.5], [0, 1, 0.5], [0, 0, 1]])
    unshift = np.array([[1, 0, -0.5], [0, 1, -0.5], [0, 0, 1]])
    H = unshift @ proj_to_cam() @ px_to_norm @ shift
    seen = cv2.warpPerspective(pattern, H, (1920, 1080), flags=cv2.INTER_AREA, borderValue=30)
    return (40 + seen.astype(np.float32) * 0.7).astype(np.uint8)


def test_pattern_finder_recovers_camera_to_projector():
    finder = PatternFinder(search=1)
    gray = render_pattern_seen()
    for _ in range(FRAMES_NEEDED):
        progress = finder.feed(gray)
    assert progress.fit is not None
    assert progress.corners == 8
    expected = np.linalg.inv(proj_to_cam())
    pts = PROJ_QUAD.reshape(-1, 2).astype(np.float64) * 0.9 + 100
    err = (transform(progress.fit.cam_to_proj, pts) - transform(expected, pts)) * PATTERN_SIZE
    assert np.abs(err).max() < 1.5  # pattern px
    assert progress.fit.error_px < 1.5


def test_pattern_finder_needs_the_pattern():
    finder = PatternFinder(search=1)
    for _ in range(FRAMES_NEEDED + 2):
        progress = finder.feed(np.full((1080, 1920), 128, np.uint8))
    assert progress.frames == 0 and progress.fit is None


def _fit() -> PatternFit:
    return PatternFit(np.linalg.inv(proj_to_cam()), 0.8, 90)


def test_calibrator_wizard_flow(scenario, tmp_path):
    path = tmp_path / "calibration.json"
    cal = Calibrator(scenario, path)
    assert cal.phase == CalibrationPhase.NONE
    assert cal.message_model().map_to_proj is None

    cal.step("start", has_camera=False)
    assert cal.phase == CalibrationPhase.NONE and "CAMERA" in cal.message
    # The projector goes black until the corners are seen, then shows the pattern.
    cal.step("start", has_camera=True)
    assert cal.phase == CalibrationPhase.PATTERN and cal.finding is None and "corner" in cal.message
    black = cal.message_model().pattern
    assert black.startswith("data:image/png;base64,")
    assert not cal.poll(None, None)
    assert cal.poll(None, BOARD)
    assert cal.finding == cal.search and cal.message is None
    assert cal.message_model().pattern != black
    # A result from an older search is ignored.
    assert not cal.poll(PatternProgress(cal.search - 1, 90, FRAMES_NEEDED, _fit()), None)
    assert cal.phase == CalibrationPhase.PATTERN
    assert cal.poll(PatternProgress(cal.search, 90, FRAMES_NEEDED, _fit()), None)
    # Then the dot grid; the ring's search stays on while the projector switches.
    dots = cal.message_model().pattern
    assert cal.phase == CalibrationPhase.PATTERN and dots not in (black, None)
    ring_only(cal)
    assert cal.phase == CalibrationPhase.REVIEW and cal.finding is None and "ring" in cal.message

    msg = cal.message_model()
    h = np.array(msg.map_to_proj).reshape(3, 3)
    # The map's corners land where the board's corners are in the projector.
    map_corners = np.array([[0, 0], [256, 0], [256, 192], [0, 192]], float)
    cam_corners = transform(np.linalg.inv(BOARD), map_corners)
    assert np.allclose(transform(h, map_corners), transform(_fit().cam_to_proj, cam_corners), atol=1e-6)
    assert not path.exists()

    cal.step("save", has_camera=True)
    assert cal.phase == CalibrationPhase.CALIBRATED and path.exists()

    again = Calibrator(scenario, path)
    assert again.phase == CalibrationPhase.CALIBRATED
    assert np.allclose(again.message_model().map_to_proj, msg.map_to_proj)

    again.step("clear", has_camera=True)
    assert again.phase == CalibrationPhase.NONE and not path.exists()


def test_cancel_keeps_the_saved_calibration(scenario, tmp_path):
    cal = Calibrator(scenario, tmp_path / "calibration.json")
    start(cal)
    cal.poll(PatternProgress(cal.search, 90, FRAMES_NEEDED, _fit()), None)
    ring_only(cal)
    cal.step("save", has_camera=True)
    saved = cal.message_model().map_to_proj

    start(cal)
    other = PatternFit(_fit().cam_to_proj @ np.diag([1.1, 1.0, 1.0]), 0.8, 90)
    cal.poll(PatternProgress(cal.search, 90, FRAMES_NEEDED, other), None)
    ring_only(cal)
    assert cal.phase == CalibrationPhase.REVIEW and cal.message_model().map_to_proj != saved
    cal.step("cancel", has_camera=True)
    assert cal.phase == CalibrationPhase.CALIBRATED
    assert cal.message_model().map_to_proj == saved


def test_calibrator_follows_a_moved_board(scenario, tmp_path):
    cal = Calibrator(scenario, tmp_path / "calibration.json")
    start(cal)
    cal.poll(PatternProgress(cal.search, 90, FRAMES_NEEDED, _fit()), None)
    ring_only(cal)
    cal.step("save", has_camera=True)
    before = np.array(cal.message_model().map_to_proj).reshape(3, 3)

    # Jitter well under a projector pixel: ignored.
    jitter = np.array([[1, 0, 0.01], [0, 1, -0.01], [0, 0, 1]]) @ BOARD
    assert not any(cal.poll(None, jitter) for _ in range(FOLLOW_POLLS * 2))

    # The table slides: the board moves 30 camera px right.
    moved = BOARD @ np.array([[1, 0, -30], [0, 1, 0], [0, 0, 1]], float)
    results = [cal.poll(None, moved) for _ in range(FOLLOW_POLLS)]
    assert results == [False] * (FOLLOW_POLLS - 1) + [True]
    after = np.array(cal.message_model().map_to_proj).reshape(3, 3)
    assert not np.allclose(after, before)
    assert np.allclose(after, derive(_fit().cam_to_proj, moved))
    assert np.allclose(Calibrator(scenario, tmp_path / "calibration.json").saved.map_to_proj, after)


def test_camera_thread_finds_the_pattern(scenario, tmp_path):
    path = tmp_path / "pattern.png"
    cv2.imwrite(str(path), render_pattern_seen())
    vision = CameraVision(str(path), scenario)
    vision.start()
    try:
        vision.find_pattern(7)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            snap = vision.snapshot()
            if snap.pattern is not None and snap.pattern.fit is not None:
                break
            time.sleep(0.05)
    finally:
        vision.stop()
    assert snap.pattern.search == 7
    assert snap.pattern.fit is not None
    assert snap.feed_jpeg[:2] == b"\xff\xd8"
