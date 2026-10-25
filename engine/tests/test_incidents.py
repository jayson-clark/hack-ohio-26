"""Several fires on one map (#179): incidents from ignitions, growth, merges, spots."""

import numpy as np

from scenario import load_scenario
from sim.fire import BURNING, FUEL, FireSim
from sim.game import Game
from sim.incidents import IncidentTracker

SCEN = load_scenario("paradise")


def blank():
    return np.full((SCEN.height, SCEN.width), FUEL, np.int8)


def burn(state, x0, x1, y0, y1):
    state[y0:y1, x0:x1] = BURNING


def test_an_ignition_opens_an_incident_named_after_the_nearest_place():
    inc = IncidentTracker(SCEN)
    pulga = next(p for p in SCEN.places if p.name == "Pulga")
    iid = inc.ignite(pulga.x, pulga.y, 0)
    s = blank()
    burn(s, int(pulga.x) - 1, int(pulga.x) + 2, int(pulga.y) - 1, int(pulga.y) + 2)
    inc.update(s, 1)
    [i] = inc.report(s)
    assert i.id == iid and i.name == "Pulga Fire" and i.active
    # It grows with its fire: neighbouring cells join it.
    burn(s, int(pulga.x) - 1, int(pulga.x) + 6, int(pulga.y) - 1, int(pulga.y) + 2)
    inc.update(s, 2)
    [i] = inc.report(s)
    assert i.acres > 9 * SCEN.cell_size_m**2 / 4046.86


def test_two_fires_are_two_incidents_until_they_merge_into_the_older():
    inc = IncidentTracker(SCEN)
    a = inc.ignite(50, 50, 0)
    b = inc.ignite(80, 50, 30)
    assert a != b
    s = blank()
    burn(s, 48, 53, 48, 53)
    burn(s, 78, 83, 48, 53)
    inc.update(s, 31)
    assert {i.id for i in inc.report(s)} == {a, b}
    assert len({i.name for i in inc.report(s)}) == 2
    burn(s, 48, 83, 49, 52)  # they burn into each other
    inc.update(s, 32)
    [i] = inc.report(s)
    assert i.id == a  # the older id survives


def test_spot_fires_join_inside_the_envelope_and_start_new_ones_outside():
    inc = IncidentTracker(SCEN)
    a = inc.ignite(50, 50, 0)
    s = blank()
    burn(s, 48, 53, 48, 53)
    inc.update(s, 1)
    env = np.zeros_like(s, bool)
    env[40:70, 40:70] = True
    s[60, 60] = BURNING  # a spot inside the envelope
    s[20, 150] = BURNING  # one far outside it
    inc.update(s, 2, env)
    assert inc.of(60, 60) == a
    far = inc.of(150, 20)
    assert far is not None and far != a
    assert len(inc.report(s)) == 2


def test_an_order_ahead_of_the_fire_is_about_the_nearest_incident():
    inc = IncidentTracker(SCEN)
    a = inc.ignite(50, 50, 0)
    s = blank()
    burn(s, 48, 53, 48, 53)
    inc.update(s, 1)
    assert inc.of(70, 60) == a
    assert IncidentTracker(SCEN).of(70, 60) is None  # nothing burning yet


def test_a_round_can_light_a_second_fire_on_schedule():
    g = Game(SCEN, [], config={"duration_min": 600, "limits": {}, "ignition": [60, 60], "wind": None,
                               "bus_people_per_min": 40, "mutual_aid": 2,
                               "ignitions": [{"x": 120, "y": 100, "at_min": 60}]})
    g.start(0)
    assert g.due_ignitions(59) == []
    assert g.due_ignitions(60) == [(120.0, 100.0)]
    assert g.due_ignitions(61) == []  # only once
    g.reset()
    g.start(0)
    assert g.due_ignitions(70) == [(120.0, 100.0)]  # again in the next round


def test_incidents_follow_a_real_fire():
    sim = FireSim(SCEN, seed=1)
    inc = IncidentTracker(SCEN)
    sim.ignite(217, 54)
    inc.ignite(217, 54, 0)
    for t in range(60):
        sim.step()
        inc.update(sim.state, sim.tick)
    lit = sim.state >= BURNING
    owned = inc.owner > 0
    assert (lit & ~owned).sum() == 0  # every burning or burned cell has an incident
    assert len(inc.report(sim.state)) >= 1


def _two_fires():
    """A west fire and an east fire, with a town between them."""
    inc = IncidentTracker(SCEN)
    west = inc.ignite(40.5, 100.5, 0)
    east = inc.ignite(200.5, 100.5, 0)
    s = blank()
    burn(s, 39, 42, 99, 102)
    burn(s, 199, 202, 99, 102)
    inc.update(s, 1)
    yy, xx = np.mgrid[: SCEN.height, : SCEN.width]
    town = np.hypot(xx + 0.5 - 120, yy + 0.5 - 100) <= 8
    return inc, west, east, s, town, xx


def test_a_town_is_threatened_by_the_fire_that_reaches_it_first():
    from commander.tools import threat_incident

    inc, west, east, s, town, xx = _two_fires()
    burnt = s >= BURNING
    # Five simulated futures: in three the east fire arrives first (the town's
    # east edge burns first), in two the west fire does.
    n = 5
    first = np.full((n, SCEN.height, SCEN.width), np.inf, np.float32)
    east_first = np.where(town, 100.0 - (xx - 112), np.inf)  # east edge soonest
    west_first = np.where(town, 100.0 + (xx - 128), np.inf)  # west edge soonest
    for k, (grid, delay) in enumerate([(east_first, 0), (west_first, 30), (east_first, 10), (west_first, 50), (east_first, 20)]):
        first[k] = grid + delay
    arrivals = first.reshape(n, -1)[:, town.ravel()].min(axis=1)
    assert threat_incident(inc, first, arrivals, town, burnt) == east
    # Flip which fire comes first in most runs, and the median run follows.
    first2 = np.stack([west_first, west_first + 5, east_first + 40, west_first + 10, east_first + 60])
    arrivals2 = first2.reshape(n, -1)[:, town.ravel()].min(axis=1)
    assert threat_incident(inc, first2, arrivals2, town, burnt) == west


def test_a_town_already_burning_belongs_to_the_fire_inside_it():
    from commander.tools import threat_incident

    inc, west, east, s, town, _ = _two_fires()
    burn(s, 120, 125, 98, 103)  # the east fire spreads into town, connected to it
    burn(s, 125, 202, 100, 101)
    inc.update(s, 2)
    assert threat_incident(inc, None, None, town, s >= BURNING) == east
    # No forecast and no fire inside: no incident to name.
    assert threat_incident(inc, None, None, town, np.zeros_like(town)) is None
