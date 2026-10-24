"""Fire units come from stations; a token is an order, not a teleport (#104).

Without this, a crew placed next to a fresh ignition held it from the first
tick, so instant initial attack contained every fire in about an hour.
Now each crew, firebreak (dozer) or water token is an order:

- The fastest free unit of that type is sent: a ground unit from a fire
  station by road (routing/units.py), or a tanker from an air base by air.
  Tankers are grounded above TANKER_MAX_WIND_MS; the order waits.
- The token only reaches the fire model (TokenEffects) once its unit
  arrives. A crew starts digging in from then, a dozer starts cutting line,
  a tanker drops.
- Moving a token re-routes its unit from where it is. Removing one frees
  the unit. A road burning across a unit's route mid-trip makes it re-route,
  or report "blocked" if nothing gets through; blocked and grounded orders
  are retried every RETRY_TICKS.
- Buses aren't dispatched: they're the operator's own and act at once.

The round's limits (sim/game.py) still decide which tokens count at all;
the dispatcher only sees those.
"""

import math
from dataclasses import dataclass, field

import numpy as np

from protocol import Token, TokenType
from routing.units import TANKER_MAX_WIND_MS, TURNOUT_MIN, Station, UnitRouter
from sim.effects import CREW_MOVE_RESET
from sim.fire import SIM_MINUTES_PER_TICK

DISPATCHED = {TokenType.CREW: "ground", TokenType.FIREBREAK: "ground", TokenType.WATER: "air"}
RETRY_TICKS = 5


@dataclass
class Unit:
    id: str  # "Jarbo Gap Station 36 crew"
    station: Station
    token_type: TokenType
    status: str = "available"  # available | en_route | working | blocked | grounded
    token_id: str | None = None
    target: tuple[float, float] | None = None  # where it was sent (the token's position then)
    origin: tuple[float, float] | None = None  # where this trip started
    depart_tick: int = 0
    arrive_tick: int = 0
    path: list[list[float]] = field(default_factory=list)  # map coords, origin to target
    edges: list[int] = field(default_factory=list)  # road edge ids on a ground route
    retry_tick: int = 0

    @property
    def home(self) -> tuple[float, float]:
        return self.station.x, self.station.y

    def position(self, tick: int) -> tuple[float, float]:
        """Where it is now: along its path while en route, else at its target or home."""
        if self.status != "en_route" or len(self.path) < 2:
            return self.target if self.status == "working" and self.target else self.home
        frac = (tick - self.depart_tick) / max(self.arrive_tick - self.depart_tick, 1e-9)
        return _along(self.path, min(max(frac, 0.0), 1.0))


def _along(path: list[list[float]], frac: float) -> tuple[float, float]:
    """The point `frac` of the way along a polyline (by length)."""
    seg = [math.dist(a, b) for a, b in zip(path, path[1:])]
    total = sum(seg)
    if total == 0:
        return tuple(path[-1])
    left = frac * total
    for (a, b), d in zip(zip(path, path[1:]), seg):
        if left <= d and d > 0:
            f = left / d
            return a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1])
        left -= d
    return tuple(path[-1])


@dataclass
class DispatchEvent:
    kind: str  # "blocked" | "grounded" | "arrived"
    unit: Unit
    text: str


class Dispatcher:
    def __init__(self, stations: list[Station], router: UnitRouter | None) -> None:
        self.router = router
        self.units: list[Unit] = []
        for st in stations:
            for t, count in st.units.items():
                for i in range(count):
                    suffix = f" {i + 1}" if count > 1 else ""
                    label = {"crew": "crew", "firebreak": "dozer", "water": "tanker"}.get(t, t)
                    self.units.append(Unit(f"{st.name} {label}{suffix}", st, TokenType(t)))
        self.events: list[DispatchEvent] = []

    def reset(self) -> None:
        for u in self.units:
            self._free(u)
        self.events.clear()

    # --- the tick ------------------------------------------------------------------

    def update(self, tokens: list[Token], tick: int, wind_ms: float, closed: np.ndarray | None) -> list[Token]:
        """Assign, move and arrive units for this tick. Returns the tokens that
        act on the fire now: buses, plus dispatched tokens whose unit is there.
        With no units at all (no stations), every token acts at once."""
        if not self.units:
            return tokens
        if self.router is not None and closed is not None:
            self.router.refresh(closed)
        live = {t.id: t for t in tokens if t.token_type in DISPATCHED}
        # Tokens that left the table free their units.
        for u in self.units:
            if u.token_id is not None and u.token_id not in live:
                self._free(u)
        by_token = {u.token_id: u for u in self.units if u.token_id is not None}
        for t in live.values():
            u = by_token.get(t.id)
            if u is None:
                self._assign(t, tick, wind_ms)
                continue
            moved = u.target is not None and math.dist(u.target, (t.x, t.y)) > CREW_MOVE_RESET
            if moved:
                self._send(u, t, tick, wind_ms, start=u.position(tick))
            elif u.status in ("blocked", "grounded") and tick >= u.retry_tick:
                self._send(u, t, tick, wind_ms, start=u.home)
            elif u.status == "en_route" and self._path_cut(u):
                self._send(u, t, tick, wind_ms, start=u.position(tick))
            if u.status == "en_route" and tick >= u.arrive_tick:
                u.status = "working"
                self.events.append(DispatchEvent("arrived", u, f"{u.id} is on scene."))
        working = {u.token_id for u in self.units if u.status == "working"}
        return [t for t in tokens if t.token_type not in DISPATCHED or t.id in working]

    def pending(self) -> list[Unit]:
        return [u for u in self.units if u.status == "en_route"]

    def take_events(self) -> list[DispatchEvent]:
        out, self.events = self.events, []
        return out

    # --- arrival-time maps (recommendations) ----------------------------------------

    def eta_grid(self, token_type: TokenType, wind_ms: float) -> np.ndarray:
        """Minutes for the fastest *free* unit of this type to reach every
        cell, float (H, W): turnout plus travel. inf where none can."""
        free = [u for u in self.units if u.token_type == token_type and u.status == "available"]
        h, w = self.router.cell_node.shape if self.router else (0, 0)
        best = np.full((h, w), np.inf)
        for st in {u.station.name: u.station for u in free}.values():
            if st.kind == "air":
                if wind_ms < TANKER_MAX_WIND_MS:
                    np.minimum(best, self.router.air_grid(st.x, st.y), out=best)
            else:
                np.minimum(best, self.router.ground_grid(st.x, st.y), out=best)
        return best + TURNOUT_MIN

    def eta_from(self, x: float, y: float) -> np.ndarray:
        """Minutes for a ground unit already at (x, y) to reach every cell (a crew being moved)."""
        return self.router.ground_grid(x, y)

    # --- internals --------------------------------------------------------------------

    def _assign(self, t: Token, tick: int, wind_ms: float) -> None:
        free = [u for u in self.units if u.token_type == t.token_type and u.status == "available"]
        if not free or self.router is None:
            return  # nothing left to send: the round's limit, or no stations of this kind
        best = min(free, key=lambda u: self._eta(u, u.home, (t.x, t.y), wind_ms)[0])
        self._send(best, t, tick, wind_ms, start=best.home)

    def _eta(self, u: Unit, start, target, wind_ms: float) -> tuple[float, list[list[float]]]:
        if u.station.kind == "air":
            if wind_ms >= TANKER_MAX_WIND_MS:
                return math.inf, []
            return self.router.air_eta(*start, *target), [list(start), list(target)]
        return self.router.ground_eta(*start, *target)

    def _send(self, u: Unit, t: Token, tick: int, wind_ms: float, start) -> None:
        eta, path = self._eta(u, start, (t.x, t.y), wind_ms)
        u.token_id, u.target, u.origin = t.id, (t.x, t.y), tuple(start)
        if not math.isfinite(eta):
            grounded = u.station.kind == "air"
            u.status, u.path, u.retry_tick = ("grounded" if grounded else "blocked"), [], tick + RETRY_TICKS
            text = (f"Tankers are grounded: wind is over {TANKER_MAX_WIND_MS:.0f} m/s." if grounded
                    else f"No open road gets {u.id} there; it will keep trying.")
            self.events.append(DispatchEvent(u.status, u, text))
            return
        turnout = TURNOUT_MIN if start == u.home else 0.0
        u.status, u.path, u.depart_tick = "en_route", path, tick
        u.edges = self._edge_ids(path) if u.station.kind == "ground" else []
        u.arrive_tick = tick + int(math.ceil((eta + turnout) / SIM_MINUTES_PER_TICK))

    def _edge_ids(self, path: list[list[float]]) -> list[int]:
        """Road edges along a ground route (its inner points are road nodes)."""
        net = self.router.net
        nodes = [net.nearest_node(x, y) for x, y in path[1:-1]]
        out = []
        for a, b in zip(nodes, nodes[1:]):
            data = net.graph.get_edge_data(a, b)
            if data is not None:
                out.append(int(data["eid"]))
        return out

    def _path_cut(self, u: Unit) -> bool:
        """Whether a road on a ground unit's route has started burning."""
        return bool(u.edges) and self.router is not None and bool(self.router.closed[u.edges].any())

    def _free(self, u: Unit) -> None:
        u.status, u.token_id, u.target, u.origin, u.path, u.edges = "available", None, None, None, [], []
