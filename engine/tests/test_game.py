"""The game layer: limits, scoring, round state, and the engine's wiring of it."""

import asyncio
import json

import numpy as np

from protocol import RoundPhase, Score, StartRound, EndRound, Reset, Token, TokenSource, TokenType, VirtualTokenAdd
from scenario import load_scenario
from server import Engine
from sim.fire import BURNED, BURNING, FUEL, UNBURNABLE
from sim.game import EndReason, Game, GameTown, load_config

TOWN = GameTown("Testville", x=20.0, y=20.0, radius=5.0, population=1000, structures=100)


def game(**config) -> Game:
    s = load_scenario("paradise")
    cfg = load_config(s) | {"ignition": None} | config
    return Game(s, [TOWN], cfg)


def grid(fill: int = FUEL) -> np.ndarray:
    s = load_scenario("paradise")
    return np.full((s.height, s.width), fill, np.uint8)


def token(i: int, kind: TokenType, x: float = 100.0, y: float = 100.0) -> Token:
    return Token(id=f"t{i}", token_type=kind, x=x, y=y, source=TokenSource.VIRTUAL)


def test_sandbox_has_no_limits():
    g = game()
    crews = [token(i, TokenType.CREW) for i in range(6)]
    assert g.active(crews) == crews and g.inactive == []


def test_round_keeps_the_first_tokens_up_to_each_limit():
    g = game(limits={"crew": 2, "water": 1, "firebreak": 1, "bus": 1})
    g.start(0)
    crews = [token(i, TokenType.CREW) for i in range(3)]
    assert [t.id for t in g.active(crews)] == ["t0", "t1"]
    assert g.inactive == ["t2"] and g.used[TokenType.CREW] == 2
    # Lifting an early crew lets the one waiting over the limit take effect.
    assert [t.id for t in g.active(crews[1:])] == ["t1", "t2"]
    assert g.inactive == []


def test_structures_lost_follow_the_share_of_the_town_that_burned():
    g = game()
    state = grid()
    ys, xs = np.mgrid[: state.shape[0], : state.shape[1]] + 0.5
    in_town = np.hypot(xs - TOWN.x, ys - TOWN.y) <= TOWN.radius
    left_half = in_town & (xs < TOWN.x)
    state[left_half] = BURNED
    g.update(1, state, [], set())
    share = left_half.sum() / in_town.sum()
    assert g.structures_lost == [round(TOWN.structures * share)]
    assert g.acres_burned > 0


def test_unburnable_cells_dont_count_against_a_town():
    g = game()
    state = grid()
    ys, xs = np.mgrid[: state.shape[0], : state.shape[1]] + 0.5
    in_town = np.hypot(xs - TOWN.x, ys - TOWN.y) <= TOWN.radius
    # Half the town is water; burning the other half is losing all of it.
    state[in_town & (xs < TOWN.x)] = UNBURNABLE
    state[in_town & (xs >= TOWN.x)] = BURNED
    g.update(1, state, [], set())
    assert g.structures_lost == [TOWN.structures]


def test_a_bus_in_town_evacuates_unless_the_route_is_cut():
    g = game(bus_people_per_min=10)
    bus = token(0, TokenType.BUS, x=TOWN.x + 1, y=TOWN.y)
    for tick in range(5):
        g.update(tick, grid(), [bus], set())
    assert g.evacuated == [50.0]
    g.update(6, grid(), [bus], {TOWN.name})
    assert g.evacuated == [50.0]
    far = token(1, TokenType.BUS, x=200, y=150)
    g.update(7, grid(), [far], set())
    assert g.evacuated == [50.0]


def test_evacuation_stops_at_the_population():
    g = game(bus_people_per_min=600)
    bus = token(0, TokenType.BUS, x=TOWN.x, y=TOWN.y)
    for tick in range(3):
        g.update(tick, grid(), [bus], set())
    assert g.evacuated == [float(TOWN.population)]


def test_round_ends_on_time_and_freezes():
    g = game(duration_min=5)
    g.start(0)
    burning = grid()
    burning[0, 0] = BURNING
    g.update(4, burning, [], set())
    assert g.phase == RoundPhase.RUNNING
    g.update(5, burning, [], set())
    assert (g.phase, g.end_reason, g.frozen) == (RoundPhase.ENDED, EndReason.TIME, True)
    assert g.elapsed_min(99) == 5


def test_round_ends_when_the_fire_is_out():
    g = game()
    g.start(0)
    g.update(1, grid(), [], set())
    assert g.phase == RoundPhase.RUNNING  # nothing has burned yet: not "contained"
    burning = grid()
    burning[0, 0] = BURNING
    g.update(2, burning, [], set())
    out = grid()
    out[0, 0] = BURNED
    g.update(3, out, [], set())
    assert g.end_reason == EndReason.CONTAINED


def test_stop_only_ends_a_running_round():
    g = game()
    g.stop(3)
    assert g.phase == RoundPhase.SANDBOX
    g.start(0)
    g.stop(3)
    assert g.end_reason == EndReason.STOPPED


def test_paradise_game_config_ignites_inside_the_map():
    s = load_scenario("paradise")
    cfg = load_config(s)
    x, y = cfg["ignition"]
    assert s.in_bounds(x, y)


def test_engine_round_flow():
    async def run():
        engine = Engine()
        try:
            score = Score.model_validate_json(engine.score_msg())
            assert score.phase == RoundPhase.SANDBOX
            assert score.people_total > 0 and score.structures_total > 0

            engine.dispatch(StartRound())
            assert engine.game.phase == RoundPhase.RUNNING
            assert engine.fire.counts()[0] > 0  # ignited at the scenario's ignition point

            for _ in range(engine.game.limits[TokenType.CREW] + 1):
                engine.dispatch(VirtualTokenAdd(token_type=TokenType.CREW, x=120, y=100))
            engine.step_fire()
            score = Score.model_validate_json(engine.score_msg())
            crew = next(r for r in score.resources if r.token_type == TokenType.CREW)
            assert crew.used == crew.limit and len(score.inactive_tokens) == 1

            engine.dispatch(EndRound())
            tick = engine.fire.tick
            engine.step_fire()
            assert engine.fire.tick == tick  # frozen
            assert json.loads(engine.state_msg())["running"] is False

            engine.dispatch(Reset())
            assert engine.game.phase == RoundPhase.SANDBOX
        finally:
            engine.forecaster.shutdown()
            engine.long_forecaster.shutdown()
            engine.recommender.shutdown()

    asyncio.run(run())
