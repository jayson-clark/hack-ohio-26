"""What the commander announces on its own, and when (PLAN.md, Incident commander).

Two parts, neither of which needs an LLM. This is also what keeps the demo
talking with no API key or no network:

- ForecastWatcher turns each new forecast into events: a town becomes
  threatened, a threatened town is safe again, or the forecast shifted.
  Thresholds have hysteresis so a town hovering near the line doesn't
  chatter. Route events (road_cut, route_changed, no_safe_route) come from
  the router.
- BriefingQueue decides which event to say next: highest priority first
  (oldest first within a priority), at most one briefing every MIN_GAP_S of wall time, no repeats of the same
  thing about the same town within DEDUPE_S, and nothing stale.

Each event's text is already a complete spoken sentence built from the
simulation's own numbers, so a briefing is grounded by construction.
"""

from dataclasses import dataclass, field

import numpy as np

from protocol import CommanderKind, CommanderMessage, EndReason, Event, EventKind, Score
from sim.fire import SIM_MINUTES_PER_TICK
from uq.mc import wilson

# A town is threatened once the *lower* end of the 90% interval on "fire
# reaches it within 30 min" is at least 50%: more likely than not, even
# allowing for having only N simulations (#11). It's safe again once the
# *upper* end is under 50% for SAFE_CONFIRMATIONS forecasts in a row. The gap
# between the two is the hysteresis.
THREAT_LEVEL = 0.5
SAFE_CONFIRMATIONS = 2
SHIFT_IOU = 0.6  # next-hour burn envelope overlap below this counts as a shift
SHIFT_MIN_TICKS = 30  # at most one shift event per this many ticks
SHIFT_TOWARD = 0.25  # a town's 60-min reach share has to grow this much to be named

PRIORITY = {
    EventKind.NO_SAFE_ROUTE: 0,
    EventKind.TOWN_THREATENED: 0,
    EventKind.ROAD_CUT: 1,
    EventKind.ROUTE_CHANGED: 1,
    EventKind.FORECAST_SHIFT: 2,
    EventKind.TOWN_SAFE: 3,
    EventKind.ROUND_ENDED: 0,
}
MIN_GAP_S = 8.0  # wall seconds between spoken briefings
DEDUPE_S = 45.0  # don't repeat the same kind of news about the same town
STALE_S = 20.0  # drop news that waited this long in wall time...
# ...or this long in sim time. The sim can run up to 8x (#71), where 8 s of
# wall time is over an hour of fire: "within 30 minutes" is meaningless by then.
STALE_SIM_MIN = 15.0


_END = {
    EndReason.TIME: "time ran out",
    EndReason.CONTAINED: "the fire is out",
    EndReason.STOPPED: "it was stopped",
}


def round_summary(score: Score) -> str:
    """'The round is over: time ran out. 1,240 of 52,000 people evacuated, ...'"""
    why = _END.get(score.end_reason, "it ended")
    return (
        f"The round is over: {why}. {score.people_evacuated:,} of {score.people_total:,} people evacuated, "
        f"{score.structures_lost:,} of {score.structures_total:,} structures lost, "
        f"and {round(score.acres_burned):,} acres burned."
    )


def _interval(reach: dict | None) -> tuple[float, float]:
    """90% Wilson interval on a reach count; (0, 0) when there's no forecast."""
    if not reach or not reach["of"]:
        return 0.0, 0.0
    return wilson(reach["simulations"], reach["of"])


def _share(reach: dict | None) -> float:
    return reach["simulations"] / reach["of"] if reach and reach["of"] else 0.0


def threatened_text(row: dict) -> str:
    """'Paradise is threatened: fire reaches it within 30 minutes in 24 of 32 simulations, ...'"""
    r30 = row["fire_reaches_within_30_min"]
    text = f"{row['town']} is threatened: fire reaches it within 30 minutes in {r30['simulations']} of {r30['of']} simulations"
    if row.get("median_minutes_until_fire") is not None:
        text += f", about {row['median_minutes_until_fire']} minutes out"
    evac = row.get("evacuation")
    if evac and evac["status"] == "cut":
        text += ". Its way out is cut"
    elif evac and evac["exit"]:
        text += f". Evacuate toward {evac['exit']}"
    return text + "."


@dataclass
class ForecastWatcher:
    threatened: set[str] = field(default_factory=set)
    _calm: dict[str, int] = field(default_factory=dict)
    _envelope: np.ndarray | None = None
    _reach60: dict[str, float] = field(default_factory=dict)
    _last_shift: int = -SHIFT_MIN_TICKS

    def reset(self) -> None:
        self.threatened.clear()
        self._calm.clear()
        self._envelope = None
        self._reach60.clear()
        self._last_shift = -SHIFT_MIN_TICKS

    def update(self, tick: int, towns: list[dict], probability: np.ndarray) -> list[Event]:
        """`towns` is get_situation()["towns"]; `probability` is the forecast's
        (horizons, H, W) P(burn) stack, last horizon = T+60."""
        events = []
        for row in towns:
            name = row["town"]
            lo, hi = _interval(row.get("fire_reaches_within_30_min"))
            hot = row.get("fire_inside_town_now", False)
            if name not in self.threatened:
                if lo >= THREAT_LEVEL or hot:
                    self.threatened.add(name)
                    self._calm.pop(name, None)
                    text = f"Fire is inside {name}." if hot and lo < THREAT_LEVEL else threatened_text(row)
                    events.append(Event(kind=EventKind.TOWN_THREATENED, tick=tick, town=name, text=text))
            elif hi < THREAT_LEVEL and not hot:
                self._calm[name] = self._calm.get(name, 0) + 1
                if self._calm[name] >= SAFE_CONFIRMATIONS:
                    self.threatened.discard(name)
                    self._calm.pop(name)
                    events.append(Event(kind=EventKind.TOWN_SAFE, tick=tick, town=name,
                                        text=f"{name} is out of the fire's path for the next half hour."))
            else:
                self._calm.pop(name, None)

        reach60 = {row["town"]: _share(row.get("fire_reaches_within_60_min")) for row in towns}
        envelope = probability[-1] >= 0.5
        if self._envelope is not None and tick - self._last_shift >= SHIFT_MIN_TICKS:
            union = (envelope | self._envelope).sum()
            if union > 20 and (envelope & self._envelope).sum() / union < SHIFT_IOU:
                self._last_shift = tick
                gains = {t: reach60[t] - self._reach60.get(t, 0.0) for t in reach60}
                toward = max(gains, key=gains.get) if gains else None
                if toward and gains[toward] >= SHIFT_TOWARD:
                    text = f"The forecast has shifted: the fire is now heading toward {toward}."
                else:
                    text = "The forecast has shifted: the fire's path for the next hour has moved."
                events.append(Event(kind=EventKind.FORECAST_SHIFT, tick=tick, town=toward, text=text))
        self._envelope = envelope
        self._reach60 = reach60
        return events


@dataclass
class _Pending:
    event: Event
    since: float


@dataclass
class BriefingQueue:
    pending: list[_Pending] = field(default_factory=list)
    _said: dict[tuple, float] = field(default_factory=dict)
    _last_spoken: float = -MIN_GAP_S

    def reset(self) -> None:
        self.pending.clear()
        self._said.clear()
        self._last_spoken = -MIN_GAP_S

    def offer(self, events: list[Event], now: float) -> None:
        for e in events:
            if e.kind == EventKind.ROUND_ENDED:
                # Nothing else about the fire matters once the round is over.
                self.pending = [_Pending(e, now)]
                continue
            key = (e.kind, e.town)
            if now - self._said.get(key, -DEDUPE_S) < DEDUPE_S:
                continue
            # "No safe way out" says everything a road cut or reroute would.
            if e.kind == EventKind.NO_SAFE_ROUTE:
                self.pending = [p for p in self.pending if not (
                    p.event.town == e.town and p.event.kind in (EventKind.ROAD_CUT, EventKind.ROUTE_CHANGED))]
            elif e.kind in (EventKind.ROAD_CUT, EventKind.ROUTE_CHANGED) and any(
                    p.event.town == e.town and p.event.kind == EventKind.NO_SAFE_ROUTE for p in self.pending):
                continue
            self.pending = [p for p in self.pending if (p.event.kind, p.event.town) != key]
            self.pending.append(_Pending(e, now))

    def next(self, now: float, tick: int, paused: bool = False) -> CommanderMessage | None:
        """The briefing to say now, if any. `now` is wall time, `tick` the sim tick.

        News expires after STALE_S of wall time or STALE_SIM_MIN of sim time,
        whichever comes first, so a fast sim doesn't announce history. While
        paused nothing is said and nothing expires: the sim isn't moving, so
        the news is still true when play resumes."""
        if paused:
            for p in self.pending:
                p.since = now
            return None
        self.pending = [
            p for p in self.pending
            if now - p.since < STALE_S and (tick - p.event.tick) * SIM_MINUTES_PER_TICK <= STALE_SIM_MIN
        ]
        if not self.pending or now - self._last_spoken < MIN_GAP_S:
            return None
        # Oldest first within a priority, so urgent news can't be starved by newer news.
        best = min(self.pending, key=lambda p: (PRIORITY[p.event.kind], p.since))
        self.pending.remove(best)
        e = best.event
        self._said[(e.kind, e.town)] = now
        self._last_spoken = now
        return CommanderMessage(kind=CommanderKind.BRIEFING, tick=e.tick, text=e.text, grounded=True, event=e.kind)
