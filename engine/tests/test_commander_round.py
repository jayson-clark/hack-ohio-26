"""The commander knows the round (#78): situation, answers, and the round-end briefing."""

import asyncio
import json

import pytest

from commander.agent import rule_based_answer
from commander.briefings import BriefingQueue, round_summary
from commander.guard import allowed_numbers, ungrounded
from protocol import EndReason, EndRound, Event, EventKind, RoundPhase, Score, TokenType
from test_commander_agent import engine  # noqa: F401  (fixture)


def test_sandbox_round_says_no_round(engine):  # noqa: F811
    assert engine.tools.get_situation()["round"] == {"phase": "no round running (free play: no limits, no timer)"}
    ans = asyncio.run(rule_based_answer(engine.tools, "How are we doing?"))
    assert ans.text == "No round is running, so there's no clock or score yet."


def test_running_round_has_time_left_score_and_resources(engine):  # noqa: F811
    engine.game.start(engine.fire.tick - 100)  # 100 sim-minutes in
    engine.game.used = {TokenType.CREW: 1}
    r = engine.tools.get_situation()["round"]
    assert r["phase"] == "running" and r["minutes_elapsed"] == 100 and r["minutes_left"] == 500
    crew = next(x for x in r["resources"] if x["type"] == "crew")
    assert crew == {"type": "crew", "used": 1, "limit": 3, "left": 2}

    out = engine.tools.get_situation()
    ans = asyncio.run(rule_based_answer(engine.tools, "How much time do we have left?"))
    assert ans.text.startswith("500 minutes left:") and "2 crews" in ans.text and "1 firebreak" in ans.text
    assert ungrounded(ans.text, allowed_numbers([out])) == []


def score(**kw):
    base = dict(tick=600, phase=RoundPhase.ENDED, end_reason=EndReason.TIME, elapsed_min=600, duration_min=600,
                resources=[], inactive_tokens=[], water_cooldowns=[], people_total=52000, people_evacuated=1240,
                structures_total=22000, structures_lost=3100, acres_burned=8412.6, towns=[])
    return Score(**{**base, **kw})


def test_round_summary_reads_the_score():
    assert round_summary(score()) == ("The round is over: time ran out. 1,240 of 52,000 people evacuated, "
                                      "3,100 of 22,000 structures lost, and 8,413 acres burned.")
    assert round_summary(score(end_reason=EndReason.CONTAINED)).startswith("The round is over: the fire is out.")


def test_ending_a_round_briefs_the_score_and_clears_old_news(engine, monkeypatch):  # noqa: F811
    sent = []
    monkeypatch.setattr("server.broadcast", lambda clients, msg: sent.append(json.loads(msg)))
    engine.briefings.offer([Event(kind=EventKind.TOWN_THREATENED, tick=engine.fire.tick, town="Concow",
                                  text="Concow is threatened.")], 0.0)
    engine.game.start(engine.fire.tick)
    engine.dispatch(EndRound())
    [p] = engine.briefings.pending
    assert p.event.kind == EventKind.ROUND_ENDED and p.event.text.startswith("The round is over: it was stopped.")
    assert any(m["type"] == "events" and m["events"][0]["kind"] == "round_ended" for m in sent)
    msg = engine.briefings.next(100.0, engine.fire.tick)
    assert msg.event == EventKind.ROUND_ENDED and msg.grounded


def test_ending_outside_a_round_says_nothing(engine):  # noqa: F811
    engine.dispatch(EndRound())  # sandbox: nothing to end
    assert engine.briefings.pending == []


@pytest.mark.parametrize("q", ["What's the score?", "How many crews do I have left?", "How are we doing?"])
def test_round_questions_use_the_round(engine, q):  # noqa: F811
    engine.game.start(engine.fire.tick)
    ans = asyncio.run(rule_based_answer(engine.tools, q))
    assert ans.tools_used == ["get_situation"] and "minutes left" in ans.text
