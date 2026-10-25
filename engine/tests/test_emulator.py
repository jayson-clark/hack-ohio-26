"""Fire emulator features (#113). The network itself needs MLX and weights,
so only the NumPy side is tested here."""

import numpy as np

from emulator import features as F
from scenario import load_scenario
from sim.fire import BURNED, BURNING, FireLayers, FireSim, Wind


def burning_sim():
    sim = FireSim(load_scenario("paradise"), seed=0)
    sim.set_wind(Wind(9, 300))
    sim.ignite(150, 100, radius=3)
    for _ in range(15):
        sim.step()
    return sim


def _spread_only(spread: np.ndarray, fy: bool, fx: bool) -> np.ndarray:
    """Flip a bare (8, H, W) spread stack with the same channel swap."""
    pad = np.zeros((3, *spread.shape[1:]), np.float32)
    return F.flip(np.concatenate([pad, spread, np.zeros((4, *spread.shape[1:]), np.float32)]), fy, fx)[3:11]


def test_flipping_inputs_matches_flipping_the_world():
    """Flipped training inputs equal the inputs of the same fire on a flipped
    map, with the wind turned to match: the directional channels swap the way
    the fire model's own neighbours do."""
    snap = burning_sim().snapshot()
    sup = np.zeros((4, *snap.state.shape), np.float32)
    x = F.inputs(snap.state, snap.burn_left, snap.layers.spread, snap.wind, sup)
    w = snap.wind
    for fy, fx, wind in ((True, False, Wind(w.speed_ms, (180 - w.from_deg) % 360)),
                         (False, True, Wind(w.speed_ms, (360 - w.from_deg) % 360)),
                         (True, True, Wind(w.speed_ms, (w.from_deg + 180) % 360))):
        layers = FireLayers(_spread_only(snap.layers.spread, fy, fx), F.flip_grid(snap.layers.burnable, fy, fx))
        world = F.inputs(F.flip_grid(snap.state, fy, fx), F.flip_grid(snap.burn_left, fy, fx), layers.spread, wind, sup)
        assert np.allclose(F.flip(x, fy, fx), world, atol=1e-5), (fy, fx)
        assert np.allclose(F.flip(F.flip(x, fy, fx), fy, fx), x)  # an involution


def test_certain_cells():
    state = burning_sim().state
    done, open_ = F.masks(state)
    assert done[:, state >= BURNING].all() and not (done & open_).any()
    # Fire moves at most one cell (king move) per tick.
    ys, xs = np.nonzero(state == BURNING)
    yy, xx = np.mgrid[: state.shape[0], : state.shape[1]]
    cheb = np.min(np.maximum(abs(yy[..., None] - ys), abs(xx[..., None] - xs)), axis=-1)
    assert not open_[1][cheb > 60].any() and open_[1][(cheb <= 60) & (state < BURNING)].all()
    p = F.finish(np.full((2, *state.shape), 0.5, np.float32), state)
    assert (p[:, state == BURNED] == 1).all() and (p[1][cheb > 60] == 0).all()


class _StubEmulator:
    """Stands in for the trained net: a constant forecast, so the engine's
    preview plumbing can be tested without MLX or weights."""

    def forecast(self, snapshot):
        return np.full((2, *snapshot.state.shape), 0.5, np.float32)


def test_engine_previews_until_monte_carlo_catches_up():
    import asyncio

    from server import PREVIEW_MIN_TICKS, Engine

    async def go():
        e = Engine()
        try:
            e.emulator = _StubEmulator()
            e.fire.ignite(409.3, 118.5)
            e._ignitions += 1
            e.tick = PREVIEW_MIN_TICKS
            e.maybe_preview()
            await e._preview_job
            await asyncio.sleep(0)  # let the done callback run
            assert e._preview is not None and e._preview[0] == e.fire.tick
            frame = e.forecast_frame()
            assert frame[-1] == round(0.5 * 255)  # the preview, not an empty grid
            # Nothing changed: no new preview job.
            e.tick += PREVIEW_MIN_TICKS
            job = e._preview_job
            e.maybe_preview()
            assert e._preview_job is job
            # A Monte Carlo forecast from the same tick or later replaces it.
            from forecast.runner import run_forecast

            done = asyncio.get_running_loop().create_future()
            done.set_result(run_forecast(e.snapshot(), n=4, seed=0))
            e.forecast_done(done, e._fire_epoch)
            assert e._preview is None and e.latest_forecast is not None
            e.reset_map()
            assert e._preview is None
        finally:
            e.forecaster.shutdown()
            e.long_forecaster.shutdown()
            e.recommender.shutdown()

    asyncio.run(go())


def test_real_emulator_previews_on_every_scenario():
    """The trained emulator through the live engine (needs the ml extra and
    weights): previews work on every scenario in assets/, after switching
    to it, since MLX runs on the engine's own emulator thread."""
    import asyncio

    import pytest

    pytest.importorskip("mlx.core")
    from emulator.model import WEIGHTS
    from scenario import ASSETS
    from server import PREVIEW_MIN_TICKS, Engine

    scenarios = sorted(d.name for d in ASSETS.iterdir() if (d / "terrain.json").exists())

    if not WEIGHTS.exists():
        pytest.skip("no trained weights")

    async def go():
        e = Engine()
        try:
            assert e.emulator is not None
            for name in scenarios:
                e.switch_scenario(name)
                e.fire.ignite(*(e.game.ignition or (e.scenario.width / 2, e.scenario.height / 2)))
                e._ignitions += 1
                for _ in range(15):
                    e.step_fire()
                e.tick += PREVIEW_MIN_TICKS
                e.maybe_preview()
                await e._preview_job
                await asyncio.sleep(0)
                assert e._preview is not None, name
                tick, grids = e._preview
                assert grids.shape == (2, e.scenario.height, e.scenario.width)
                assert (grids[1] >= grids[0] - 1e-6).all()  # T+60 covers at least T+30
                assert (grids[:, e.fire.state >= 2] == 1).all()  # burning and burned stay certain
        finally:
            e.forecaster.shutdown()
            e.recommender.shutdown()

    asyncio.run(go())
