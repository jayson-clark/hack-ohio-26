"""The game layer (PLAN.md, Game layer): resource limits, scoring and rounds.

Outside a round (the sandbox phase) nothing is limited or timed, so virtual
table mode stays a free-play tool for development. A round starts from a
reset map, ignites at the scenario's ignition point, holds each token type to
its limit, and ends when time runs out, the fire is out, or the operator stops
it. When a round ends the fire freezes, so the summary matches the map.

Scoring is computed in every phase, since it's cheap and the console shows it
either way:

- acres burned: burning and burned cells.
- structures lost: each town's structures times the share of its burnable
  cells that have caught. Towns are disks from towns.json.
- people evacuated: an in-limit bus parked inside a town carries residents
  out at BUS_PEOPLE_PER_MIN while that town's route isn't cut. That's a
  stand-in for buses driving their routes, which #6 may add later.

Per-scenario settings come from an optional assets/scenarios/<name>/game.json
(keys as in DEFAULTS), so a scenario can tune its round without code changes.
"""

import json
import math
from dataclasses import dataclass

import numpy as np

from protocol import EndReason, Token, TokenType
from protocol import RoundPhase as Phase
from scenario import Scenario
from sim.fire import BURNED, BURNING, SIM_MINUTES_PER_TICK, UNBURNABLE

SQ_M_PER_ACRE = 4046.86

DEFAULTS = {
    # Sim minutes. On Paradise at the default wind an unfought fire reaches
    # Paradise around minute 310 and burns out by about 600-850, so the round
    # runs past the big towns' arrival but the clock still matters.
    "duration_min": 600,
    # PLAN.md: "3 crews, 2 water drops (with cooldown), and 1 firebreak".
    # Buses aren't in PLAN's list; two keeps evacuating every town a tradeoff.
    "limits": {"crew": 3, "water": 2, "firebreak": 1, "bus": 2},
    # [x, y] in map coords, or null to leave the first ignition to the operator.
    "ignition": None,
    # Two buses can't empty every town before the fire arrives (Paradise alone
    # is 26,800 people), so where they go is the decision.
    "bus_people_per_min": 40,
}


@dataclass(frozen=True)
class GameTown:
    name: str
    x: float
    y: float
    radius: float
    population: int
    structures: int


def load_config(scenario: Scenario) -> dict:
    cfg = json.loads(json.dumps(DEFAULTS))  # deep copy
    path = scenario.dir / "game.json"
    if path.exists():
        over = json.loads(path.read_text())
        cfg["limits"].update(over.pop("limits", {}))
        cfg.update(over)
    return cfg


class Game:
    def __init__(self, scenario: Scenario, towns: list[GameTown], config: dict | None = None) -> None:
        self.config = config or load_config(scenario)
        self.limits: dict[TokenType, int] = {TokenType(k): v for k, v in self.config["limits"].items()}
        self.duration_ticks = self.config["duration_min"] / SIM_MINUTES_PER_TICK
        self.acres_per_cell = scenario.cell_size_m**2 / SQ_M_PER_ACRE
        self.towns = towns
        ys, xs = np.mgrid[: scenario.height, : scenario.width].astype(np.float32) + 0.5
        self._town_masks = [np.hypot(xs - t.x, ys - t.y) <= t.radius for t in towns]
        # Burnable cells per town. Unburnable cells never change state, so
        # this can be taken from any frame; it's filled on the first update.
        self._town_burnable: list[np.ndarray] = []
        self.reset()

    def reset(self) -> None:
        """Back to the sandbox, with nothing scored."""
        self.phase = Phase.SANDBOX
        self.end_reason: EndReason | None = None
        self.start_tick = 0
        self.end_tick = 0
        self.evacuated = [0.0] * len(self.towns)
        self.structures_lost = [0] * len(self.towns)
        self.acres_burned = 0.0
        self.inactive: list[str] = []
        self.used: dict[TokenType, int] = {}
        # Placement order within the current phase: the first `limit` tokens of
        # a type are the ones that count, so a token added over the limit
        # takes effect once an earlier one is lifted.
        self._order: dict[str, int] = {}
        self._next = 0
        self._ignited = False

    def start(self, tick: int) -> None:
        """Start a round on a freshly reset map at sim tick `tick`."""
        self.reset()
        self.phase = Phase.RUNNING
        self.start_tick = tick

    def stop(self, tick: int) -> None:
        if self.phase == Phase.RUNNING:
            self._end(tick, EndReason.STOPPED)

    @property
    def ignition(self) -> tuple[float, float] | None:
        ig = self.config.get("ignition")
        return None if ig is None else (float(ig[0]), float(ig[1]))

    @property
    def frozen(self) -> bool:
        """True once a round has ended: the fire shouldn't advance."""
        return self.phase == Phase.ENDED

    def elapsed_min(self, tick: int) -> float:
        if self.phase == Phase.SANDBOX:
            return 0.0
        end = self.end_tick if self.phase == Phase.ENDED else tick
        return (end - self.start_tick) * SIM_MINUTES_PER_TICK

    def active(self, tokens: list[Token]) -> list[Token]:
        """The tokens that take effect: all of them in the sandbox, and the
        first `limit` of each type (in placement order) during a round."""
        for t in tokens:
            if t.id not in self._order:
                self._order[t.id] = self._next
                self._next += 1
        live = {t.id for t in tokens}
        self._order = {k: v for k, v in self._order.items() if k in live}

        used: dict[TokenType, int] = {}
        keep, inactive = [], []
        for t in sorted(tokens, key=lambda t: self._order[t.id]):
            n = used.get(t.token_type, 0)
            limit = self.limits.get(t.token_type)
            if self.phase == Phase.SANDBOX or limit is None or n < limit:
                used[t.token_type] = n + 1
                keep.append(t)
            else:
                inactive.append(t.id)
        self.used = used
        self.inactive = inactive
        return keep

    def update(self, tick: int, state: np.ndarray, buses: list[Token], cut_towns: set[str]) -> None:
        """Score the map after a sim step, move people out, and end the round
        if it's over. `buses` are the active bus tokens; `cut_towns` are towns
        whose route currently has no safe way out."""
        if self.frozen:
            return
        if not self._town_burnable:
            fuel = state != UNBURNABLE
            self._town_burnable = [mask & fuel for mask in self._town_masks]
        caught = (state == BURNING) | (state == BURNED)
        self.acres_burned = float(caught.sum()) * self.acres_per_cell
        for i, (t, mask, burnable) in enumerate(zip(self.towns, self._town_masks, self._town_burnable)):
            n = int(burnable.sum())
            share = float((caught & mask).sum()) / n if n else 0.0
            self.structures_lost[i] = round(t.structures * min(1.0, share))

        rate = self.config["bus_people_per_min"] * SIM_MINUTES_PER_TICK
        for b in buses:
            i = self._town_at(b.x, b.y)
            if i is None or self.towns[i].name in cut_towns:
                continue
            self.evacuated[i] = min(float(self.towns[i].population), self.evacuated[i] + rate)

        if self.phase != Phase.RUNNING:
            return
        burning = bool((state == BURNING).any())
        self._ignited |= burning
        if self._ignited and not burning:
            self._end(tick, EndReason.CONTAINED)
        elif tick - self.start_tick >= self.duration_ticks:
            self._end(tick, EndReason.TIME)

    def _end(self, tick: int, reason: EndReason) -> None:
        self.phase = Phase.ENDED
        self.end_reason = reason
        self.end_tick = tick

    def _town_at(self, x: float, y: float) -> int | None:
        """The nearest town whose disk contains (x, y)."""
        best, best_d = None, math.inf
        for i, t in enumerate(self.towns):
            d = math.hypot(x - t.x, y - t.y)
            if d <= t.radius and d < best_d:
                best, best_d = i, d
        return best
