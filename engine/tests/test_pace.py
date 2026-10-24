"""Pause, resume, single steps and sim speed."""

import asyncio
import json

from protocol import SetRunning, SetSpeed, StartRound, StepOnce
from server import Engine


def run_engine(body):
    async def run():
        engine = Engine()
        try:
            body(engine)
        finally:
            engine.forecaster.shutdown()
            engine.long_forecaster.shutdown()
            engine.recommender.shutdown()
            if engine.camera is not None:
                engine.camera.stop()

    asyncio.run(run())


def test_pause_stops_the_fire_and_step_once_advances_one_tick():
    def body(engine: Engine):
        engine.dispatch(SetRunning(running=False))
        for _ in range(5):
            engine.tick_fire()
        assert engine.fire.tick == 0
        state = json.loads(engine.state_msg())
        assert state["paused"] is True and state["running"] is False

        engine.dispatch(StepOnce())
        assert engine.fire.tick == 1

        engine.dispatch(SetRunning(running=True))
        engine.tick_fire()
        assert engine.fire.tick == 2

    run_engine(body)


def test_step_once_is_ignored_while_running():
    def body(engine: Engine):
        engine.dispatch(StepOnce())
        assert engine.fire.tick == 0

    run_engine(body)


def test_speed_sets_steps_per_engine_tick():
    def body(engine: Engine):
        engine.dispatch(SetSpeed(speed=4))
        engine.tick_fire()
        assert engine.fire.tick == 4

        engine.dispatch(SetSpeed(speed=0.5))
        for _ in range(4):
            engine.tick_fire()
        assert engine.fire.tick == 6  # half a step per tick
        assert json.loads(engine.state_msg())["speed"] == 0.5

    run_engine(body)


def test_a_paused_round_keeps_its_clock_still_and_starting_unpauses():
    def body(engine: Engine):
        engine.dispatch(SetRunning(running=False))
        engine.dispatch(StartRound())
        assert engine.paused is False
        for _ in range(3):
            engine.tick_fire()
        engine.dispatch(SetRunning(running=False))
        before = engine.game.elapsed_min(engine.fire.tick)
        for _ in range(10):
            engine.tick_fire()
        assert engine.game.elapsed_min(engine.fire.tick) == before == 3

    run_engine(body)
