"""Ask the commander a question against a scripted fire, from the terminal.

    cd engine && uv run python -m commander.ask "What if the wind shifts west?"

Starts the Camp Fire origin burning under a north-east wind, lets it run for
--minutes, forecasts, then answers and prints which tools ran, whether the
LLM or the rules answered, and how long it took. Reads ANTHROPIC_API_KEY and
COMMANDER_MODEL from the environment (the Makefile exports the root .env;
otherwise export them yourself).
"""

import argparse
import asyncio
import time

from commander.agent import Commander, has_credentials
from forecast.runner import run_forecast
from server import Engine
from sim.fire import Wind


async def scripted_engine(minutes: int, wind: Wind = Wind(10, 45), in_round: bool = False) -> Engine:
    """An engine with the Camp Fire origin burning for `minutes`, forecast,
    routes and recommendations all current, as the server would have them.
    Call shutdown(e) when done. minutes=0 means no fire at all. in_round
    starts a round at the ignition, so the fire is `minutes` into it."""
    e = Engine()
    if in_round:
        e.game.start(0)
    e.fire.set_wind(wind)
    if minutes:
        e.fire.ignite(217.3, 54.5)
        for _ in range(minutes):
            e.fire.step()
        e.game.update(e.fire.tick, e.fire.state, [], set())  # score the map as the server would
        e.latest_forecast = f = run_forecast(e.fire.snapshot(), seed=0)
    await e.recommender.warm()
    if minutes:
        e.check_road_cuts()
        e.schedule_replan()
        await e._route_job
        recs = await e.recommender.submit(e.fire.snapshot(), f.probability[0], e.towns, seed=0)
        acres_per_cell = e.scenario.cell_size_m**2 / 4046.86
        e.recs = [e.rec_message(r, f"r{i}", acres_per_cell) for i, r in enumerate(recs)]
    return e


def shutdown(e: Engine) -> None:
    e.forecaster.shutdown()
    e.recommender.shutdown()


async def main(question: str, minutes: int) -> None:
    e = await scripted_engine(minutes)
    try:
        cmd = Commander(e.tools)
        print(f"model: {cmd.model} | credentials: {'yes' if has_credentials() else 'no (rules only)'}")
        t0 = time.perf_counter()
        first: list[float] = []

        def on_sentence(sentence: str) -> None:
            if not first:
                first.append(time.perf_counter() - t0)

        ans = await cmd.answer(question, on_sentence=on_sentence)
        total = time.perf_counter() - t0
        ttfs = f"{first[0]:.2f}s" if first else "n/a"
        print(f"[{ans.source}] grounded={ans.grounded} tools={ans.tools_used} first sentence={ttfs} total={total:.2f}s")
        print(ans.text)
    finally:
        shutdown(e)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("question")
    p.add_argument("--minutes", type=int, default=40, help="sim minutes to let the fire run first")
    args = p.parse_args()
    asyncio.run(main(args.question, args.minutes))
