"""Scripted questions for the commander: does it call the right tool, stay
grounded and short, and answer fast enough?

    cd engine && uv run python -m commander.eval.run
    cd engine && uv run python -m commander.eval.run --model claude-sonnet-5-5 --effort low --out report.md

Each case is a question asked against a scripted fire (the Camp Fire origin
after N sim minutes, or no fire). A case passes when the answer:
- called one of the expected tools,
- is grounded (every number from a tool; see commander/guard.py),
- is at most two sentences,
- and isn't empty.
The report lists every case plus pass rate and p50/p95 time to the first
spoken sentence and to the full answer. Without an API key it measures the
rule-based fallback instead (the report says which answered).

Each run makes real API calls when a key is set: about 20 questions, each a
few short requests.
"""

import argparse
import asyncio
import statistics
import time
from dataclasses import dataclass

import commander.agent as agent_mod
from commander.agent import Commander, has_credentials
from commander.ask import scripted_engine, shutdown
from commander.guard import split_sentences

YOUNG, OLD, NONE = 40, 90, 0  # fire age in sim minutes; 0 = nothing burning


@dataclass(frozen=True)
class Case:
    fire: int
    question: str
    tools: tuple[str, ...]  # any of these counts as the right tool
    in_round: bool = False  # a round is running (#68), started when the fire was lit


CASES = [
    Case(YOUNG, "What if the wind shifts west?", ("forecast_whatif",)),
    Case(YOUNG, "What happens if the wind comes from the south at 15 meters per second?", ("forecast_whatif",)),
    Case(YOUNG, "Which town is in the most danger?", ("get_situation",)),
    Case(YOUNG, "How long until the fire reaches Pulga?", ("get_situation",)),
    Case(YOUNG, "Where should I put my next crew?", ("get_situation", "evaluate_placement")),
    Case(YOUNG, "Would a crew at Concow help?", ("evaluate_placement",)),
    Case(YOUNG, "Is Paradise's evacuation route safe?", ("get_routes", "get_situation")),
    Case(YOUNG, "How many acres have burned?", ("get_situation",)),
    Case(YOUNG, "What's the fire going to do in the next hour?", ("get_situation",)),
    Case(YOUNG, "How sure are you that Paradise is safe for now?", ("get_situation",)),
    Case(OLD, "Is Magalia's way out still open?", ("get_routes", "get_situation")),
    Case(OLD, "What if the wind dies down to 3 meters per second?", ("forecast_whatif",)),
    Case(OLD, "Should we evacuate Concow now?", ("get_situation", "get_routes")),
    Case(OLD, "Give me a status update.", ("get_situation",)),
    Case(OLD, "What if the wind turns north-west?", ("forecast_whatif",)),
    Case(OLD, "Would a crew near Magalia keep the fire out?", ("evaluate_placement",)),
    Case(OLD, "Which routes are cut?", ("get_routes",)),
    Case(OLD, "Can buses still get out of Concow?", ("get_routes",)),
    Case(NONE, "What's the situation?", ("get_situation",)),
    Case(NONE, "What if the wind shifts west?", ("forecast_whatif",)),
    Case(OLD, "How are we doing?", ("get_situation",), in_round=True),
    Case(YOUNG, "How many crews do I have left?", ("get_situation",), in_round=True),
]


@dataclass
class Result:
    case: Case
    text: str
    source: str
    tools: list[str]
    grounded: bool
    sentences: int
    first_s: float | None
    total_s: float

    @property
    def right_tool(self) -> bool:
        return any(t in self.tools for t in self.case.tools)

    @property
    def passed(self) -> bool:
        return self.right_tool and self.grounded and 0 < self.sentences <= 2


async def run_case(case: Case, model: str | None, effort: str | None) -> Result:
    e = await scripted_engine(case.fire, in_round=case.in_round)
    try:
        cmd = Commander(e.tools, model=model, effort=effort)
        t0 = time.perf_counter()
        first: list[float] = []
        ans = await cmd.answer(case.question, on_sentence=lambda s: first or first.append(time.perf_counter() - t0))
        total = time.perf_counter() - t0
        return Result(case, ans.text, ans.source, ans.tools_used, ans.grounded, len(split_sentences(ans.text)),
                      first[0] if first else None, total)
    finally:
        shutdown(e)


def pct(xs: list[float], p: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p * (len(xs) - 1))))] if xs else float("nan")


def report(results: list[Result], model: str, effort: str) -> str:
    firsts = [r.first_s for r in results if r.first_s is not None]
    totals = [r.total_s for r in results]
    llm = sum(r.source == "llm" for r in results)
    lines = [
        f"# Commander eval: {model}, effort {effort}",
        "",
        f"- Passed: **{sum(r.passed for r in results)}/{len(results)}** "
        f"(right tool {sum(r.right_tool for r in results)}, grounded {sum(r.grounded for r in results)}, "
        f"≤ 2 sentences {sum(0 < r.sentences <= 2 for r in results)})",
        f"- Answered by the LLM: {llm}/{len(results)} (the rest fell back to templates)",
        f"- First sentence: p50 {pct(firsts, 0.5):.2f} s, p95 {pct(firsts, 0.95):.2f} s",
        f"- Full answer: p50 {statistics.median(totals):.2f} s, p95 {pct(totals, 0.95):.2f} s",
        "",
        "| # | Fire | Question | Pass | Source | Tools | First s | Total s | Answer |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(results, 1):
        fire = (f"{r.case.fire} min" if r.case.fire else "none") + (", round" if r.case.in_round else "")
        mark = "✅" if r.passed else "❌ " + ", ".join(
            w for w, ok in (("tool", r.right_tool), ("grounded", r.grounded), ("length", 0 < r.sentences <= 2)) if not ok)
        first = f"{r.first_s:.2f}" if r.first_s is not None else "–"
        lines.append(f"| {i} | {fire} | {r.case.question} | {mark} | {r.source} | {', '.join(r.tools) or '–'} | "
                     f"{first} | {r.total_s:.2f} | {r.text.replace('|', '/')} |")
    return "\n".join(lines) + "\n"


async def main(model: str | None, effort: str | None, out: str | None, only: int | None) -> None:
    cases = CASES[:only] if only else CASES
    results = []
    for i, case in enumerate(cases, 1):
        r = await run_case(case, model, effort)
        print(f"[{i}/{len(cases)}] {'pass' if r.passed else 'FAIL'} {r.source} {r.total_s:.2f}s  {case.question}")
        results.append(r)
    name = model or Commander.__init__.__defaults__ and agent_mod.os.environ.get("COMMANDER_MODEL") or agent_mod.DEFAULT_MODEL
    text = report(results, name if has_credentials() else "rules only (no API key)", effort or agent_mod.EFFORT)
    if out:
        with open(out, "w") as f:
            f.write(text)
        print(f"wrote {out}")
    else:
        print(text)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--model", help="defaults to COMMANDER_MODEL, then claude-opus-5-5")
    p.add_argument("--effort", choices=["low", "medium", "high", "xhigh", "max"])
    p.add_argument("--out", help="write the markdown report here instead of printing it")
    p.add_argument("--only", type=int, help="run just the first N cases")
    args = p.parse_args()
    asyncio.run(main(args.model, args.effort, args.out, args.only))
