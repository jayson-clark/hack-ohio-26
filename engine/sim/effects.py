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

CREW_RADIUS = 6.0  # cells (~560 m)
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
    there settles to once it has ramped up. Recommendations test this."""
    cy, cx = np.mgrid[:height, :width].astype(np.float32) + 0.5
    return (CREW_MAX * soft_disk(np.hypot(cx - x, cy - y), CREW_RADIUS)).astype(np.float32)


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
        s = np.zeros((self.height, self.width), np.float32)
        seen = set()
        for t in tokens:
            seen.add(t.id)
            match t.token_type:
                case TokenType.CREW:
                    np.maximum(s, self._crew(t, tick), out=s)
                case TokenType.WATER:
                    np.maximum(s, self._water_drop(t, tick), out=s)
                case TokenType.FIREBREAK:
                    np.maximum(s, self._firebreak(t), out=s)
        for d in (self._crews, self._water):
            for gone in d.keys() - seen:
                del d[gone]
        return s

    def preview(self, tokens: list[Token], tick: int) -> np.ndarray:
        """What update() would return for `tokens`, without changing any
        crew's ramp-up or water drop's timer. Recommendations use it to ask
        "what if this crew weren't here?"."""
        crews, water = copy.deepcopy(self._crews), copy.deepcopy(self._water)
        try:
            return self.update(tokens, tick)
        finally:
            self._crews, self._water = crews, water

    def water_ready_in(self, tick: int) -> dict[str, int]:
        """Ticks until each water token can drop again (0 = ready once moved),
        for the console's cooldown display."""
        return {k: max(0, WATER_COOLDOWN_TICKS - (tick - w.dropped)) for k, w in self._water.items()}

    def _dist(self, x: float, y: float) -> np.ndarray:
        return np.hypot(self._cx - x, self._cy - y)

    def _disk(self, x: float, y: float, radius: float) -> np.ndarray:
        return soft_disk(self._dist(x, y), radius)

    def _crew(self, t: Token, tick: int) -> np.ndarray:
        c = self._crews.get(t.id)
        if c is None or math.hypot(t.x - c.x, t.y - c.y) > CREW_MOVE_RESET:
            c = self._crews[t.id] = _Crew(t.x, t.y, tick)
        else:
            c.x, c.y = t.x, t.y  # follow jitter without restarting the ramp
        ramp = min(1.0, (tick - c.since) / CREW_RAMP_TICKS)
        return CREW_MAX * ramp * self._disk(t.x, t.y, CREW_RADIUS)

    def _water_drop(self, t: Token, tick: int) -> np.ndarray:
        w = self._water.get(t.id)
        moved = w is not None and math.hypot(t.x - w.x, t.y - w.y) > WATER_RADIUS
        if w is None or (moved and tick - w.dropped >= WATER_COOLDOWN_TICKS):
            w = self._water[t.id] = _Water(t.x, t.y, tick)
        age = tick - w.dropped
        if age == 0:
            level = 1.0
        else:
            level = WATER_WET * max(0.0, 1.0 - age / WATER_WET_TICKS)
        if level <= 0:
            return np.zeros((self.height, self.width), np.float32)
        # The knockdown stays where the water landed, even if the token moves.
        return level * self._disk(w.x, w.y, WATER_RADIUS)

    def _firebreak(self, t: Token) -> np.ndarray:
        # Token.angle is radians clockwise from +x; with y pointing south that
        # is the ordinary (cos, sin) direction in map coords.
        ux, uy = math.cos(t.angle), math.sin(t.angle)
        dx, dy = self._cx - t.x, self._cy - t.y
        along = np.clip(dx * ux + dy * uy, -FIREBREAK_LENGTH / 2, FIREBREAK_LENGTH / 2)
        off = np.hypot(dx - along * ux, dy - along * uy)
        return (off <= FIREBREAK_HALF_WIDTH).astype(np.float32)
