"""A dug-in crew cuts a growing line along the wind (#99)."""

import numpy as np

from protocol import Token, TokenSource, TokenType
from sim.effects import CREW_RADIUS, CREW_RAMP_TICKS, LINE_LENGTH, LINE_RATE, TokenEffects, crew_layer

W, H = 200, 160
X, Y = 100.0, 80.0


def _crew() -> Token:
    return Token(id="c", token_type=TokenType.CREW, x=X, y=Y, angle=0.0, source=TokenSource.VIRTUAL)


def _full(g: np.ndarray) -> set[tuple[int, int]]:
    return {(int(x), int(y)) for y, x in zip(*np.nonzero(g >= 1.0))}


def test_line_grows_along_the_wind_after_digging_in():
    fx = TokenEffects(W, H)
    fx.set_wind(0.0)  # from the north: the line runs north-south through the crew
    assert not _full(fx.update([_crew()], 0))
    assert not _full(fx.update([_crew()], CREW_RAMP_TICKS))  # dug in, nothing cut yet
    later = CREW_RAMP_TICKS + 40
    cells = _full(fx.update([_crew()], later))
    reach = LINE_RATE * 40
    ys = [y for _, y in cells]
    assert all(abs(x + 0.5 - X) <= 1.0 for x, _ in cells)  # a north-south strip
    assert max(ys) - min(ys) >= 2 * reach - 2  # both ways from the crew
    # It keeps growing, past the crew's own disk, up to its full length.
    done = _full(fx.update([_crew()], later + 1000))
    ys = [y for _, y in done]
    assert max(ys) - min(ys) >= LINE_LENGTH - 2 > 2 * CREW_RADIUS


def test_line_keeps_the_direction_it_started_with():
    fx = TokenEffects(W, H)
    fx.set_wind(0.0)
    fx.update([_crew()], 0)
    fx.set_wind(90.0)  # the wind shifts after the crew started
    cells = _full(fx.update([_crew()], CREW_RAMP_TICKS + 200))
    assert all(abs(x + 0.5 - X) <= 1.0 for x, _ in cells)


def test_no_wind_no_line():
    fx = TokenEffects(W, H)
    assert not _full(fx.update([_crew()], CREW_RAMP_TICKS + 200))


def test_schedule_credits_the_line_as_it_grows():
    """Forecasts see the line the live sim will cut: schedule().at(dt) matches update() dt ticks on."""
    fx, live = TokenEffects(W, H), TokenEffects(W, H)
    for e in (fx, live):
        e.set_wind(45.0)
        e.update([_crew()], 0)
    sched = fx.schedule([_crew()], 1)
    for dt in (0, 30, 90):
        np.testing.assert_array_equal(sched.at(dt), live.update([_crew()], 1 + dt))


def test_crew_layer_matches_a_placed_crew():
    """A recommended crew (crew_layer) cuts the same line a placed one would."""
    fx = TokenEffects(W, H)
    fx.set_wind(45.0)
    fx.update([_crew()], 0)
    layer = crew_layer(W, H, X, Y, wind_from=45.0)
    for dt in (CREW_RAMP_TICKS + 10, CREW_RAMP_TICKS + 100):
        np.testing.assert_array_equal(layer.grid(dt) >= 1.0, fx.update([_crew()], dt) >= 1.0)


def test_line_of_gives_the_ends_the_map_draws():
    """The units message carries the line cut so far (#159): nothing while
    digging in, then two ends either side of the crew, along the wind."""
    fx = TokenEffects(W, H)
    fx.set_wind(0.0)  # from the north: the line runs north-south
    fx.update([_crew()], 0)
    assert fx.line_of("c", CREW_RAMP_TICKS) == []
    (x1, y1), (x2, y2) = fx.line_of("c", CREW_RAMP_TICKS + 20)
    assert x1 == x2 == X and abs((y1 + y2) / 2 - Y) < 1e-6
    assert abs(abs(y2 - y1) - 2 * LINE_RATE * 20) < 1e-6
    assert fx.line_growing(CREW_RAMP_TICKS + 20)
    (_, y1), (_, y2) = fx.line_of("c", 10_000)
    assert abs(abs(y2 - y1) - LINE_LENGTH) < 1e-6
    assert not fx.line_growing(10_000)
    assert fx.line_of("nobody", 100) == []
