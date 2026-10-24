"""Fire cellular automaton, after Alexandridis et al. (2008).

Each tick, every burning cell tries to ignite each of its 8 fuel neighbours:

    p_burn = p_h · (1 + p_veg) · (1 + p_den) · p_wind · p_slope · (1 − suppression)

where partial suppression (< 1) is weakened against intense, wind-driven
spread (HOLD_P), so a crew holds flanks and backing fire but not the head.

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
# The Camp Fire replay (eval/campfire.py, #15) would fit its perimeters better
# with C2 0.3-0.4 (a narrower tongue: the replay burns ~1.7x the real area at
# 0.22). But C2 also starves backing and flank spread at every wind, so at 3-8
# m/s fires came out under half the size, many burned out on their own, and
# instant attack contained them again. One extreme-wind event isn't enough
# evidence for that, so C2 stays at 0.22.
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
# Partial suppression (a crew's line, a wet patch) holds slow fire, not a
# wind-driven head. Its strength is scaled by 1 / (1 + (p / HOLD_P)^2), where p
# is the strongest single-neighbour spread chance into the cell this tick:
# about 0.007 for backing fire and 0.04 for a flank at 8 m/s (held almost
# fully), 0.08 for calm fire (0.8 of full), 0.25 for an 8 m/s head (0.3) and
# 0.65 at 15 m/s (0.05). Full suppression (fuel removed by a firebreak, the
# tick a water drop lands) still stops anything. Without this, crews dropped on
# a new ignition held its head as well as its flanks and contained every start.
HOLD_P = 0.15
# Spotting (#15): in strong wind, burning cells throw embers downwind that can
# light new fires ahead of the front. Without it the fire can't go faster than
# one cell per tick, and the real Camp Fire covered ~1.4 cells/min in its
# second hour by spotting (NIST TN 2135 logs spot fires up to 6.3 km ahead).
# Each burning cell throws an ember with chance SPOT_RATE * (v - SPOT_MIN_WIND)
# / 10 per tick. The ember flies an exponential distance with mean SPOT_MEAN *
# v / 10 cells (capped at SPOT_MAX) within SPOT_SPREAD_DEG of downwind, and
# lights a fuel cell with chance SPOT_IGNITE * fuel * (1 - suppression).
# Calibrated against the Camp Fire with eval/campfire.py (#15). With spotting,
# the replay reaches 87% of the cells NIST saw burning in the first 12 h and is
# late at none of the best-timed 75% (without it: 79%, 15 min late). The fit
# is flat for SPOT_RATE between 0.002 and 0.01; the low end keeps strong-wind
# games from snowballing. Below 9 m/s there is none, so calm and moderate days
# play exactly as before.
SPOT_MIN_WIND = 9.0  # m/s
SPOT_RATE = 0.003
SPOT_MEAN = 12.0  # cells at 10 m/s
SPOT_MAX = 70.0  # cells (~6.6 km)
SPOT_SPREAD_DEG = 20.0
SPOT_IGNITE = 0.5

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
    # Suppression from now on (a sim.effects.SuppressionSchedule), if the
    # engine knows the tokens: crews still digging in, drops drying out (#56).
    # Forecasts use it in place of freezing `suppression`. None for a bare FireSim.
    schedule: object | None = None


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

    Scenarios ship a grayscale fuel.png from tools/osm_to_fuel.py (OSM land
    cover): black is unburnable and white is 1.5x fuel, with forest at 1.0.
    Without one, fuel is uniform everywhere. Roads from roads.json, if
    present, are a partial fuel break.
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
) -> tuple[np.ndarray, int, int, tuple | None] | None:
    """One tick, in place, on a batch: state/burn_left are (N, H, W).

    Returns (ignited, y0, x0, spots): the (N, h, w) mask of cells that caught
    from a neighbour this tick and the top-left of the crop it covers, plus
    the (rows, ys, xs) indices of cells lit by embers anywhere on the map (or
    None). None if nothing is burning.

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
    if sup.ndim == 3 and sup.shape[0] != state.shape[0]:
        # One grid per group (variant): rows are variant-major, so repeat each
        # grid over its block of rollouts. Only the crop, so it stays cheap.
        sup = np.repeat(sup, state.shape[0] // sup.shape[0], axis=0)
    b = np.zeros((state.shape[0], h + 2, w + 2), np.float32)
    b[:, 1:-1, 1:-1] = burning[:, y0:y1, x0:x1]

    pw = wind_factors(wind)[:, None, None, None] if wind_rows is None else wind_rows[:, :, None, None]
    no_ignite = np.ones((state.shape[0], h, w), np.float32)
    strongest = np.zeros((state.shape[0], h, w), np.float32)
    for d, (dy, dx) in enumerate(NEIGHBOURS):
        p = np.minimum(layers.spread[d, y0:y1, x0:x1] * pw[d], 1.0) * b[:, 1 + dy : 1 + dy + h, 1 + dx : 1 + dx + w]
        no_ignite *= 1.0 - p
        np.maximum(strongest, p, out=strongest)
    # Partial suppression weakens against intense (head) fire; see HOLD_P.
    hold = 1.0 / (1.0 + (strongest / HOLD_P) ** 2)
    eff = np.where(sup >= 1.0, sup, sup * hold)
    p_ignite = (1.0 - no_ignite) * (1.0 - eff)

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
    spots = _spot(state, burn_left, layers, wind, suppression, rng, lit, y0, x0, group)
    return ignite, y0, x0, spots


def _spot(state, burn_left, layers, wind, suppression, rng, lit, y0, x0, group):
    """Embers from the cells burning at the start of this tick (`lit`, a crop
    at y0, x0) light fuel cells downwind; see SPOT_RATE. Returns the lit
    (rows, ys, xs), or None. Each source cell's draws are shared across
    groups, so paired what-ifs keep common random numbers."""
    v = wind.speed_ms
    rate = SPOT_RATE * (v - SPOT_MIN_WIND) / 10.0
    if rate <= 0 or not lit.any():
        return None
    n, h, w = lit.shape
    u = rng.random((4, n // group, h, w), dtype=np.float32)
    if group > 1:
        u = np.tile(u, (1, group, 1, 1))
    src = lit & (u[0] < rate)
    if not src.any():
        return None
    rows, sy, sx = np.nonzero(src)
    f = math.radians(wind.from_deg)
    to = math.atan2(math.cos(f), -math.sin(f))  # downwind, in map coords (x east, y south)
    dist = np.minimum(-np.log(np.maximum(u[1][src], 1e-6)) * SPOT_MEAN * v / 10.0, SPOT_MAX)
    ang = to + (u[2][src] * 2 - 1) * math.radians(SPOT_SPREAD_DEG)
    H, W = state.shape[1:]
    ty = np.floor(sy + y0 + 0.5 + dist * np.sin(ang)).astype(np.int64)
    tx = np.floor(sx + x0 + 0.5 + dist * np.cos(ang)).astype(np.int64)
    ok = (ty >= 0) & (ty < H) & (tx >= 0) & (tx < W)
    rows, ty, tx, draw = rows[ok], ty[ok], tx[ok], u[3][src][ok]
    ok = state[rows, ty, tx] == FUEL
    rows, ty, tx, draw = rows[ok], ty[ok], tx[ok], draw[ok]
    fuel = layers.spread[:, ty, tx].max(axis=0) / P_H  # fuel x slope, ~1 for forest
    if suppression.ndim == 2:
        s = suppression[ty, tx]
    else:  # one grid per row, or per group of rows
        s = suppression[rows // (n // suppression.shape[0]), ty, tx]
    ok = draw < SPOT_IGNITE * np.minimum(fuel, 1.5) * (1.0 - s)
    if not ok.any():
        return None
    rows, ty, tx = rows[ok], ty[ok], tx[ok]
    state[rows, ty, tx] = BURNING
    burn_left[rows, ty, tx] = BURN_TICKS
    return rows, ty, tx


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
