"""Several fires on one map (#179): which burning cells belong to which incident.

The fire model doesn't care how many fires there are; the operator does,
because units have to be split between them. This keeps an owner per cell:

- Every ignition opens an incident, named after the nearest place ("Pulga
  Fire"). Ignitions inside a burning incident just add to it.
- Each tick, newly lit cells take the owner of a lit neighbour (8-connected),
  so an incident grows with its fire.
- A cell with no lit neighbour is a spot fire. Inside the calibrated T+60
  envelope (the outline the console draws, #12) it belongs to the nearest
  incident; outside it, it starts a new incident. Before the first forecast
  there's no envelope, so a spot within SPOT_MAX (the farthest an ember flies)
  of an incident joins it: embers come from somewhere.
- When two incidents burn into each other, the older id survives and takes the
  younger's cells.

Ids are stable strings ("inc-1", "inc-2", ...) so recommendations, threats and
orders can name the incident they're about (Incident in protocol.py).
"""

import math
from collections import deque
from dataclasses import dataclass, field

import numpy as np

from protocol import Incident
from scenario import Scenario
from sim.fire import BURNED, BURNING, SIM_MINUTES_PER_TICK, SPOT_MAX

SQ_M_PER_ACRE = 4046.86
GROWTH_WINDOW_TICKS = int(60 / SIM_MINUTES_PER_TICK)  # growth is reported per sim hour


@dataclass
class _Inc:
    id: str
    name: str
    started_tick: int
    seed: tuple[float, float]
    history: deque = field(default_factory=lambda: deque(maxlen=GROWTH_WINDOW_TICKS + 1))  # (tick, cells)


def _neighbour_max(a: np.ndarray) -> np.ndarray:
    """Each cell's largest 8-neighbour value (0 outside the grid)."""
    p = np.pad(a, 1)
    h, w = a.shape
    out = np.zeros_like(a)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy or dx:
                np.maximum(out, p[1 + dy : 1 + dy + h, 1 + dx : 1 + dx + w], out=out)
    return out


class IncidentTracker:
    def __init__(self, scenario: Scenario) -> None:
        self.scenario = scenario
        # Places worth naming a fire after (terrain.json's places), minus the
        # markers of where the real fire started ("Camp Fire origin Fire").
        self._places = [(p.name, p.x, p.y) for p in scenario.places if "origin" not in p.name.lower()]
        self.reset()

    def reset(self) -> None:
        self.owner = np.zeros((self.scenario.height, self.scenario.width), np.int32)  # 0 = none
        self.incidents: dict[int, _Inc] = {}
        self._next = 1
        self.changed = True  # tells the engine to send the list

    # --- ignitions --------------------------------------------------------------

    def ignite(self, x: float, y: float, tick: int, radius: float = 2.0) -> str:
        """An ignition at (x, y): joins the incident burning there, or opens one."""
        h, w = self.owner.shape
        cy, cx = int(min(max(y, 0), h - 1)), int(min(max(x, 0), w - 1))
        r = int(math.ceil(radius)) + 1
        near = self.owner[max(cy - r, 0) : cy + r + 1, max(cx - r, 0) : cx + r + 1]
        ids = near[near > 0]
        if ids.size:
            k = int(ids.min())  # the oldest incident already there
        else:
            k = self._open(x, y, tick)
        ys, xs = np.ogrid[:h, :w]
        disk = (xs + 0.5 - x) ** 2 + (ys + 0.5 - y) ** 2 <= radius**2
        self.owner[disk & (self.owner == 0)] = k
        return self.incidents[k].id

    def _open(self, x: float, y: float, tick: int) -> int:
        k = self._next
        self._next += 1
        self.incidents[k] = _Inc(f"inc-{k}", self._name(x, y), tick, (x, y))
        self.changed = True
        return k

    def _name(self, x: float, y: float) -> str:
        """"<nearest place> Fire", made unique if that place already has one."""
        base = min(self._places, key=lambda p: (p[1] - x) ** 2 + (p[2] - y) ** 2)[0] if self._places else "Unnamed"
        taken = {i.name for i in self.incidents.values()}
        name, n = f"{base} Fire", 2
        while name in taken:
            name, n = f"{base} Fire {n}", n + 1
        return name

    # --- the tick ---------------------------------------------------------------

    def update(self, state: np.ndarray, tick: int, envelope: np.ndarray | None = None) -> None:
        """Assign newly lit cells after a sim step. `envelope` is the
        calibrated T+60 envelope (bool grid), which decides spot fires."""
        lit = (state == BURNING) | (state == BURNED)
        new = lit & (self.owner == 0)
        if new.any():
            # Grow from lit neighbours. A few passes cover cells that lit in a
            # chain within one tick; what's left has no owned neighbour.
            for _ in range(4):
                take = _neighbour_max(self.owner) * new
                got = take > 0
                if not got.any():
                    break
                self.owner[got] = take[got]
                new &= ~got
            if new.any():
                self._spots(new, tick, envelope)
        self._merge(lit)
        for k, inc in self.incidents.items():
            inc.history.append((tick, int((self.owner == k).sum())))

    def _spots(self, new: np.ndarray, tick: int, envelope: np.ndarray | None) -> None:
        for y, x in zip(*np.nonzero(new)):
            if self.owner[y, x]:
                continue  # claimed by an earlier spot this tick
            if envelope is not None:
                k = self._nearest(x + 0.5, y + 0.5) if envelope[y, x] else None
            else:
                k = self._nearest(x + 0.5, y + 0.5, within=SPOT_MAX)
            if k is None:
                k = self._open(float(x) + 0.5, float(y) + 0.5, tick)
            self.owner[y, x] = k
            # Take the rest of this spot's cluster along with it.
            cluster = np.zeros_like(new)
            cluster[y, x] = True
            for _ in range(8):
                grow = (_neighbour_max(cluster.astype(np.int32)) > 0) & new & ~cluster
                if not grow.any():
                    break
                cluster |= grow
            self.owner[cluster] = k

    def _merge(self, lit: np.ndarray) -> None:
        """Incidents touching each other merge into the older (lower) id."""
        while True:
            hi = _neighbour_max(self.owner)
            # A lit cell whose neighbour belongs to a younger incident.
            touch = lit & (self.owner > 0) & (hi > self.owner)
            if not touch.any():
                return
            y, x = np.argwhere(touch)[0]
            keep, gone = int(self.owner[y, x]), int(hi[y, x])
            self.owner[self.owner == gone] = keep
            del self.incidents[gone]
            self.changed = True

    # --- reporting --------------------------------------------------------------

    def _nearest(self, x: float, y: float, within: float = math.inf) -> int | None:
        """The incident with a cell nearest (x, y), if one is within `within` cells."""
        ys, xs = np.nonzero(self.owner)
        if len(xs) == 0:
            return None
        d2 = (xs + 0.5 - x) ** 2 + (ys + 0.5 - y) ** 2
        i = int(np.argmin(d2))
        return int(self.owner[ys[i], xs[i]]) if d2[i] <= within**2 else None

    def of(self, x: float, y: float) -> str | None:
        """The incident at (x, y), or the nearest one (an order placed ahead of
        a fire is about that fire); None when nothing has burned."""
        h, w = self.owner.shape
        k = int(self.owner[int(min(max(y, 0), h - 1)), int(min(max(x, 0), w - 1))]) or self._nearest(x, y)
        return self.incidents[k].id if k in self.incidents else None

    def report(self, state: np.ndarray) -> list[Incident]:
        acres = self.scenario.cell_size_m**2 / SQ_M_PER_ACRE
        burning = state == BURNING
        out = []
        for k, inc in sorted(self.incidents.items()):
            mine = self.owner == k
            cells = int(mine.sum())
            if cells == 0:
                continue
            ys, xs = np.nonzero(mine & burning)
            active = len(xs) > 0
            if not active:
                ys, xs = np.nonzero(mine)
            t0, c0 = inc.history[0] if inc.history else (0, cells)
            t1, c1 = inc.history[-1] if inc.history else (0, cells)
            hours = max((t1 - t0) / GROWTH_WINDOW_TICKS, 1e-9)
            out.append(Incident(
                id=inc.id, name=inc.name, acres=round(cells * acres, 1),
                growth_ac_h=round((c1 - c0) * acres / hours, 1) if t1 > t0 else 0.0,
                x=round(float(xs.mean()) + 0.5, 2), y=round(float(ys.mean()) + 0.5, 2),
                started_tick=inc.started_tick, active=active,
            ))
        return out
