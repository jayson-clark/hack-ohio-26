import math
import time

import cv2
import numpy as np
import pytest

from protocol import CameraState, TokenSource, TokenType
from scenario import load_scenario
from vision.calibration import BoardHomography
from vision import geometry
from vision.camera import CameraVision
from vision.markers import CORNER_IDS, DICTIONARY, Detection, detect, make_detector, token_type_for
from vision.tracking import APPEAR_FRAMES, SNAP_CELLS, VANISH_FRAMES, MarkerTracker, Sighting, measure

PX_PER_CELL = 5
MARGIN = 30  # cells around the map, room for the corner markers
TOKEN_SIZE = 12.0  # cells (~15 mm)
# Where the board render's corners land in a 1920x1080 "camera" image: a
# slightly keystoned, off-centre view like a real overhead webcam.
CAMERA_QUAD = np.float32([[260, 50], [1690, 110], [1630, 1040], [310, 990]])

TOKENS = [  # marker id, map x, y, angle (deg clockwise from +x)
    (10, 40.0, 30.0, 0.0),
    (21, 128.5, 96.25, 37.0),
    (33, 200.0, 150.0, -120.0),
    (44, 20.0, 170.0, 90.0),
]


@pytest.fixture(scope="module")
def scenario():
    return load_scenario("paradise")


@pytest.fixture(autouse=True)
def flat_camera(monkeypatch):
    """These renders paste markers onto a flat picture of the board, which no
    real camera sees, so the height correction is off (tests/test_geometry.py
    covers it with a 3D camera)."""
    monkeypatch.setattr(geometry, "CAMERA_FOCAL", None)


def _paste_marker(canvas, marker_id, cx, cy, size_cells, angle_deg):
    dictionary = cv2.aruco.getPredefinedDictionary(DICTIONARY)
    side = 120
    img = cv2.aruco.generateImageMarker(dictionary, marker_id, side)
    a = math.radians(angle_deg)
    u = np.array([math.cos(a), math.sin(a)])  # marker +x, map y down
    v = np.array([-math.sin(a), math.cos(a)])  # marker +y
    c = (np.array([cx, cy]) + MARGIN) * PX_PER_CELL - 0.5  # OpenCV: pixel i is centred on i
    h = size_cells * PX_PER_CELL / 2
    dst = np.float32([c - h * u - h * v, c + h * u - h * v, c + h * u + h * v, c - h * u + h * v])
    src = np.float32([[0, 0], [side, 0], [side, side], [0, side]]) - 0.5
    M = cv2.getPerspectiveTransform(src, dst)
    size = (canvas.shape[1], canvas.shape[0])
    warped = cv2.warpPerspective(img, M, size, flags=cv2.INTER_LINEAR)
    mask = cv2.warpPerspective(np.full_like(img, 255), M, size, flags=cv2.INTER_NEAREST)
    canvas[mask > 0] = warped[mask > 0]


def render_camera_image(scenario, tokens=TOKENS, hide_corner=None):
    """A grayscale 'webcam frame' of the board with the given token markers."""
    w = (scenario.width + 2 * MARGIN) * PX_PER_CELL
    h = (scenario.height + 2 * MARGIN) * PX_PER_CELL
    canvas = np.full((h, w), 235, np.uint8)  # light-grey board
    # The terrain itself, a bit darker, so the map edge is visible.
    x0, y0 = MARGIN * PX_PER_CELL, MARGIN * PX_PER_CELL
    canvas[y0 : y0 + scenario.height * PX_PER_CELL, x0 : x0 + scenario.width * PX_PER_CELL] = 205
    cells_per_mm = scenario.width / scenario.terrain["model"]["width_mm"]
    corner_size = scenario.terrain["markers"]["marker_size_mm"] * cells_per_mm
    for c in scenario.terrain["markers"]["corners"]:
        if c["corner"] != hide_corner:
            _paste_marker(canvas, CORNER_IDS[c["corner"]], *c["center_map"], corner_size, 0)
    for marker_id, x, y, angle in tokens:
        _paste_marker(canvas, marker_id, x, y, TOKEN_SIZE, angle)
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]]) - 0.5
    H = cv2.getPerspectiveTransform(src, CAMERA_QUAD)
    return cv2.warpPerspective(canvas, H, (1920, 1080), borderValue=40)


def _angle_diff(a, b):
    return abs((a - b + math.pi) % (2 * math.pi) - math.pi)


def test_token_ids_map_to_types():
    assert token_type_for(10) == TokenType.CREW
    assert token_type_for(24) == TokenType.FIREBREAK
    assert token_type_for(30) == TokenType.WATER
    assert token_type_for(44) == TokenType.BUS
    assert token_type_for(0) is None  # a corner
    assert token_type_for(17) is None  # in the crew block, but never printed
    assert token_type_for(50) is None


def test_markers_land_at_their_map_positions(scenario):
    frame = render_camera_image(scenario)
    board = BoardHomography(scenario)
    detections = detect(make_detector(), frame)
    assert board.update(detections)
    assert board.corners_seen == ["NW", "NE", "SE", "SW"]

    sightings = measure(detections, board)
    assert sorted(sightings) == [t[0] for t in TOKENS]
    for marker_id, x, y, angle in TOKENS:
        s = sightings[marker_id]
        assert math.hypot(s.x - x, s.y - y) < 0.2, (marker_id, s)
        assert _angle_diff(s.angle, math.radians(angle)) < math.radians(2), (marker_id, s)


def test_board_keeps_last_homography_when_a_corner_is_covered(scenario):
    board = BoardHomography(scenario)
    detector = make_detector()
    board.update(detect(detector, render_camera_image(scenario)))
    solved = board.cam_to_map.copy()

    assert not board.update(detect(detector, render_camera_image(scenario, hide_corner="SE")))
    assert board.corners_seen == ["NW", "NE", "SW"]
    np.testing.assert_array_equal(board.cam_to_map, solved)


def test_board_rejects_swapped_corners(scenario):
    board = BoardHomography(scenario)
    dets = detect(make_detector(), render_camera_image(scenario))
    swap = {CORNER_IDS["SE"]: CORNER_IDS["SW"], CORNER_IDS["SW"]: CORNER_IDS["SE"]}
    assert not board.update([Detection(swap.get(d.id, d.id), d.corners) for d in dets])
    assert board.misplaced and board.cam_to_map is None
    assert board.update(dets)
    assert not board.misplaced


def test_board_needs_all_four_corners_first(scenario):
    board = BoardHomography(scenario)
    board.update(detect(make_detector(), render_camera_image(scenario, hide_corner="NW")))
    assert board.cam_to_map is None


def test_tracker_debounces_appear_and_vanish():
    tracker = MarkerTracker(256, 192)
    seen = {10: Sighting(50, 50, 0)}
    for _ in range(APPEAR_FRAMES - 1):
        assert tracker.update(seen) == []
    [token] = tracker.update(seen)
    assert (token.id, token.token_type, token.source) == ("m10", TokenType.CREW, TokenSource.VISION)

    for _ in range(VANISH_FRAMES):
        assert len(tracker.update({})) == 1  # a hand over it doesn't remove it
    assert tracker.update({}) == []


def test_tracker_restarts_count_when_not_yet_placed():
    tracker = MarkerTracker(256, 192)
    seen = {10: Sighting(50, 50, 0)}
    for _ in range(APPEAR_FRAMES - 1):
        tracker.update(seen)
    tracker.update({})  # a flicker before it's placed
    for _ in range(APPEAR_FRAMES - 1):
        assert tracker.update(seen) == []


def test_tracker_ignores_jitter_and_snaps_big_moves():
    tracker = MarkerTracker(256, 192)
    for _ in range(APPEAR_FRAMES):
        tokens = tracker.update({10: Sighting(50, 50, 0)})
    [token] = tokens
    rng = np.random.default_rng(0)
    for _ in range(30):
        jx, jy = rng.normal(0, 0.03, 2)
        [jittered] = tracker.update({10: Sighting(50 + jx, 50 + jy, rng.normal(0, 0.005))})
        assert (jittered.x, jittered.y, jittered.angle) == (token.x, token.y, token.angle)

    [moved] = tracker.update({10: Sighting(50 + SNAP_CELLS + 5, 80, 1.0)})
    assert (moved.x, moved.y, moved.angle) == (50 + SNAP_CELLS + 5, 80, 1.0)


def test_tracker_drops_off_map_and_unknown_markers():
    tracker = MarkerTracker(256, 192)
    for _ in range(APPEAR_FRAMES):
        tokens = tracker.update({10: Sighting(-3, 50, 0), 11: Sighting(256, 10, 0), 12: Sighting(255.9, 191.9, 0)})
    assert [t.id for t in tokens] == ["m12"]


def test_camera_thread_reports_tokens_from_a_still_image(scenario, tmp_path):
    path = tmp_path / "board.png"
    cv2.imwrite(str(path), render_camera_image(scenario))
    vision = CameraVision(str(path), scenario)
    vision.start()
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            snap = vision.snapshot()
            if len(snap.tokens) == len(TOKENS) and snap.feed_jpeg:
                break
            time.sleep(0.05)
    finally:
        vision.stop()
    assert sorted(t.id for t in snap.tokens) == sorted(f"m{t[0]}" for t in TOKENS)
    assert snap.status.camera == CameraState.OK
    assert snap.status.board_found
    assert snap.feed_jpeg[:2] == b"\xff\xd8"  # a JPEG
    assert snap.feed_size[0] == 960
