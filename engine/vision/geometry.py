"""Height parallax: where things on the printed terrain really are.

The camera and projector homographies are for one plane, the tops of the
corner markers. The terrain rises up to `relief_mm` above it, and the camera
and projector sit well under a metre up, so a point on a ridge is seen (and
lit) several mm away from where the plane model puts it: about
h * d / H, height times distance from the viewpoint's foot over its height.

Both the camera and the projector are treated as pinholes ("viewpoints"). A
surface point s at height h and the point where the line of sight through it
meets the marker plane are related by similar triangles:

    plane = foot + (s - foot) * H / (H - h)

so with the heightmap known, each can be found from the other. The camera's
viewpoint comes from the corner markers (solvePnP with the webcam's nominal
focal length). The projector's is solved during calibration from a grid of
dots it lights on the terrain (vision/projector.py, solve_lens); PROJECTOR_MM
in .env is the starting guess.

Units: x, y in map cells (the point straight below), heights in mm above the
marker plane. The ratio H / (H - h) has no units, so the two never mix.
"""

from dataclasses import dataclass

import cv2
import numpy as np

from scenario import Scenario

# Webcam focal length over frame width. The C920 is 78 degrees diagonal at
# 16:9: f = (diagonal / 2) / tan(39 deg) = 0.73 of the width. A few percent off
# only scales the correction by as much. None turns the camera correction off.
CAMERA_FOCAL: float | None = 0.73

# Finding where a line of sight meets the terrain: march down from the top of
# the relief in this many steps (a fraction of a cell each), then bisect.
MARCH_STEPS = 64
BISECT_STEPS = 10


@dataclass(frozen=True)
class Viewpoint:
    """A camera or projector centre."""

    x: float  # map cells, the point straight below it
    y: float
    h: float  # mm above the marker plane

    @property
    def foot(self) -> np.ndarray:
        return np.array([self.x, self.y], np.float64)


class Surface:
    """The printed surface's height above the marker plane, in mm."""

    def __init__(self, scenario: Scenario) -> None:
        t = scenario.terrain
        model, elev = t["model"], t["elevation_m"]
        top = t["markers"]["marker_top_z_mm"]
        span = max(elev["max"] - elev["min"], 1e-6)
        # dem_to_assets.py: z = base + (elev - min) / span * relief, from the table.
        self.mm = (model["base_mm"] + (scenario.heightmap - elev["min"]) / span * model["relief_mm"] - top).astype(np.float64)
        self.floor = -top  # the bare table around the terrain
        self.top = float(self.mm.max())
        self.width, self.height = scenario.width, scenario.height
        self.cell_mm = t["grid"]["cell_size_mm"]

    def at(self, pts: np.ndarray) -> np.ndarray:
        """(n, 2) map coords -> (n,) mm, bilinear between cell centres."""
        pts = np.asarray(pts, np.float64).reshape(-1, 2)
        x, y = pts[:, 0], pts[:, 1]
        fx = np.clip(x - 0.5, 0, self.width - 1)
        fy = np.clip(y - 0.5, 0, self.height - 1)
        x0 = np.minimum(fx.astype(int), self.width - 2)
        y0 = np.minimum(fy.astype(int), self.height - 2)
        tx, ty = fx - x0, fy - y0
        m = self.mm
        top = m[y0, x0] * (1 - tx) + m[y0, x0 + 1] * tx
        bottom = m[y0 + 1, x0] * (1 - tx) + m[y0 + 1, x0 + 1] * tx
        h = top * (1 - ty) + bottom * ty
        inside = (x >= 0) & (x <= self.width) & (y >= 0) & (y <= self.height)
        return np.where(inside, h, self.floor)


def to_plane(view: Viewpoint, pts: np.ndarray, heights: np.ndarray) -> np.ndarray:
    """Points at `heights` mm -> where the line of sight from `view` through
    them meets the marker plane."""
    pts = np.asarray(pts, np.float64).reshape(-1, 2)
    k = view.h / (view.h - np.asarray(heights, np.float64).reshape(-1))
    return view.foot + (pts - view.foot) * k[:, None]


def onto_surface(view: Viewpoint, plane: np.ndarray, surface: Surface, lift_mm: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
    """Marker-plane points -> where the line of sight from `view` through them
    first meets the surface (raised by `lift_mm`, e.g. a token's top).
    Returns map coords and their heights.

    The first hit, coming down from the viewpoint: near the board's edge a ray
    can also satisfy the height equation further on, past the side wall, where
    it never reaches."""
    plane = np.asarray(plane, np.float64).reshape(-1, 2)
    d = plane - view.foot

    def at(z):  # the ray at height z, and how far it is above the surface there
        pts = view.foot + d * ((view.h - z) / view.h)[:, None]
        return pts, z - surface.at(pts) - lift_mm

    n = len(plane)
    above = np.full(n, surface.top + lift_mm + 1.0)  # the ray is above the surface here
    below = np.full(n, surface.floor + lift_mm)  # and at or below it here
    found = np.zeros(n, bool)
    for z in np.linspace(above[0], below[0], MARCH_STEPS + 1)[1:]:
        _, gap = at(np.full(n, z))
        hit = (gap <= 0) & ~found
        below[hit] = z
        found |= hit
        above[~found] = z
    for _ in range(BISECT_STEPS):
        mid = (above + below) / 2
        _, gap = at(mid)
        below = np.where(gap <= 0, mid, below)
        above = np.where(gap <= 0, above, mid)
    pts, _ = at(below)
    return pts, surface.at(pts) + lift_mm


def orthophoto_remap(
    cam_to_map: np.ndarray,
    view: Viewpoint | None,
    surface: Surface,
    out_size: tuple[int, int],
) -> np.ndarray:
    """A cv2.remap table that rectifies the camera frame to a top-down view of
    the board: output pixels cover the whole map grid, each sampling the camera
    pixel that saw the ground under it.

    `out_size` is (width, height) in output pixels. The board (`surface.width` x
    `surface.height` cells) is scaled to fill it, so one output pixel is a fixed
    fraction of a cell and the result lines up with the map frame.

    With a camera viewpoint the line of sight through each ground point is
    followed from the terrain back up to the marker plane (to_plane), so hills
    no longer lean outward; without one (CAMERA_FOCAL off, or an unplaceable
    solve) it's the plain plane homography. Returns an (h, w, 2) float32 array
    of camera pixel coords for cv2.remap."""
    out_w, out_h = out_size
    sx, sy = surface.width / out_w, surface.height / out_h
    # Map-cell centre of each output pixel: pixel (i, j) covers [i, i+1) px.
    xs = (np.arange(out_w, dtype=np.float64) + 0.5) * sx
    ys = (np.arange(out_h, dtype=np.float64) + 0.5) * sy
    gx, gy = np.meshgrid(xs, ys)
    ground = np.column_stack([gx.ravel(), gy.ravel()])
    if view is None:
        plane = ground
    else:
        plane = to_plane(view, ground, surface.at(ground))
    cam = cv2.perspectiveTransform(plane.reshape(-1, 1, 2), np.linalg.inv(cam_to_map)).reshape(out_h, out_w, 2)
    return cam.astype(np.float32)


def camera_viewpoint(board: np.ndarray, map_pts: np.ndarray, frame_size: tuple[int, int], cell_mm: float) -> Viewpoint | None:
    """The camera's centre from the board homography (camera px -> map) and the
    map points it was solved from (the corner markers), or None if it can't be
    placed (no focal length set, or a degenerate solve)."""
    if CAMERA_FOCAL is None:
        return None
    w, h = frame_size
    f = CAMERA_FOCAL * w
    k = np.array([[f, 0, w / 2], [0, f, h / 2], [0, 0, 1]], np.float64)
    map_pts = np.asarray(map_pts, np.float64).reshape(-1, 2)
    cam = cv2.perspectiveTransform(map_pts.reshape(-1, 1, 2), np.linalg.inv(board)).reshape(-1, 2)
    # Map frame in mm: x east, y south, so z points down into the table.
    obj = np.column_stack([map_pts * cell_mm, np.zeros(len(map_pts))])
    ok, rvec, tvec = cv2.solvePnP(obj, cam, k, None, flags=cv2.SOLVEPNP_IPPE)
    if not ok:
        return None
    r, _ = cv2.Rodrigues(rvec)
    c = -r.T @ tvec.ravel()
    if c[2] >= 0:  # behind the board: a mirrored solve
        return None
    return Viewpoint(c[0] / cell_mm, c[1] / cell_mm, -c[2])


def projector_from_env(value: str | None, scenario: Scenario) -> Viewpoint | None:
    """PROJECTOR_MM="east,north,up": a guess at the projector lens in board mm (terrain.json
    `frames.board_mm`: from the terrain's south-west corner, up from the table)."""
    if not value or not value.strip():
        return None
    try:
        x, y, z = (float(v) for v in value.split(","))
    except ValueError:
        raise ValueError(f"PROJECTOR_MM={value!r}: expected three numbers, east,north,up in mm") from None
    t = scenario.terrain
    cell = t["grid"]["cell_size_mm"]
    return Viewpoint(x / cell, (t["model"]["height_mm"] - y) / cell, z - t["markers"]["marker_top_z_mm"])
