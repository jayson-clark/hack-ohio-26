import cv2
import numpy as np
import pytest

from scenario import load_scenario
from vision.calibration import BoardHomography
from vision.geometry import CAMERA_FOCAL, Surface, Viewpoint, onto_surface, projector_from_env, to_plane
from vision.markers import CORNER_IDS, Detection
from vision.projector import (
    PATTERN_SIZE,
    PatternFit,
    derive,
    dot_centres,
    dots_png,
    find_dots,
    fit_on_terrain,
    pattern_corners,
    solve_lens,
    transform,
)
from vision.tracking import TOKEN_TOP_MM, measure

FRAME = (1920, 1080)


@pytest.fixture(scope="module")
def scenario():
    return load_scenario("paradise")


@pytest.fixture(scope="module")
def surface(scenario):
    return Surface(scenario)


class Camera:
    """A pinhole camera over the board with the C920's nominal focal length,
    a little off-centre and tilted, like the real rig."""

    def __init__(self, cell_mm: float, centre_mm=(260.0, 110.0, 730.0), tilt=(0.06, -0.09, 0.03)):
        f = CAMERA_FOCAL * FRAME[0]
        self.k = np.array([[f, 0, FRAME[0] / 2], [0, f, FRAME[1] / 2], [0, 0, 1]])
        # Map frame in mm: x east, y south, z down into the table. Looking
        # straight down, the camera's axes are the map's; then a small tilt.
        self.r, _ = cv2.Rodrigues(np.array(tilt, float))
        self.c = np.array([centre_mm[0], centre_mm[1], -centre_mm[2]])
        self.cell_mm = cell_mm

    def px(self, pts: np.ndarray, heights_mm: np.ndarray) -> np.ndarray:
        """Map points at heights above the marker plane -> image pixels."""
        pts = np.asarray(pts, float).reshape(-1, 2)
        world = np.column_stack([pts * self.cell_mm, -np.asarray(heights_mm, float).reshape(-1)])
        cam = (self.r @ (world - self.c).T).T
        uv = (self.k @ cam.T).T
        return uv[:, :2] / uv[:, 2:]

    def viewpoint(self) -> Viewpoint:
        return Viewpoint(self.c[0] / self.cell_mm, self.c[1] / self.cell_mm, -self.c[2])


def corner_detections(scenario, cam: Camera) -> list[Detection]:
    half = scenario.terrain["markers"]["marker_size_mm"] / scenario.terrain["grid"]["cell_size_mm"] / 2
    out = []
    for c in scenario.terrain["markers"]["corners"]:
        cx, cy = c["center_map"]
        sq = np.array([[cx - half, cy - half], [cx + half, cy - half], [cx + half, cy + half], [cx - half, cy + half]])
        out.append(Detection(CORNER_IDS[c["corner"]], cam.px(sq, np.zeros(4)).astype(np.float32)))
    return out


def test_surface_heights_match_the_print(scenario, surface):
    t = scenario.terrain
    floor = t["model"]["base_mm"] - t["markers"]["marker_top_z_mm"]  # the base's top, the lowest point
    assert floor <= surface.mm.min() < floor + 1
    assert surface.mm.max() == pytest.approx(floor + t["model"]["relief_mm"], abs=1)
    # Off the print it's the bare table, below the marker plane.
    assert surface.at(np.array([[-5.0, 10.0], [300.0, 50.0]])).tolist() == [surface.floor] * 2


def test_plane_and_surface_round_trip(surface):
    view = Viewpoint(140.0, 210.0, 650.0)
    rng = np.random.default_rng(1)
    ground = rng.uniform([2, 2], [254, 190], (200, 2))
    plane = to_plane(view, ground, surface.at(ground))
    back, heights = onto_surface(view, plane, surface)
    assert np.abs(back - ground).max() < 0.02
    assert np.allclose(heights, surface.at(ground), atol=0.05)


def test_camera_is_placed_from_the_corner_markers(scenario):
    cam = Camera(scenario.terrain["grid"]["cell_size_mm"])
    board = BoardHomography(scenario)
    assert board.update(corner_detections(scenario, cam), FRAME)
    got, want = board.camera, cam.viewpoint()
    assert abs(got.x - want.x) < 0.5 and abs(got.y - want.y) < 0.5  # cells
    assert abs(got.h - want.h) < 3  # mm


def test_tokens_on_hills_read_where_they_sit(scenario, surface):
    cam = Camera(scenario.terrain["grid"]["cell_size_mm"])
    board = BoardHomography(scenario)
    board.update(corner_detections(scenario, cam), FRAME)
    rng = np.random.default_rng(2)
    spots = rng.uniform([10, 10], [246, 182], (40, 2))
    seen = cam.px(spots, surface.at(spots) + TOKEN_TOP_MM)
    flat = board.to_map(seen)
    fixed = board.to_surface(seen, TOKEN_TOP_MM)
    assert np.linalg.norm(flat - spots, axis=1).max() > 3  # cells: what the plane alone gets wrong
    assert np.linalg.norm(fixed - spots, axis=1).max() < 0.1

    # measure() goes through the same correction.
    half = 5.0
    sq = np.array([[-half, -half], [half, -half], [half, half], [-half, half]])
    x, y = spots[0]
    det = Detection(10, cam.px(spots[0] + sq, np.full(4, surface.at(spots[:1])[0] + TOKEN_TOP_MM)).astype(np.float32))
    s = measure([det], board)[10]
    assert abs(s.x - x) < 0.15 and abs(s.y - y) < 0.15


def test_calibration_fit_takes_the_terrain_out(scenario, surface):
    cam = Camera(scenario.terrain["grid"]["cell_size_mm"])
    board = BoardHomography(scenario)
    board.update(corner_detections(scenario, cam), FRAME)
    lens = Viewpoint(150.0, 230.0, 620.0)
    # The truth: map (marker plane) -> pattern px, the board filling the middle.
    true_h = cv2.getPerspectiveTransform(
        np.float32([[0, 0], [256, 0], [256, 192], [0, 192]]), np.float32([[250, 60], [1700, 90], [1680, 1030], [230, 1000]])
    ).astype(np.float64)
    # Each ring corner lands where the lens's ray first meets the terrain; the camera sees it there.
    target = pattern_corners()
    ground, heights = onto_surface(lens, transform(np.linalg.inv(true_h), target), surface)
    seen = cam.px(ground, heights)
    flat_h, _ = cv2.findHomography(seen, target, 0)
    norm = np.diag([1 / PATTERN_SIZE[0], 1 / PATTERN_SIZE[1], 1.0])
    fit = PatternFit(norm @ flat_h, 0.0, 8, seen, target / PATTERN_SIZE)

    map_to_proj, cam_to_proj, err = fit_on_terrain(fit, board.cam_to_map, surface, board.camera, lens)
    probe = np.array([[0, 0], [256, 0], [256, 192], [0, 192], [128, 96]], float)
    want = transform(true_h, probe)
    got = transform(np.linalg.inv(norm) @ map_to_proj, probe)
    flat = transform(np.linalg.inv(norm) @ derive(fit.cam_to_proj, board.cam_to_map), probe)
    assert np.abs(flat - want).max() > 10  # pattern px: the flat fit is off
    assert np.abs(got - want).max() < 1.5 and err < 1.0
    # The camera -> projector kept for following a moved board gives the same map -> projector.
    assert np.allclose(derive(cam_to_proj, board.cam_to_map), map_to_proj, atol=1e-9)


def test_projector_position_from_env(scenario):
    t = scenario.terrain
    cell = t["grid"]["cell_size_mm"]
    v = projector_from_env(f"{t['model']['width_mm'] / 2}, 0, 706", scenario)
    assert v.x == pytest.approx(scenario.width / 2) and v.y == pytest.approx(scenario.height)
    assert v.h == pytest.approx(706 - t["markers"]["marker_top_z_mm"])
    assert projector_from_env("", scenario) is None
    with pytest.raises(ValueError):
        projector_from_env("12,34", scenario)
    assert cell > 0


# The real rig's projector: low and off the south-west corner, shining across
# with lens shift, onto the board filling the middle of its frame.
LENS = Viewpoint(46.0, 228.0, 534.0)
MAP_TO_PX = cv2.getPerspectiveTransform(
    np.float32([[0, 0], [256, 0], [256, 192], [0, 192]]), np.float32([[250, 60], [1700, 90], [1680, 1030], [230, 1000]])
).astype(np.float64)
NORM = np.diag([1 / PATTERN_SIZE[0], 1 / PATTERN_SIZE[1], 1.0])


def seen_dots(scenario, surface, cam, noise_px=0.0, seed=3):
    """Dots placed through MAP_TO_PX, where the lens really lands them on the
    terrain, as the camera sees them."""
    centres = dot_centres(NORM @ MAP_TO_PX, scenario.width, scenario.height)
    ground, heights = onto_surface(LENS, transform(np.linalg.inv(MAP_TO_PX), centres), surface)
    px = cam.px(ground, heights)
    return centres, px + np.random.default_rng(seed).normal(0, noise_px, px.shape)


def test_dot_grid_solves_the_projector_lens(scenario, surface):
    cam = Camera(scenario.terrain["grid"]["cell_size_mm"])
    board = BoardHomography(scenario)
    board.update(corner_detections(scenario, cam), FRAME)
    centres, px = seen_dots(scenario, surface, cam, noise_px=0.3)
    px[5] = np.nan  # a missed dot
    lens = solve_lens(px, centres, board.cam_to_map, surface, board.camera, guess=None)
    assert lens is not None and lens.projector is not None
    cell = scenario.terrain["grid"]["cell_size_mm"]
    p = lens.projector
    assert np.hypot(p.x - LENS.x, p.y - LENS.y) * cell < 25 and abs(p.h - LENS.h) < 30  # mm
    assert lens.flat_error_px > 4 * lens.error_px and lens.error_px < 1.0
    probe = np.array([[0, 0], [256, 0], [256, 192], [0, 192], [128, 96]], float)
    got = transform(np.linalg.inv(NORM) @ lens.map_to_proj, probe)
    assert np.abs(got - transform(MAP_TO_PX, probe)).max() < 2.0  # pattern px
    assert np.allclose(derive(lens.cam_to_proj, board.cam_to_map), lens.map_to_proj, atol=1e-9)

    # The light it predicts lands where the real light does, over the hills.
    rng = np.random.default_rng(4)
    spots = rng.uniform([10, 10], [246, 182], (50, 2))
    real = transform(MAP_TO_PX, to_plane(LENS, spots, surface.at(spots)))
    model = transform(np.linalg.inv(NORM) @ lens.map_to_proj, to_plane(p, spots, surface.at(spots)))
    assert np.linalg.norm(model - real, axis=1).max() < 2.0  # pattern px, under 0.5 mm on the board


def test_dot_grid_without_a_camera_pose_is_flat(scenario, surface):
    cam = Camera(scenario.terrain["grid"]["cell_size_mm"])
    board = BoardHomography(scenario)
    board.update(corner_detections(scenario, cam), FRAME)
    centres, px = seen_dots(scenario, surface, cam)
    lens = solve_lens(px, centres, board.cam_to_map, surface, None, guess=None)
    assert lens.projector is None and lens.error_px == lens.flat_error_px
    assert solve_lens(px[:10], centres[:10], board.cam_to_map, surface, board.camera, None) is None  # too few


def test_find_dots_finds_each_dot_centre():
    centres = dot_centres(NORM @ MAP_TO_PX, 256, 192)
    pattern = cv2.imdecode(np.frombuffer(dots_png(centres), np.uint8), cv2.IMREAD_GRAYSCALE)
    # Seen by a camera: pattern px -> camera px, smaller and keystoned.
    to_cam = cv2.getPerspectiveTransform(
        np.float32([[0, 0], [1920, 0], [1920, 1080], [0, 1080]]), np.float32([[300, 160], [1500, 120], [1460, 900], [340, 940]])
    ).astype(np.float64)
    shift = np.array([[1, 0, 0.5], [0, 1, 0.5], [0, 0, 1]])
    unshift = np.array([[1, 0, -0.5], [0, 1, -0.5], [0, 0, 1]])
    seen = cv2.warpPerspective(pattern, unshift @ to_cam @ shift, (1920, 1080), flags=cv2.INTER_AREA)
    want = transform(to_cam, centres) - 0.5  # camera px are OpenCV's: pixel i is centred on i
    # The flat fit's guess can be off by parallax; the match still finds each dot.
    got = find_dots(seen, want + np.array([9.0, -7.0]))
    assert not np.isnan(got).any()
    assert np.abs(got - want).max() < 0.5
