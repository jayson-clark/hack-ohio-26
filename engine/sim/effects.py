"""What tokens on the table do to the fire, as a suppression grid.

The fire model has one knob for every intervention: suppression in [0, 1],
multiplied as (1 - s) into p_burn, with s = 1 also putting out cells that are
already burning (see sim.fire.advance). So:

- crew: suppression that ramps up over CREW_RAMP_TICKS within CREW_RADIUS,
  to CREW_MAX (< 1, so a crew holds a line but doesn't snuff flames).
- water: when dropped, s = 1 within WATER_RADIUS (instant knockdown), then a
  wet patch that dries out over WATER_WET_TICKS. Each token can drop again
  once WATER_COOLDOWN_TICKS have passed, but only after it has been moved.
- firebreak: s = 1 along a FIREBREAK_LENGTH segment through the token at its
  angle. That's fuel removed, and like a dug line it holds as long as the
  token is there. A two-marker firebreak can be added when vision needs it.
- bus: no fire effect.

Effects are kept by token id, so a token that vision briefly loses and finds
again keeps its state, while a newly placed one starts fresh.
"""

import copy
import math
from dataclasses import dataclass

import numpy as np

from protocol import Token, TokenType

# Cells (~1.3 km); full strength out to 60% of it (soft_disk). Measured with
# three crews on the Camp Fire start (#97):
#  - At 6 the fire just burned round them: crews at Concow's edge took it from
#    74% to 43% burned, and in open country they cut the burn by 4%.
#  - At 10 the reach ends inside the token's own projected disc (HALO_RADIUS
#    + 1.6 = 10.6 cells), so crews hold no more than the ground they cover and
#    still look like they do nothing.
#  - At 14 crews at a town's edge hold it to 1% burned and cut open-country
#    burn by 23%, and their reach shows past the token. Three crews can save
#    one town, not all of them, so where they go is still the decision.
CREW_RADIUS = 14.0
CREW_MAX = 0.9
CREW_RAMP_TICKS = 20
# A crew that is picked up and set down elsewhere has to dig in again.
CREW_MOVE_RESET = 2.0

WATER_RADIUS = 5.0
WATER_WET = 0.8
WATER_WET_TICKS = 30
WATER_COOLDOWN_TICKS = 60

FIREBREAK_LENGTH = 16.0  # cells, end to end (~1.5 km)
FIREBREAK_HALF_WIDTH = 0.9


def soft_disk(dist: np.ndarray, radius: float) -> np.ndarray:
    """Full strength out to 60% of the radius, then a linear edge, so the
    boundary isn't a hard pixel circle the fire hugs."""
    return np.clip((radius - dist) / (0.4 * radius), 0.0, 1.0)


def crew_footprint(width: int, height: int, x: float, y: float) -> np.ndarray:
    """A dug-in crew's suppression at (x, y), float32 (H, W): what a crew placed
    there settles to once it has ramped up."""
    cy, cx = np.mgrid[:height, :width].astype(np.float32) + 0.5
    return (CREW_MAX * soft_disk(np.hypot(cx - x, cy - y), CREW_RADIUS)).astype(np.float32)


@dataclass
class TimedLayer:
    """Suppression `footprint` x level(dt), where dt is ticks from now: a crew
    digging in, a water drop drying out, or a crew still on its way (#56).

    level(dt) is 0 before `t_on`, then `level0 + slope * (dt - t_on)`, clipped
    to [0, cap]. `first`, if set, overrides the level at dt == 0 (the tick a
    water drop lands, when it knocks fire down completely).
    """

    footprint: np.ndarray  # float32 (H, W), the shape, 0..1
    level0: float
    slope: float
    cap: float
    t_on: int = 0
    first: float | None = None

    def level(self, dt: int) -> float:
        if dt < self.t_on:
            return 0.0
        if dt == 0 and self.first is not None:
            return self.first
        return min(self.cap, max(0.0, self.level0 + self.slope * (dt - self.t_on)))

    @property
    def varies(self) -> bool:
        return self.slope != 0 or self.t_on > 0 or self.first is not None


@dataclass
class SuppressionSchedule:
    """Suppression from now on, if the tokens stay where they are: a fixed part
    (firebreaks) plus layers that ramp up or dry out. at(0) is exactly what the
    live sim applies this tick; forecasts evaluate it every tick instead of
    freezing today's grid, so a crew placed a moment ago is credited as it digs
    in, and a wet patch dries out on schedule."""

    static: np.ndarray  # float32 (H, W)
    layers: list[TimedLayer]

    def at(self, dt: int) -> np.ndarray:
        s = self.static.copy()
        for layer in self.layers:
            lvl = layer.level(dt)
            if lvl > 0:
                np.maximum(s, lvl * layer.footprint, out=s)
        return s

    @property
    def varies(self) -> bool:
        return any(layer.varies for layer in self.layers)


def crew_layer(width: int, height: int, x: float, y: float, *, t_on: int = 0, ramped: float = 0.0) -> TimedLayer:
    """A crew at (x, y) that starts digging in `t_on` ticks from now (it's still
    travelling until then) and is already `ramped` (0..1) of the way there.
    Recommendations test this, so a suggested crew is credited the way a
    placed one would really act."""
    cy, cx = np.mgrid[:height, :width].astype(np.float32) + 0.5
    disk = soft_disk(np.hypot(cx - x, cy - y), CREW_RADIUS).astype(np.float32)
    return TimedLayer(disk, CREW_MAX * ramped, CREW_MAX / CREW_RAMP_TICKS, CREW_MAX, t_on=t_on)


@dataclass
class _Crew:
    x: float
    y: float
    since: int


@dataclass
class _Water:
    x: float
    y: float
    dropped: int


class TokenEffects:
    """Turns the current tokens into a suppression grid, once per tick."""

    def __init__(self, width: int, height: int) -> None:
        self.width, self.height = width, height
        ys, xs = np.mgrid[:height, :width].astype(np.float32)
        self._cx, self._cy = xs + 0.5, ys + 0.5  # cell centres
        self.reset()

    def reset(self) -> None:
        self._crews: dict[str, _Crew] = {}
        self._water: dict[str, _Water] = {}

    def update(self, tokens: list[Token], tick: int) -> np.ndarray:
        """Suppression for this tick, and advance each crew's and drop's state."""
        return self._build(tokens, tick).at(0)

    def schedule(self, tokens: list[Token], tick: int) -> SuppressionSchedule:
        """Suppression from this tick on, if the tokens stay put, without
        changing any state. at(0) equals what update() would return."""
        crews, water = copy.deepcopy(self._crews), copy.deepcopy(self._water)
        try:
            return self._build(tokens, tick)
        finally:
            self._crews, self._water = crews, water

    def preview(self, tokens: list[Token], tick: int) -> np.ndarray:
        """What update() would return for `tokens`, without changing any
        crew's ramp-up or water drop's timer. Recommendations use it to ask
        "what if this crew weren't here?"."""
        return self.schedule(tokens, tick).at(0)

    def _build(self, tokens: list[Token], tick: int) -> SuppressionSchedule:
        static = np.zeros((self.height, self.width), np.float32)
        layers: list[TimedLayer] = []
        seen = set()
        for t in tokens:
            seen.add(t.id)
            match t.token_type:
                case TokenType.CREW:
                    layers.append(self._crew(t, tick))
                case TokenType.WATER:
                    layers.append(self._water_drop(t, tick))
                case TokenType.FIREBREAK:
                    np.maximum(static, self._firebreak(t), out=static)
        for d in (self._crews, self._water):
            for gone in d.keys() - seen:
                del d[gone]
        return SuppressionSchedule(static, layers)

    def water_ready_in(self, tick: int) -> dict[str, int]:
        """Ticks until each water token can drop again (0 = ready once moved),
        for the console's cooldown display."""
        return {k: max(0, WATER_COOLDOWN_TICKS - (tick - w.dropped)) for k, w in self._water.items()}

    def _dist(self, x: float, y: float) -> np.ndarray:
        return np.hypot(self._cx - x, self._cy - y)

    def _disk(self, x: float, y: float, radius: float) -> np.ndarray:
        return soft_disk(self._dist(x, y), radius)

    def _crew(self, t: Token, tick: int) -> TimedLayer:
        c = self._crews.get(t.id)
        if c is None or math.hypot(t.x - c.x, t.y - c.y) > CREW_MOVE_RESET:
            c = self._crews[t.id] = _Crew(t.x, t.y, tick)
        else:
            c.x, c.y = t.x, t.y  # follow jitter without restarting the ramp
        ramp = min(1.0, (tick - c.since) / CREW_RAMP_TICKS)
        return TimedLayer(self._disk(t.x, t.y, CREW_RADIUS), CREW_MAX * ramp, CREW_MAX / CREW_RAMP_TICKS, CREW_MAX)

    def _water_drop(self, t: Token, tick: int) -> TimedLayer:
        w = self._water.get(t.id)
        moved = w is not None and math.hypot(t.x - w.x, t.y - w.y) > WATER_RADIUS
        if w is None or (moved and tick - w.dropped >= WATER_COOLDOWN_TICKS):
            w = self._water[t.id] = _Water(t.x, t.y, tick)
        age = tick - w.dropped
        # Full knockdown the tick it lands, then a wet patch that dries out.
        # The knockdown stays where the water landed, even if the token moves.
        return TimedLayer(
            self._disk(w.x, w.y, WATER_RADIUS),
            WATER_WET * (1.0 - age / WATER_WET_TICKS),
            -WATER_WET / WATER_WET_TICKS,
            WATER_WET,
            first=1.0 if age == 0 else None,
        )

    def _firebreak(self, t: Token) -> np.ndarray:
        # Token.angle is radians clockwise from +x; with y pointing south that
        # is the ordinary (cos, sin) direction in map coords.
        ux, uy = math.cos(t.angle), math.sin(t.angle)
        dx, dy = self._cx - t.x, self._cy - t.y
        along = np.clip(dx * ux + dy * uy, -FIREBREAK_LENGTH / 2, FIREBREAK_LENGTH / 2)
        off = np.hypot(dx - along * ux, dy - along * uy)
        return (off <= FIREBREAK_HALF_WIDTH).astype(np.float32)
