"""Fire cellular automaton, after Alexandridis et al. (2008).

Each tick, every burning cell tries to ignite each of its 8 fuel neighbours:

    p_burn = p_h · (1 + p_veg) · (1 + p_den) · p_wind · p_slope · (1 − suppression)

and a cell that catches burns for BURN_TICKS ticks before turning to char.
Everything is whole-array NumPy (one shifted slice per neighbour direction),
and the same kernel advances a batch of grids, so the forecaster's rollouts
are this exact model, not an approximation of it.

The kernel only touches the bounding box of the burning cells (plus a
one-cell margin), since nothing outside it can change this tick. Early on,
when the fire is a few cells wide, that makes a step nearly free.
"""

import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from scenario import Scenario

UNBURNABLE, FUEL, BURNING, BURNED = 0, 1, 2, 3

# One tick is one sim-minute. At 10 Hz that's 10 sim-minutes per real second,
# so T+60 is 60 ticks (6 s of wall time) away and a rollout to it is cheap.
# The CA can move at most one 94 m cell per tick, so the top spread rate is
# about 5.6 km/h: a fast, wind-driven run, roughly what the Camp Fire did
# through Paradise. Slower settings would cap the fire below that.
SIM_MINUTES_PER_TICK = 1.0

# Model constants, tuned for the table rather than taken from the paper (see
# the tune-fire skill). p_h is far below Alexandridis' 0.58 because our cells
# burn for BURN_TICKS ticks, so each burning neighbour gets that many tries.
# The wind terms are about 3x the paper's c1 = 0.045, c2 = 0.131 so wind
# dominates at demo speeds: with no wind the fire creeps out as a disc at about
# 0.3 cells/tick; at 8 m/s the head runs about 0.55 cells/tick and the back
# barely moves; at 15 m/s the head runs about 0.9. The paper's slope term
# a = 0.078/deg made Paradise's canyon walls (90th percentile 24 deg)
# effectively impassable downhill, so it's softened too.
P_H = 0.08
C1 = 0.14
C2 = 0.22
SLOPE_A = 0.05  # per degree of slope between neighbours
BURN_TICKS = 8
# A diagonal neighbour is sqrt(2) further away, so it should take longer to
# reach. Without this the fire grows as a square.
DIAGONAL = 0.6
# Roads are a partial fuel break (the pavement doesn't burn, the verges do).
ROAD_FUEL = 0.4

# (dy, dx) from the cell being ignited to the burning neighbour.
NEIGHBOURS = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


@dataclass(frozen=True)
class Wind:
    speed_ms: float  # m/s
    # Meteorological: the direction the wind blows FROM, degrees clockwise from
    # north (map up, -y). 270 = west wind, pushing fire east (+x).
    from_deg: float


# Camp Fire conditions: a strong north-easterly (Jarbo Gap) wind.
DEFAULT_WIND = Wind(speed_ms=8.0, from_deg=45.0)


@dataclass(frozen=True)
class FireLayers:
    """Static per-scenario layers, precomputed once.

    `spread[d]` is everything in p_burn that doesn't change tick to tick for
    spread from neighbour NEIGHBOURS[d] into each cell: p_h, fuel, slope and
    the diagonal factor. Wind and suppression are multiplied in per step.
    """

    spread: np.ndarray  # float32 (8, H, W)
    burnable: np.ndarray  # bool (H, W)


@dataclass(frozen=True)
class FireSnapshot:
    """A picklable copy of the sim state, for the forecaster process."""

    tick: int
    wind: Wind
    state: np.ndarray  # uint8 (H, W)
    burn_left: np.ndarray  # int16 (H, W), ticks left for burning cells
    suppression: np.ndarray  # float32 (H, W) in [0, 1]
    layers: FireLayers


def wind_factors(wind: Wind) -> np.ndarray:
    """p_wind for each of the 8 spread directions, float32 (8,)."""
    f = math.radians(wind.from_deg)
    # Unit vector the wind blows towards, in map coords (x east, y south).
    to_x, to_y = -math.sin(f), math.cos(f)
    out = np.empty(8, np.float32)
    v = max(wind.speed_ms, 0.0)
    for d, (dy, dx) in enumerate(NEIGHBOURS):
        # Fire travels from the neighbour into the cell, i.e. along (-dx, -dy).
        cos_t = (-dx * to_x - dy * to_y) / math.hypot(dx, dy)
        out[d] = math.exp(C1 * v) * math.exp(C2 * v * (cos_t - 1))
    return out


def load_fuel(scenario: Scenario) -> np.ndarray:
    """Fuel multiplier per cell, float32 (H, W); 0 means unburnable.

    There's no real fuel map yet, so the default is uniform fuel everywhere
    (the river canyon included: its walls are brush, and at 94 m cells the
    river itself is narrower than a cell). If the scenario ever ships a
    grayscale fuel.png, black is unburnable and white is 1.5x fuel. Roads
    from roads.json, if present, are a partial fuel break.
    """
    h, w = scenario.height, scenario.width
    fuel = np.ones((h, w), np.float32)
    png = scenario.dir / "fuel.png"
    if png.exists():
        fuel = _read_gray_png(png, h, w) * 1.5
    roads = scenario.dir / "roads.json"
    if roads.exists():
        _burn_in_roads(fuel, json.loads(roads.read_text()))
    return fuel


def _read_gray_png(path: Path, h: int, w: int) -> np.ndarray:
    # Pillow isn't an engine dependency; OpenCV may be once vision lands. Only
    # pay for whichever is installed, and only if a fuel map exists.
    try:
        import cv2

        img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        img = cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)
    except ImportError:
        from PIL import Image

        img = np.asarray(Image.open(path).convert("L").resize((w, h)))
    return img.astype(np.float32) / 255.0


def _burn_in_roads(fuel: np.ndarray, roads: dict) -> None:
    h, w = fuel.shape
    nodes = roads.get("nodes", [])
    for i, j, *_ in roads.get("edges", []):
        (x0, y0), (x1, y1) = nodes[i], nodes[j]
        n = int(max(abs(x1 - x0), abs(y1 - y0)) * 2) + 2
        xs = np.clip(np.linspace(x0, x1, n).astype(int), 0, w - 1)
        ys = np.clip(np.linspace(y0, y1, n).astype(int), 0, h - 1)
        fuel[ys, xs] *= ROAD_FUEL


def build_layers(scenario: Scenario, fuel: np.ndarray | None = None) -> FireLayers:
    if fuel is None:
        fuel = load_fuel(scenario)
    z = scenario.heightmap.astype(np.float32)
    zp = np.pad(z, 1, mode="edge")
    h, w = z.shape
    spread = np.empty((8, h, w), np.float32)
    for d, (dy, dx) in enumerate(NEIGHBOURS):
        # Real metres, not the print's exaggerated relief.
        rise = z - zp[1 + dy : 1 + dy + h, 1 + dx : 1 + dx + w]
        run = scenario.cell_size_m * math.hypot(dx, dy)
        slope_deg = np.degrees(np.arctan(rise / run))
        diag = DIAGONAL if dx and dy else 1.0
        spread[d] = P_H * fuel * np.exp(SLOPE_A * slope_deg) * diag
    return FireLayers(spread=spread, burnable=fuel > 0)


def advance(
    state: np.ndarray,
    burn_left: np.ndarray,
    layers: FireLayers,
    wind: Wind,
    suppression: np.ndarray,
    rng: np.random.Generator,
    *,
    group: int = 1,
    wind_rows: np.ndarray | None = None,
) -> tuple[np.ndarray, int, int] | None:
    """One tick, in place, on a batch: state/burn_left are (N, H, W).

    Returns (ignited, y0, x0): the (N, h, w) mask of cells that caught this
    tick and the top-left of the crop it covers. None if nothing is burning.

    `group` > 1 splits the batch into that many equal blocks that share their
    random draws: row i of every block sees the same uniforms. That is how
    forecast.rollout_paired compares "crew here" with "no crew" on identical
    luck (common random numbers). `wind_rows`, float32 (8, N), replaces
    wind_factors(wind) with per-row factors, for an ensemble with wind spread.
    The defaults draw exactly what they always did, so the live sim is unchanged.
    """
    burning = state == BURNING
    # Union bounding box over the batch, plus the one-cell ring fire can reach.
    rows = np.flatnonzero(burning.any(axis=(0, 2)))
    if rows.size == 0:
        return None
    cols = np.flatnonzero(burning.any(axis=(0, 1)))
    H, W = state.shape[1:]
    y0, y1 = max(rows[0] - 1, 0), min(rows[-1] + 2, H)
    x0, x1 = max(cols[0] - 1, 0), min(cols[-1] + 2, W)
    h, w = y1 - y0, x1 - x0

    st = state[:, y0:y1, x0:x1]
    bl = burn_left[:, y0:y1, x0:x1]
    sup = suppression[..., y0:y1, x0:x1]
    b = np.zeros((state.shape[0], h + 2, w + 2), np.float32)
    b[:, 1:-1, 1:-1] = burning[:, y0:y1, x0:x1]

    pw = wind_factors(wind)[:, None, None, None] if wind_rows is None else wind_rows[:, :, None, None]
    no_ignite = np.ones((state.shape[0], h, w), np.float32)
    for d, (dy, dx) in enumerate(NEIGHBOURS):
        p = np.minimum(layers.spread[d, y0:y1, x0:x1] * pw[d], 1.0)
        no_ignite *= 1.0 - p * b[:, 1 + dy : 1 + dy + h, 1 + dx : 1 + dx + w]
    p_ignite = (1.0 - no_ignite) * (1.0 - sup)

    u = rng.random((st.shape[0] // group, h, w), dtype=np.float32)
    if group > 1:
        u = np.tile(u, (group, 1, 1))
    ignite = (st == FUEL) & (u < p_ignite)

    # Burning cells count down and char; fully suppressed ones (a water drop
    # or a firebreak laid over the flames) go straight out.
    lit = st == BURNING
    bl[lit] -= 1
    out = lit & ((bl <= 0) | (sup >= 1.0))
    st[out] = BURNED
    bl[out] = 0
    st[ignite] = BURNING
    bl[ignite] = BURN_TICKS
    return ignite, y0, x0


class FireSim:
    def __init__(self, scenario: Scenario, seed: int | None = None) -> None:
        self.scenario = scenario
        self.layers = build_layers(scenario)
        self._seed = seed
        self.wind = DEFAULT_WIND
        self.suppression = np.zeros((scenario.height, scenario.width), np.float32)
        self.reset()

    def reset(self) -> None:
        """Back to unburned, tick 0. Wind and suppression are kept."""
        shape = (self.scenario.height, self.scenario.width)
        self.tick = 0
        self.rng = np.random.default_rng(self._seed)
        # Kept as (1, H, W) so the batched kernel runs on it unchanged.
        self._state = np.where(self.layers.burnable, FUEL, UNBURNABLE).astype(np.uint8)[None]
        self._burn_left = np.zeros((1, *shape), np.int16)

    @property
    def state(self) -> np.ndarray:
        return self._state[0]

    @property
    def burn_left(self) -> np.ndarray:
        return self._burn_left[0]

    def set_wind(self, wind: Wind) -> None:
        self.wind = wind

    def set_suppression(self, suppression: np.ndarray) -> None:
        self.suppression = np.clip(suppression, 0.0, 1.0).astype(np.float32, copy=False)

    def ignite(self, x: float, y: float, radius: float = 1.5) -> None:
        """Light every fuel cell whose centre is within `radius` of (x, y)."""
        ys, xs = np.ogrid[: self.scenario.height, : self.scenario.width]
        disk = (xs + 0.5 - x) ** 2 + (ys + 0.5 - y) ** 2 <= radius**2
        if not disk.any():  # a tiny radius still lights the clicked cell
            col, row = int(x), int(y)
            if not self.scenario.in_bounds(x, y):
                return
            disk[row, col] = True
        hit = disk & (self.state == FUEL)
        self.state[hit] = BURNING
        self.burn_left[hit] = BURN_TICKS

    def step(self) -> None:
        advance(self._state, self._burn_left, self.layers, self.wind, self.suppression, self.rng)
        self.tick += 1

    def counts(self) -> tuple[int, int]:
        """(burning, burned) cell counts."""
        c = np.bincount(self.state.ravel(), minlength=4)
        return int(c[BURNING]), int(c[BURNED])

    def snapshot(self) -> FireSnapshot:
        return FireSnapshot(
            tick=self.tick,
            wind=self.wind,
            state=self.state.copy(),
            burn_left=self.burn_left.copy(),
            suppression=self.suppression.copy(),
            layers=self.layers,
        )
