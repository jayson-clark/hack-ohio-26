"""The incident commander's simulation tools (PLAN.md, Incident commander).

The LLM never sees grids or raw engine state. It calls these, and each
returns a short JSON-able dict computed from the live forecast, routes and
recommendations, so every number it says comes from a real simulation call.
The same functions back the rule-based briefings, so nothing here needs an
LLM.

Probabilities are reported as plain counts ("in 6 of 32 simulations").
Intervals come later (#11, #13).

Slow tools (what-ifs, placements) run in the Recommender worker with a
timeout, so a question never stalls the tick loop.
"""

import asyncio
import math
from typing import TYPE_CHECKING

import numpy as np

from forecast.recommend import TownInfo, evaluate_spots
from forecast.rollout import rollout
from sim.fire import BURNED, BURNING, SIM_MINUTES_PER_TICK, FireSnapshot, Wind

if TYPE_CHECKING:
    from server import Engine

# Long enough for a 16-rollout what-if on a big fire, short enough to answer in a few seconds.
TOOL_TIMEOUT_S = 3.0
WHATIF_ROLLOUTS = 16
PLACEMENT_ROLLOUTS = 8
SQ_M_PER_ACRE = 4046.86
COMPASS = ["north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west"]


def compass(deg: float) -> str:
    return COMPASS[round((deg % 360) / 45) % 8]


# --- Tool definitions, in the Messages API's tool format --------------------

TOOL_SPECS = [
    {
        "name": "get_situation",
        "description": (
            "The current fire picture: wind, acres burning and burned, and for every town how many of the "
            "forecast's simulations have the fire reaching it within 30 and 60 minutes, the median time until "
            "it does, and the town's evacuation route. Call this before any briefing or status answer."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
    },
    {
        "name": "forecast_whatif",
        "description": (
            "Re-run the fire forecast from right now under a hypothetical wind, and compare it with the "
            "current forecast town by town. Use for questions like 'what if the wind shifts west?'. "
            "wind_from is the compass direction the wind blows FROM (a west wind blows from the west)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "wind_from": {"type": "string", "enum": COMPASS},
                "wind_speed_ms": {
                    "type": ["number", "null"],
                    "description": "Wind speed in m/s; null keeps the current speed.",
                },
            },
            "required": ["wind_from", "wind_speed_ms"],
            "additionalProperties": False,
        },
    },
    {
        "name": "evaluate_placement",
        "description": (
            "Simulate placing a fire crew at a spot, against not placing it, on identical simulations. "
            "Returns how often it keeps the fire out of each town, how much less of each town burns, and "
            "acres saved over the next hour. Give a place name (a town, an exit or a landmark) or map "
            "coordinates."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "place": {"type": ["string", "null"], "description": "e.g. 'Magalia'; null if using x and y."},
                "x": {"type": ["number", "null"]},
                "y": {"type": ["number", "null"]},
            },
            "required": ["place", "x", "y"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_routes",
        "description": (
            "Every town's current evacuation route: status (clear, risky or cut), which exit, drive time, "
            "and the chance the worst road on it burns before the bus passes. Also the latest reroutes."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
    },
]


# --- Worker-side jobs (picklable, run in the Recommender process) -----------

def _town_arrivals(first_burn: np.ndarray, masks: np.ndarray, elapsed: float) -> np.ndarray:
    """(n, T) ticks from now until the fire first enters each town; inf if not in the forecast."""
    n = first_burn.shape[0]
    fb = first_burn.reshape(n, -1)
    out = np.full((n, masks.shape[0]), np.inf, np.float32)
    for t, m in enumerate(masks.reshape(masks.shape[0], -1)):
        out[:, t] = fb[:, m].min(axis=1) if m.any() else np.inf
    return np.maximum(out - elapsed, 0.0)


def _masks(towns: list[TownInfo], h: int, w: int) -> np.ndarray:
    cy, cx = np.mgrid[:h, :w].astype(np.float32) + 0.5
    return np.stack([np.hypot(cx - t.x, cy - t.y) <= t.radius for t in towns])


def whatif_job(snapshot: FireSnapshot, wind: Wind, towns: list[TownInfo], n: int, ticks: int, seed: int):
    first = rollout(snapshot, n, ticks, wind=wind, seed=seed)
    h, w = snapshot.state.shape
    arrivals = _town_arrivals(first, _masks(towns, h, w), 0.0)
    return arrivals, float(np.isfinite(first).sum(axis=(1, 2)).mean())


def placement_job(snapshot: FireSnapshot, x: float, y: float, towns: list[TownInfo], n: int, seed: int):
    return evaluate_spots(snapshot, [(x, y)], towns, n=n, seed=seed)[0]


# --- The tools ---------------------------------------------------------------

class CommanderTools:
    def __init__(self, engine: "Engine") -> None:
        self.e = engine
        s = engine.scenario
        self.acres_per_cell = s.cell_size_m**2 / SQ_M_PER_ACRE
        self.masks = _masks(engine.towns, s.height, s.width) if engine.towns else np.zeros((0, s.height, s.width), bool)
        self.places = self._place_index()

    async def call(self, name: str, args: dict) -> dict:
        """Run a tool by name. Errors come back as {"error": ...} for the model to read."""
        fn = {
            "get_situation": self.get_situation,
            "forecast_whatif": self.forecast_whatif,
            "evaluate_placement": self.evaluate_placement,
            "get_routes": self.get_routes,
        }.get(name)
        if fn is None:
            return {"error": f"unknown tool {name}"}
        try:
            result = fn(**args)
            if asyncio.iscoroutine(result):
                result = await asyncio.wait_for(result, TOOL_TIMEOUT_S)
            return result
        except asyncio.TimeoutError:
            return {"error": "the simulation took too long; try again in a moment"}
        except (TypeError, ValueError) as err:
            return {"error": str(err)}

    # get_situation ---------------------------------------------------------

    def get_situation(self) -> dict:
        e = self.e
        burning, burned = e.fire.counts()
        f = e.latest_forecast
        out = {
            "sim_minutes_elapsed": round(e.fire.tick * SIM_MINUTES_PER_TICK),
            "wind": self._wind(e.fire.wind),
            "fire": {
                "burning_acres": self._acres(burning),
                "burned_acres": self._acres(burned),
                "active": burning > 0,
            },
            "forecast_age_minutes": None if f is None else round((e.fire.tick - f.tick) * SIM_MINUTES_PER_TICK),
            "towns": self._town_table(),
            "crews_on_table": sum(1 for t in e.tracker.tokens if t.token_type == "crew"),
            "recommendations": [r.text for r in e.recs],
        }
        return out

    def _town_table(self) -> list[dict]:
        e = self.e
        f = e.latest_forecast
        routes = {r.town: r for r in e.routes}
        state = e.fire.state
        rows = []
        arrivals = None
        if f is not None and len(e.towns):
            arrivals = _town_arrivals(f.first_burn, self.masks, e.fire.tick - f.tick)
        for i, t in enumerate(e.towns):
            row = {"town": t.name, "population": t.population}
            on_fire = bool(((state == BURNING) | (state == BURNED))[self.masks[i]].any())
            row["fire_inside_town_now"] = on_fire
            if arrivals is not None:
                row.update(self._reach(arrivals[:, i]))
            r = routes.get(t.name)
            if r is not None:
                row["evacuation"] = {"status": r.status, "exit": r.safe_zone, "drive_minutes": r.eta_min}
            rows.append(row)
        return rows

    @staticmethod
    def _reach(a: np.ndarray) -> dict:
        """Counts of simulations reaching the town within 30 and 60 minutes, and the median time."""
        n = len(a)
        def within(minutes: float) -> int:
            return int((a * SIM_MINUTES_PER_TICK <= minutes).sum())

        reached = np.isfinite(a)
        median = float(np.median(a[reached])) * SIM_MINUTES_PER_TICK if reached.sum() * 2 >= n else None
        return {
            "fire_reaches_within_30_min": {"simulations": within(30), "of": n},
            "fire_reaches_within_60_min": {"simulations": within(60), "of": n},
            "median_minutes_until_fire": None if median is None else round(median),
        }

    # forecast_whatif ------------------------------------------------------

    async def forecast_whatif(self, wind_from: str, wind_speed_ms: float | None) -> dict:
        e = self.e
        if wind_from not in COMPASS:
            raise ValueError(f"wind_from must be one of {COMPASS}")
        if not e.fire.counts()[0]:
            return {"error": "nothing is burning, so there's nothing to forecast"}
        speed = e.fire.wind.speed_ms if wind_speed_ms is None else max(0.0, float(wind_speed_ms))
        wind = Wind(speed_ms=speed, from_deg=COMPASS.index(wind_from) * 45.0)
        ticks = int(60 / SIM_MINUTES_PER_TICK)
        job = e.recommender.run(whatif_job, e.fire.snapshot(), wind, e.towns, WHATIF_ROLLOUTS, ticks, e.fire.tick)
        arrivals, cells = await job
        now = self._town_table()
        towns = []
        for i, t in enumerate(e.towns):
            row = {"town": t.name, **self._reach(arrivals[:, i])}
            cur = next((r for r in now if r["town"] == t.name), {})
            if "fire_reaches_within_60_min" in cur:
                row["current_forecast_reaches_within_60_min"] = cur["fire_reaches_within_60_min"]
                row["current_median_minutes_until_fire"] = cur["median_minutes_until_fire"]
            towns.append(row)
        return {
            "hypothetical_wind": self._wind(wind),
            "current_wind": self._wind(e.fire.wind),
            "acres_burned_within_60_min": self._acres(cells),
            "towns": towns,
        }

    # evaluate_placement ---------------------------------------------------

    async def evaluate_placement(self, place: str | None, x: float | None, y: float | None) -> dict:
        e = self.e
        if place:
            x, y, label = self.resolve(place)
        elif x is not None and y is not None:
            label = f"({x:.0f}, {y:.0f})"
        else:
            raise ValueError("give a place name or both x and y")
        if not e.scenario.in_bounds(x, y):
            raise ValueError("that spot is off the map")
        if not e.fire.counts()[0]:
            return {"error": "nothing is burning, so a crew has nothing to hold"}
        job = e.recommender.run(placement_job, e.fire.snapshot(), x, y, e.towns, PLACEMENT_ROLLOUTS, e.fire.tick)
        rec = await job
        return {
            "placement": {"type": "crew", "at": label, "x": round(x, 1), "y": round(y, 1)},
            "acres_saved_within_60_min": self._acres(rec.cells_saved),
            "keeps_fire_out_of": [{"town": s.town, "simulations": s.hits, "of": s.n} for s in rec.saves],
            "lets_fire_into": [{"town": s.town, "simulations": s.hits, "of": s.n} for s in rec.worsens],
            "less_of_town_burns": [{"town": p.town, "percent": round(p.share * 100)} for p in rec.protects],
            "helps": rec.benefit > 0,
        }

    # get_routes -------------------------------------------------------------

    def get_routes(self) -> dict:
        e = self.e
        routes = [
            {
                "for": r.town,
                "status": r.status,
                "exit": r.safe_zone,
                "drive_minutes": r.eta_min,
                "worst_road_burn_chance_percent": round(r.risk * 100),
            }
            for r in e.routes
        ]
        changes = [ev.text for ev in e.recent_events if ev.kind != "road_cut"][-5:]
        return {"routes": routes, "recent_changes": changes}

    # helpers ----------------------------------------------------------------

    def _place_index(self) -> dict[str, tuple[float, float, str]]:
        e = self.e
        idx = {}
        for p in e.scenario.places:
            idx[p.name.lower()] = (p.x, p.y, p.name)
        for t in e.towns:
            idx[t.name.lower()] = (t.x, t.y, t.name)
        if e.roads is not None:
            for z in e.roads.safe_zones:
                idx[z.name.lower()] = (z.x, z.y, z.name)
        return idx

    def resolve(self, place: str) -> tuple[float, float, str]:
        """Map a spoken place name to map coords: exact, then partial match."""
        key = place.strip().lower()
        if key in self.places:
            return self.places[key]
        hits = [v for k, v in self.places.items() if key in k or k in key]
        if len(hits) == 1:
            return hits[0]
        names = sorted(v[2] for v in self.places.values())
        raise ValueError(f"unknown place {place!r}; known places: {', '.join(names)}")

    def _acres(self, cells: float) -> int:
        return int(round(cells * self.acres_per_cell))

    @staticmethod
    def _wind(w: Wind) -> dict:
        return {"from": compass(w.from_deg), "from_degrees": round(w.from_deg), "speed_ms": round(w.speed_ms, 1),
                "speed_mph": round(w.speed_ms * 2.237)}
