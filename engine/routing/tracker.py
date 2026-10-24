"""Keeps the routes on screen steady (PLAN.md, Evacuation routing).

Every forecast produces a fresh best route per town, and with stochastic
rollouts the best one can flip back and forth between two near-equal roads.
Routes that jump around look broken, so a town keeps its current route
unless:

- that route is now cut (a road on it is burning, or is near-certain to burn
  before the bus gets there), or
- the new best route is clearly cheaper (by SWITCH_MARGIN of the current
  route's cost, which already includes the burn-risk penalty), and the
  current route has been shown for at least MIN_DWELL_TICKS.

Each switch comes with an Event that says why, for the event log and the
commander's briefings.
"""

from dataclasses import dataclass, field

from protocol import Event, EventKind
from routing.evac import Route

SWITCH_MARGIN = 0.15
MIN_DWELL_TICKS = 20  # sim ticks (2 s of wall time at 10 Hz)
RISK_GAP = 0.1  # how much riskier the old route must be to call it "likely to burn"


@dataclass
class RouteTracker:
    shown: dict[str, Route] = field(default_factory=dict)
    since: dict[str, int] = field(default_factory=dict)

    def reset(self) -> None:
        self.shown.clear()
        self.since.clear()

    def held(self) -> dict[str, tuple[list[int], list[int]]]:
        """Node and edge paths of the routes on screen, for replan_routes."""
        return {k: (r.nodes, r.edges) for k, r in self.shown.items() if r.edges}

    def choose(self, best: list[Route], rescored: dict[str, Route], tick: int) -> tuple[list[Route], list[Event]]:
        """Pick what to show for each town, given the new best routes and the
        current ones re-scored under the same forecast."""
        out, events = [], []
        for new in best:
            key = new.key
            old = self.shown.get(key)
            current = rescored.get(key)
            pick, event = self._pick(new, old, current, tick)
            if pick is not old and (old is None or pick.edges != old.edges):
                self.since[key] = tick
            self.shown[key] = pick
            out.append(pick)
            if event:
                events.append(event)
        # Drop buses that left the table.
        for key in set(self.shown) - {r.key for r in best}:
            self.shown.pop(key)
            self.since.pop(key, None)
        return out, events

    def _pick(self, new: Route, old: Route | None, current: Route | None, tick: int) -> tuple[Route, Event | None]:
        if old is None:
            return new, None
        if new.status == "cut":
            if old.status == "cut":
                return new, None
            return new, Event(kind=EventKind.NO_SAFE_ROUTE, tick=tick, town=new.town,
                              text=f"{new.town} has no safe way out.")
        if current is None or new.edges == old.edges:
            # First route after a cut, a bus that moved, or the same road
            # with fresh numbers.
            return new, None
        if current.status == "cut":
            return new, self._changed(new, old, tick, "is cut")
        dwelt = tick - self.since.get(new.key, tick) >= MIN_DWELL_TICKS
        if dwelt and new.cost < current.cost * (1 - SWITCH_MARGIN):
            likely = current.risk >= new.risk + RISK_GAP
            return new, self._changed(new, old, tick, "is likely to burn first" if likely else None)
        return current, None

    @staticmethod
    def _changed(new: Route, old: Route, tick: int, problem: str | None) -> Event:
        """`problem` is what's wrong with the old route ("is cut"), or None
        when the new one is simply faster."""
        if new.safe_zone == old.safe_zone:
            text = f"Rerouting {new.town} by another road to {new.safe_zone}"
            why = f"the current road {problem}" if problem else "it's faster"
        else:
            text = f"Rerouting {new.town} to {new.safe_zone}"
            why = f"the route to {old.safe_zone} {problem}" if problem else "it's faster"
        return Event(kind=EventKind.ROUTE_CHANGED, tick=tick, town=new.town, text=f"{text}: {why}.")
