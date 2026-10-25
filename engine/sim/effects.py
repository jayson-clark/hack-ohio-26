"""What tokens on the table do to the fire, as a suppression grid.

The fire model has one knob for every intervention: suppression in [0, 1],
multiplied as (1 - s) into p_burn, with s = 1 also putting out cells that are
already burning (see sim.fire.advance). So:

- crew: suppression that ramps up over CREW_RAMP_TICKS within CREW_RADIUS,
  to CREW_MAX (< 1, so a crew holds a line but doesn't snuff flames). Being
  partial, it holds flanks and backing fire but not a wind-driven head
  (sim.fire.HOLD_P). Once dug in, the crew cuts line (#99): a strip through
  its position, along the wind it arrived in, growing LINE_RATE cells a tick
  at each end up to LINE_LENGTH. That's anchor-and-flank: a disk alone can't
  touch a front kilometres wide, and a line across the wind would meet the
  head, which partial suppression doesn't hold. Along the wind it holds a
  flank for kilometres, so the fire stays narrow and bends around it.
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
# Line a dug-in crew cuts (#99): about 2.8 km/h at each end, a crew working
# with engine support and burnout, reaching its full ~7.5 km 80 min after
# digging in. Each end has to get well past CREW_RADIUS before the line adds
# anything: at 10 cells a side it stayed inside the crew's own disk. Two crews
# flanking a running front cut its burn by a further 7-8 points over disk-only
# crews at 5-8 m/s; at half this rate the head outran the line and it added
# 0-3, and at 13 m/s the head runs either way. A cut line is fuel
# scraped to soil, so like a dozer line it's full suppression: at the crew's
# 0.9 a two-cell strip leaked under flanking fire (HOLD_P weakens partial
# suppression) and changed nothing. It runs along the wind, so it meets flanks,
# not the head.
# Shifts (#178): a crew works at full strength for SHIFT_TICKS, then fades to
# FATIGUE_FLOOR of it over FADE_TICKS unless it's relieved. Real crews work
# long shifts, but these rounds run 4-10 sim hours, so the limit has to bite
# inside one: relieving a crew is a decision, not housekeeping.
SHIFT_TICKS = 240
FADE_TICKS = 120
FATIGUE_FLOOR = 0.5
LINE_LENGTH = 80.0  # cells, end to end
LINE_RATE = 0.5  # cells a tick, at each end
LINE_HALF_WIDTH = 1.0
# Patrol (#178): a staffed line also catches embers landing across it and
# slopovers at its edges, so while its crew works there's partial suppression
# PATROL x the crew's current strength within PATROL_BAND cells of the line.
# Bare soil doesn't tire, but the patrol does: it fades with the crew and is
# gone once the crew leaves, which is what makes relieving a crew matter when
# embers fly (above SPOT_MIN_WIND).
PATROL = 0.5
PATROL_BAND = 3.0

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
    to [0, cap]. `first`, if set, overrides the level at dt == t_on (the tick a
    water drop lands, when it knocks fire down completely).
    """

    footprint: np.ndarray  # float32 (H, W), the shape, 0..1
    level0: float
    slope: float
    cap: float
    t_on: int = 0
    first: float | None = None
    # A crew's growing line (#99): each cell's distance along the line from the
    # crew (inf off it), and how far the line reaches at dt = t_on (negative
    # while the crew is still digging in), growing at line_rate a tick.
    line_along: np.ndarray | None = None
    line_band: np.ndarray | None = None  # the same, for cells within PATROL_BAND of the line
    line_reach0: float = 0.0
    line_rate: float = 0.0
    # A crew's shift (#178): from dt = fade_at it fades linearly to
    # FATIGUE_FLOOR of cap over FADE_TICKS. None never fades.
    fade_at: int | None = None

    def level(self, dt: int) -> float:
        if dt < self.t_on:
            return 0.0
        if dt == self.t_on and self.first is not None:
            return self.first
        lvl = min(self.cap, max(0.0, self.level0 + self.slope * (dt - self.t_on)))
        if self.fade_at is not None and dt > self.fade_at:
            lvl = min(lvl, self.cap * max(FATIGUE_FLOOR, 1.0 - (1.0 - FATIGUE_FLOOR) * (dt - self.fade_at) / FADE_TICKS))
        return lvl

    def grid(self, dt: int) -> np.ndarray | None:
        """Suppression this layer applies dt ticks from now, or None if none."""
        lvl = self.level(dt)
        g = lvl * self.footprint if lvl > 0 else None
        if self.line_along is not None and dt >= self.t_on:
            reach = min(LINE_LENGTH / 2, self.line_reach0 + self.line_rate * (dt - self.t_on))
            if reach > 0:
                line = (self.line_along <= reach).astype(np.float32)
                if self.line_band is not None and lvl > 0:
                    np.maximum(line, (self.line_band <= reach) * np.float32(PATROL * lvl / self.cap), out=line)
                g = line if g is None else np.maximum(g, line)
        return g

    @property
    def varies(self) -> bool:
        growing = self.line_along is not None and self.line_reach0 < LINE_LENGTH / 2
        return self.slope != 0 or self.t_on > 0 or self.first is not None or growing or self.fade_at is not None


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
            g = layer.grid(dt)
            if g is not None:
                np.maximum(s, g, out=s)
        return s

    @property
    def varies(self) -> bool:
        return any(layer.varies for layer in self.layers)


def line_along(cx: np.ndarray, cy: np.ndarray, x: float, y: float, wind_from: float) -> tuple[np.ndarray, np.ndarray]:
    """Distance along a crew's line from (x, y) for cells on it, inf off it;
    and the same for cells within PATROL_BAND of it (the patrolled band).
    The line runs with the wind: bearing b is the direction (sin b, -cos b) in
    map coords (y south), and the line goes both ways from the crew."""
    b = math.radians(wind_from)
    ux, uy = math.sin(b), -math.cos(b)
    dx, dy = cx - x, cy - y
    along = dx * ux + dy * uy
    off = np.abs(dx * uy - dy * ux)
    dist = np.abs(along)
    return (np.where(off <= LINE_HALF_WIDTH, dist, np.inf).astype(np.float32),
            np.where(off <= PATROL_BAND, dist, np.inf).astype(np.float32))


def crew_layer(width: int, height: int, x: float, y: float, *, t_on: int = 0, ramped: float = 0.0,
               wind_from: float | None = None) -> TimedLayer:
    """A crew at (x, y) that starts digging in `t_on` ticks from now (it's still
    travelling until then) and is already `ramped` (0..1) of the way there.
    Given the wind it arrives in, it also cuts its line along it once dug in.
    Recommendations test this, so a suggested crew is credited the way a
    placed one would really act."""
    cy, cx = np.mgrid[:height, :width].astype(np.float32) + 0.5
    disk = soft_disk(np.hypot(cx - x, cy - y), CREW_RADIUS).astype(np.float32)
    layer = TimedLayer(disk, CREW_MAX * ramped, CREW_MAX / CREW_RAMP_TICKS, CREW_MAX, t_on=t_on,
                       fade_at=t_on + SHIFT_TICKS - int(ramped * CREW_RAMP_TICKS))
    if wind_from is not None:
        layer.line_along, layer.line_band = line_along(cx, cy, x, y, wind_from)
        layer.line_reach0 = -LINE_RATE * CREW_RAMP_TICKS * (1.0 - ramped)
        layer.line_rate = LINE_RATE
    return layer


@dataclass
class _Crew:
    x: float
    y: float
    since: int  # when this shift started; a relief crew starts a new one (#178)
    wind_from: float | None  # locked when it starts, so the line doesn't swing with later wind
    line_since: int = 0  # when the line started: a relief crew carries on the same line


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
        # The wind crews starting now cut their lines along; kept through
        # reset(), since a map reset doesn't change the weather.
        self.wind_from: float | None = None
        self.reset()

    def reset(self) -> None:
        self._crews: dict[str, _Crew] = {}
        self._water: dict[str, _Water] = {}

    def set_wind(self, from_deg: float) -> None:
        """The wind crews starting now cut their lines along (#99)."""
        self.wind_from = from_deg

    def update(self, tokens: list[Token], tick: int, starts: dict[str, int] | None = None) -> np.ndarray:
        """Suppression for this tick, and advance each crew's and drop's state.

        `starts` (from the dispatcher, #178) maps a token to the tick its
        current unit arrived: a relief crew starts a fresh shift, and each
        tanker arrival is a new drop. Without it (no stations), a crew's shift
        runs from when its token first acts and water re-drops on a cooldown."""
        return self._build(tokens, tick, starts).at(0)

    def schedule(self, tokens: list[Token], tick: int, starts: dict[str, int] | None = None) -> SuppressionSchedule:
        """Suppression from this tick on, if the tokens stay put, without
        changing any state. at(0) equals what update() would return."""
        crews, water = copy.deepcopy(self._crews), copy.deepcopy(self._water)
        try:
            return self._build(tokens, tick, starts)
        finally:
            self._crews, self._water = crews, water

    def preview(self, tokens: list[Token], tick: int, starts: dict[str, int] | None = None) -> np.ndarray:
        """What update() would return for `tokens`, without changing any
        crew's ramp-up or water drop's timer. Recommendations use it to ask
        "what if this crew weren't here?"."""
        return self.schedule(tokens, tick, starts).at(0)

    def fatigue_of(self, token_id: str, tick: int) -> float:
        """0 for a fresh crew, 1 once it has faded to FATIGUE_FLOOR (#178)."""
        c = self._crews.get(token_id)
        return 0.0 if c is None else min(1.0, max(0.0, (tick - c.since - SHIFT_TICKS) / FADE_TICKS))

    def arrival_layer(self, t: Token, t_on: int) -> TimedLayer | None:
        """What `t` will do once its unit arrives `t_on` ticks from now (#104):
        a crew digging in from zero, a drop's knockdown then drying, a dozer's
        line. Forecasts add these for units still on their way."""
        match t.token_type:
            case TokenType.CREW:
                return self._with_line(
                    TimedLayer(self._disk(t.x, t.y, CREW_RADIUS), 0.0, CREW_MAX / CREW_RAMP_TICKS, CREW_MAX, t_on=t_on,
                               fade_at=t_on + SHIFT_TICKS),
                    t.x, t.y, self.wind_from, 0.0)
            case TokenType.WATER:
                return TimedLayer(self._disk(t.x, t.y, WATER_RADIUS), WATER_WET, -WATER_WET / WATER_WET_TICKS,
                                  WATER_WET, t_on=t_on, first=1.0)
            case TokenType.FIREBREAK:
                return TimedLayer(self._firebreak(t), 1.0, 0.0, 1.0, t_on=t_on)
        return None

    def _build(self, tokens: list[Token], tick: int, starts: dict[str, int] | None = None) -> SuppressionSchedule:
        static = np.zeros((self.height, self.width), np.float32)
        layers: list[TimedLayer] = []
        seen = set()
        for t in tokens:
            seen.add(t.id)
            match t.token_type:
                case TokenType.CREW:
                    layers.append(self._crew(t, tick, None if starts is None else starts.get(t.id)))
                case TokenType.WATER:
                    layers.append(self._water_drop(t, tick, None if starts is None else starts.get(t.id)))
                case TokenType.FIREBREAK:
                    np.maximum(static, self._firebreak(t), out=static)
        for d in (self._crews, self._water):
            for gone in d.keys() - seen:
                del d[gone]
        return SuppressionSchedule(static, layers)

    def line_of(self, token_id: str, tick: int) -> list[list[float]]:
        """The two ends of the line the crew on `token_id` has cut by `tick`
        (#159), in map coords, or [] if it hasn't started one."""
        c = self._crews.get(token_id)
        if c is None or c.wind_from is None:
            return []
        reach = min(LINE_LENGTH / 2, LINE_RATE * (tick - c.since - CREW_RAMP_TICKS))
        if reach <= 0:
            return []
        b = math.radians(c.wind_from)
        ux, uy = math.sin(b) * reach, -math.cos(b) * reach
        return [[round(c.x - ux, 2), round(c.y - uy, 2)], [round(c.x + ux, 2), round(c.y + uy, 2)]]

    def line_growing(self, tick: int) -> bool:
        """True while any crew's line is still being cut, so the map keeps up."""
        return any(c.wind_from is not None and tick - c.since < CREW_RAMP_TICKS + LINE_LENGTH / 2 / LINE_RATE
                   for c in self._crews.values())

    def water_ready_in(self, tick: int) -> dict[str, int]:
        """Ticks until each water token can drop again (0 = ready once moved),
        for the console's cooldown display."""
        return {k: max(0, WATER_COOLDOWN_TICKS - (tick - w.dropped)) for k, w in self._water.items()}

    def _dist(self, x: float, y: float) -> np.ndarray:
        return np.hypot(self._cx - x, self._cy - y)

    def _disk(self, x: float, y: float, radius: float) -> np.ndarray:
        return soft_disk(self._dist(x, y), radius)

    def _crew(self, t: Token, tick: int, start: int | None = None) -> TimedLayer:
        c = self._crews.get(t.id)
        if c is None or math.hypot(t.x - c.x, t.y - c.y) > CREW_MOVE_RESET:
            begun = tick if start is None else start
            c = self._crews[t.id] = _Crew(t.x, t.y, begun, self.wind_from, begun)
        else:
            c.x, c.y = t.x, t.y  # follow jitter without restarting the ramp
            if start is not None and start > c.since:
                # A relief crew took over (#178): a fresh shift, already dug in
                # (it takes over the same ground), carrying on the same line.
                c.since = start
        dug_in = c.since > c.line_since  # a relief crew starts at full strength
        ramp = 1.0 if dug_in else min(1.0, (tick - c.since) / CREW_RAMP_TICKS)
        layer = TimedLayer(self._disk(t.x, t.y, CREW_RADIUS), CREW_MAX * ramp, CREW_MAX / CREW_RAMP_TICKS, CREW_MAX,
                           fade_at=c.since + SHIFT_TICKS - tick)
        return self._with_line(layer, t.x, t.y, c.wind_from, tick - c.line_since)

    def _with_line(self, layer: TimedLayer, x: float, y: float, wind_from: float | None, age: int) -> TimedLayer:
        """Add the line a crew `age` ticks into its job cuts (none without a wind)."""
        if wind_from is not None:
            layer.line_along, layer.line_band = line_along(self._cx, self._cy, x, y, wind_from)
            layer.line_reach0 = LINE_RATE * (age - CREW_RAMP_TICKS)
            layer.line_rate = LINE_RATE
        return layer

    def _water_drop(self, t: Token, tick: int, start: int | None = None) -> TimedLayer:
        w = self._water.get(t.id)
        if start is not None:
            # Dispatched (#178): each tanker arrival is a drop, wherever the
            # token is then; the round trip to reload sets the pace.
            if w is None or w.dropped != start:
                w = self._water[t.id] = _Water(t.x, t.y, start)
        else:
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
