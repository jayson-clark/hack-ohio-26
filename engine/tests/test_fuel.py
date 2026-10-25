"""Paradise's fuel layer (assets/scenarios/paradise/fuel.png, from tools/osm_to_fuel.py)."""

import numpy as np

from scenario import load_scenario
from sim.fire import FUEL, UNBURNABLE, FireSim, load_fuel


def test_fuel_layer_is_loaded_at_grid_size_and_varies():
    s = load_scenario("paradise")
    assert (s.dir / "fuel.png").exists()
    fuel = load_fuel(s)
    assert fuel.shape == (s.height, s.width)
    # Forest-weighted, so the fire's tuning still holds; not uniform any more.
    assert 0.8 < fuel.mean() < 1.1
    assert fuel.std() > 0.05
    assert fuel.max() <= 1.5


def test_concow_lake_does_not_burn():
    s = load_scenario("paradise")
    sim = FireSim(s, seed=0)
    # Concow Lake, just south-west of the Concow place marker.
    lake = sim.state[159:174, 327:342]  # the print sits at (192, 64) in the extended map (#197)
    assert (lake == UNBURNABLE).any()
    assert (sim.state == FUEL).mean() > 0.95  # but nearly the whole map is fuel
