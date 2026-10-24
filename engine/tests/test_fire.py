import math
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import sim.fire as fire_mod
from forecast import burn_probability, rollout
from forecast.runner import HORIZONS_MIN, run_forecast
from protocol import Token, TokenSource, TokenType
from scenario import Scenario, load_scenario
from sim.effects import WATER_COOLDOWN_TICKS, TokenEffects
from sim.fire import BURNED, BURNING, FUEL, UNBURNABLE, FireSim, Wind, build_layers

W, H = 96, 64


def flat(heightmap: np.ndarray | None = None) -> Scenario:
    """A small synthetic scenario, so tests don't depend on Paradise's terrain."""
    hm = np.zeros((H, W), np.float32) if heightmap is None else heightmap
    return Scenario(
        name="test", dir=Path("/nonexistent"), width=W, height=H, cell_size_m=94.0,
        heightmap=hm, places=(), terrain={},
    )


def burned_mask(sim: FireSim) -> np.ndarray:
    return sim.state >= BURNING


def run(sim: FireSim, ticks: int) -> FireSim:
    for _ in range(ticks):
        sim.step()
    return sim


def test_spread_follows_wind():
    east = west = 0
    for seed in range(4):
        sim = FireSim(flat(), seed=seed)
        sim.set_wind(Wind(speed_ms=10, from_deg=270))  # west wind, pushes fire east
        sim.ignite(W / 2, H / 2)
        b = burned_mask(run(sim, 40))
        east += b[:, W // 2 + 3 :].sum()
        west += b[:, : W // 2 - 3].sum()
    assert east > 5 * max(west, 1)


def test_wind_from_north_pushes_south():
    sim = FireSim(flat(), seed=0)
    sim.set_wind(Wind(speed_ms=10, from_deg=0))
    sim.ignite(W / 2, H / 2)
    b = burned_mask(run(sim, 30))
    assert b[H // 2 + 3 :].sum() > 5 * max(b[: H // 2 - 3].sum(), 1)


def test_uphill_faster_than_downhill():
    # Elevation rises to the east, 20 m per 94 m cell (about 12 degrees).
    ramp = np.tile(np.arange(W, dtype=np.float32) * 20, (H, 1))
    up = down = 0
    for seed in range(4):
        sim = FireSim(flat(ramp), seed=seed)
        sim.set_wind(Wind(0, 0))
        sim.ignite(W / 2, H / 2)
        b = burned_mask(run(sim, 40))
        up += b[:, W // 2 + 3 :].sum()
        down += b[:, : W // 2 - 3].sum()
    assert up > 2 * down


def test_suppression_stops_spread(monkeypatch):
    monkeypatch.setattr(fire_mod, "SPOT_RATE", 0.0)  # embers can jump it; see test_embers_jump_breaks_in_strong_wind
    sim = FireSim(flat(), seed=0)
    sim.set_wind(Wind(10, 270))
    s = np.zeros((H, W), np.float32)
    s[:, W // 2 + 4 : W // 2 + 7] = 1.0  # a wall of suppression just downwind
    sim.set_suppression(s)
    sim.ignite(W / 2, H / 2)
    b = burned_mask(run(sim, 80))
    assert b[:, W // 2 + 4 :].sum() == 0
    assert b.sum() > 10  # it did burn, just not through


def test_full_suppression_puts_out_burning_cells():
    sim = FireSim(flat(), seed=0)
    sim.ignite(W / 2, H / 2, radius=3)
    sim.set_suppression(np.ones((H, W), np.float32))
    sim.step()
    assert (sim.state == BURNING).sum() == 0


def test_unburnable_never_burns():
    sc = flat()
    fuel = np.ones((H, W), np.float32)
    fuel[:, 60:62] = 0  # a river
    sim = FireSim(sc, seed=0)
    sim.layers = build_layers(sc, fuel)
    sim.reset()
    assert (sim.state[:, 60:62] == UNBURNABLE).all()
    sim.set_wind(Wind(15, 270))
    sim.ignite(W / 2, H / 2)
    run(sim, 80)
    assert (sim.state[:, 60:62] == UNBURNABLE).all()


def test_burning_cells_char_and_reset():
    sim = FireSim(flat(), seed=0)
    sim.set_wind(Wind(0, 0))
    sim.ignite(W / 2, H / 2)
    run(sim, 30)
    assert (sim.state == BURNED).any()
    sim.reset()
    assert sim.tick == 0 and (sim.state == FUEL).all()


def test_fire_sim_deterministic_with_seed():
    def go(seed):
        sim = FireSim(flat(), seed=seed)
        sim.ignite(W / 2, H / 2)
        return run(sim, 30).state.copy()

    assert np.array_equal(go(7), go(7))
    assert not np.array_equal(go(7), go(8))


def test_paradise_fire_spreads_and_runs_downwind():
    sim = FireSim(load_scenario("paradise"), seed=0)
    sim.set_wind(Wind(10, 270))
    sim.ignite(128, 96)
    b = burned_mask(run(sim, 100))
    assert b.sum() > 300
    assert b[:, 140:].sum() > 5 * b[:, :116].sum()


def snapshot_with_fire(seed=0, ticks=10):
    sim = FireSim(flat(), seed=seed)
    sim.set_wind(Wind(8, 270))
    sim.ignite(W / 2, H / 2)
    return run(sim, ticks).snapshot()


def test_rollout_shape_dtype_and_inf_semantics():
    snap = snapshot_with_fire()
    first = rollout(snap, 8, 20, seed=0)
    assert first.shape == (8, H, W) and first.dtype == np.float32
    already = (snap.state == BURNING) | (snap.state == BURNED)
    assert (first[:, already] == 0).all()
    assert np.isinf(first[:, 0, 0]).all()  # far upwind corner can't burn in 20 ticks
    finite = first[np.isfinite(first)]
    assert finite.min() == 0 and finite.max() <= 20
    assert (first[:, ~already] != 0).all()  # new burns are at tick >= 1


def test_rollout_deterministic_with_seed():
    snap = snapshot_with_fire()
    assert np.array_equal(rollout(snap, 4, 20, seed=3), rollout(snap, 4, 20, seed=3))


def test_rollout_wind_override_and_extra_suppression():
    snap = snapshot_with_fire()
    base = burn_probability(rollout(snap, 16, 30, seed=0), 30)
    # Same fire, but the wind turned to come from the east.
    turned = burn_probability(rollout(snap, 16, 30, wind=Wind(8, 90), seed=0), 30)
    assert turned[:, : W // 2 - 5].sum() > base[:, : W // 2 - 5].sum()
    # A suppression wall downwind keeps the far side unburned.
    wall = np.zeros((H, W), np.float32)
    wall[:, W // 2 + 12 : W // 2 + 15] = 1.0
    walled = burn_probability(rollout(snap, 16, 30, extra_suppression=wall, seed=0), 30)
    assert walled[:, W // 2 + 12 :].sum() == 0
    assert base[:, W // 2 + 12 :].sum() > 0


def test_burn_probability_monotone_in_horizon():
    first = rollout(snapshot_with_fire(), 16, 40, seed=0)
    p = [burn_probability(first, h) for h in (5, 10, 20, 40)]
    assert all(pi.dtype == np.float32 and pi.shape == (H, W) for pi in p)
    for a, b in zip(p, p[1:]):
        assert (b >= a).all()
    assert p[-1].max() == 1.0 and p[0].min() == 0.0


def test_run_forecast_stacks_horizons():
    f = run_forecast(snapshot_with_fire(), n=4, seed=0)
    assert f.probability.shape == (len(HORIZONS_MIN), H, W)
    assert (f.probability[1] >= f.probability[0]).all()


def token(kind, x, y, angle=0.0, id="t1"):
    return Token(id=id, token_type=kind, x=x, y=y, angle=angle, source=TokenSource.VIRTUAL)


def test_crew_ramps_up():
    fx = TokenEffects(W, H)
    t = [token(TokenType.CREW, 40, 30)]
    first = fx.update(t, 0)[30, 40]
    later = fx.update(t, 100)[30, 40]
    assert first == 0 and 0.5 < later < 1
    assert fx.update(t, 100)[0, 0] == 0


def test_water_knocks_down_then_cools_down():
    fx = TokenEffects(W, H)
    assert fx.update([token(TokenType.WATER, 40, 30)], 0)[30, 40] == 1.0
    assert fx.update([token(TokenType.WATER, 40, 30)], 1)[30, 40] < 1.0
    # Moved before the cooldown: no new drop, and the old patch dries out.
    assert fx.update([token(TokenType.WATER, 70, 30)], 50)[30, 70] == 0
    assert fx.update([token(TokenType.WATER, 70, 30)], WATER_COOLDOWN_TICKS)[30, 70] == 1.0


def test_firebreak_follows_angle():
    fx = TokenEffects(W, H)
    s = fx.update([token(TokenType.FIREBREAK, 40, 30, angle=np.pi / 2)], 0)  # runs north-south
    assert s[24:36, 40].min() == 1.0
    assert s[30, 30] == 0 and s[30, 50] == 0


def test_bus_has_no_effect():
    assert TokenEffects(W, H).update([token(TokenType.BUS, 40, 30)], 0).max() == 0


@pytest.mark.parametrize("from_deg", [0, 90, 180, 270])
def test_firebreak_holds_against_wind(from_deg, monkeypatch):
    # Ring of firebreak suppression round the ignition point holds against
    # spread from neighbours in any wind (embers are tested separately).
    monkeypatch.setattr(fire_mod, "SPOT_RATE", 0.0)
    sim = FireSim(flat(), seed=0)
    sim.set_wind(Wind(12, from_deg))
    ys, xs = np.mgrid[:H, :W]
    d = np.hypot(xs + 0.5 - W / 2, ys + 0.5 - H / 2)
    sim.set_suppression(((d > 8) & (d < 10)).astype(np.float32))
    sim.ignite(W / 2, H / 2)
    run(sim, 60)
    assert not burned_mask(sim)[d >= 10].any()


def _crossings(wind_from: float, speed: float, seeds=range(6)) -> float:
    """Share of fires that get past a crew-strength (0.9) band at x = 44-57,
    lit at x = 30 so the band sees head fire (wind from the west) or backing
    fire (wind from the east)."""
    crossed = 0
    for seed in seeds:
        sim = FireSim(flat(), seed=seed)
        sup = np.zeros((H, W), np.float32)
        sup[:, 44:58] = 0.9
        sim.set_suppression(sup)
        sim.set_wind(Wind(speed, wind_from))
        sim.ignite(30, 32, radius=3)
        run(sim, 150)
        crossed += burned_mask(sim)[:, 60:].any()
    return crossed / len(seeds)


def test_crews_hold_flanks_and_backing_fire_but_not_a_wind_driven_head(monkeypatch):
    monkeypatch.setattr(fire_mod, "SPOT_RATE", 0.0)  # embers jump lines; this is about the line itself
    assert _crossings(270, 13) >= 0.8  # the head runs through a crew's line
    assert _crossings(90, 13) == 0  # backing fire into the same line is held
    assert _crossings(270, 0) == 0  # and so is calm fire
    monkeypatch.setattr(fire_mod, "HOLD_P", math.inf)
    assert _crossings(270, 13) == 0  # without HOLD_P the line held the head too


def _jumps(speed: float, seeds=range(6)) -> float:
    """Share of fires that light anything beyond a 10-cell unburnable gap
    (x = 50-59), lit at x = 30 with the wind from the west."""
    jumped = 0
    for seed in seeds:
        fuel = np.ones((H, W), np.float32)
        fuel[:, 50:60] = 0.0
        sim = FireSim(flat(), seed=seed)
        sim.layers = build_layers(flat(), fuel=fuel)
        sim.reset()
        sim.set_wind(Wind(speed, 270))
        sim.ignite(30, 32, radius=3)
        run(sim, 80)
        jumped += burned_mask(sim)[:, 60:].any()
    return jumped / len(seeds)


def test_embers_jump_breaks_in_strong_wind():
    """Spotting (#15): a 10-cell (~1 km) gap stops a fire on a calm or
    moderate day, but strong wind carries embers across it."""
    assert _jumps(8) == 0  # below SPOT_MIN_WIND: no embers
    assert _jumps(18) >= 0.5


def test_spotting_keeps_paired_rollouts_paired():
    """Ember draws are shared across variants, so a variant that changes
    nothing still matches the baseline exactly in strong wind."""
    from forecast.rollout import rollout_paired

    sim = FireSim(flat(), seed=0)
    sim.set_wind(Wind(18, 270))
    sim.ignite(30, 32, radius=3)
    run(sim, 10)
    first = rollout_paired(sim.snapshot(), 6, 40, [np.zeros((H, W), np.float32)], seed=3)
    assert np.array_equal(first[0], first[1])
