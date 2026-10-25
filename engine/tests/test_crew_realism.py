"""Crew realism (#178): shifts and relief, tanker round trips, mutual aid."""

import numpy as np
import pytest

from protocol import Token, TokenSource, TokenType
from routing.roads import build_network
from routing.units import Station, UnitRouter
from sim.dispatch import MUTUAL_AID_TICKS, RELOAD_MIN, REST_TICKS, Dispatcher
from sim.effects import (
    CREW_MAX,
    CREW_RAMP_TICKS,
    FADE_TICKS,
    FATIGUE_FLOOR,
    SHIFT_TICKS,
    TokenEffects,
    crew_layer,
)

W, H = 40, 20
CELL_M = 94.0


def tok(i, tt, x, y):
    return Token(id=i, token_type=tt, x=x, y=y, angle=0.0, source=TokenSource.VIRTUAL)


@pytest.fixture
def router():
    nodes = [[2, 10], [20, 10], [38, 10]]
    edges = [[0, 1, 1700, "primary"], [1, 2, 1700, "primary"]]
    return UnitRouter(build_network(nodes, edges, W, H), CELL_M)


def run(d: Dispatcher, tokens, ticks, start=0):
    for t in range(start, start + ticks):
        acting = d.update(tokens, t, 5.0, None)
    return acting


def test_a_crew_fades_after_its_shift():
    layer = crew_layer(W, H, 20, 10)
    assert layer.level(CREW_RAMP_TICKS + 1) == pytest.approx(CREW_MAX)
    assert layer.level(SHIFT_TICKS) == pytest.approx(CREW_MAX)
    assert layer.level(SHIFT_TICKS + FADE_TICKS // 2) < CREW_MAX
    assert layer.level(SHIFT_TICKS + FADE_TICKS * 3) == pytest.approx(CREW_MAX * FATIGUE_FLOOR)
    fx = TokenEffects(W, H)
    c = tok("c", TokenType.CREW, 20, 10)
    fx.update([c], 0)
    assert fx.fatigue_of("c", SHIFT_TICKS) == 0.0
    assert fx.fatigue_of("c", SHIFT_TICKS + FADE_TICKS) == 1.0


def test_relief_takes_over_and_starts_a_fresh_shift(router):
    d = Dispatcher([Station("West", 2, 10, "ground", {"crew": 2})], router)
    fx = TokenEffects(W, H)
    c = tok("c", TokenType.CREW, 30, 10)
    t = 0
    for t in range(SHIFT_TICKS + 60):
        acting = d.update([c], t, 5.0, None)
        fx.update(acting, t, d.starts())
    assert fx.fatigue_of("c", t) > 0
    tired = next(u for u in d.units if u.token_id == "c")
    assert d.relieve("c", t, 5.0, [c])
    assert not d.relieve("c", t, 5.0, [c])  # relief already on its way
    while tired.status == "working":  # keeps working until the relief gets there
        t += 1
        acting = d.update([c], t, 5.0, None)
        fx.update(acting, t, d.starts())
        assert any(k.id == "c" for k in acting)
    assert tired.status == "resting" and tired.ready_tick == t + REST_TICKS
    assert fx.fatigue_of("c", t) == 0.0
    fresh = next(u for u in d.units if u.token_id == "c")
    assert fresh is not tired and fresh.status == "working"


def test_a_tanker_shuttles_between_drops(router):
    d = Dispatcher([Station("Air", 2, -60, "air", {"water": 1})], router)
    fx = TokenEffects(W, H)
    w = tok("w", TokenType.WATER, 20, 10)
    drops = []
    for t in range(400):
        acting = d.update([w], t, 5.0, None)
        before = d.starts().get("w")
        fx.update(acting, t, d.starts())
        if before is not None and (not drops or drops[-1] != before):
            drops.append(before)
    assert len(drops) >= 3
    gaps = np.diff(drops)
    assert gaps.min() >= RELOAD_MIN  # each round trip includes refilling at base
    assert np.ptp(gaps) <= 1  # a steady cadence


def test_mutual_aid_arrives_after_a_delay_and_leaves_on_reset(router):
    d = Dispatcher([Station("West", 2, 10, "ground", {"crew": 1})], router)
    staging = Station("Staging", 38, 10, "ground", {})
    u = d.mutual_aid(TokenType.CREW, 0, staging)
    assert u.status == "resting" and len(d.units) == 2
    run(d, [], MUTUAL_AID_TICKS + 1)
    assert u.status == "available"
    d.reset()
    assert len(d.units) == 1


def test_the_patrol_band_fades_with_the_crew():
    """A staffed line's patrol (partial suppression beside it) tires with its
    crew; the dug strip itself stays full suppression."""
    from sim.effects import PATROL

    layer = crew_layer(W, H, 20, 10, wind_from=90.0)  # wind from the east: the line runs east-west
    early, late = layer.grid(CREW_RAMP_TICKS + 40), layer.grid(SHIFT_TICKS + FADE_TICKS * 3)
    on, beside = (10, 37), (12, 37)  # 17 cells along, past the crew's disk; on the strip, and 2 cells off it
    assert early[on] == 1.0 and late[on] == 1.0
    assert early[beside] == pytest.approx(PATROL)
    assert late[beside] == pytest.approx(PATROL * FATIGUE_FLOOR)


def test_moved_crew_does_not_act_before_it_gets_there(router):
    """A crew that has worked and is then moved drives to the new spot before
    it acts there (silver-vole's repro on #187)."""
    d = Dispatcher([Station("West", 2, 10, "ground", {"crew": 1})], router)
    run(d, [tok("c", TokenType.CREW, 20, 10)], 200)
    acting = d.update([tok("c", TokenType.CREW, 36, 10)], 200, 5.0, None)
    assert d.units[0].status == "en_route"
    assert [t.id for t in acting] == []
