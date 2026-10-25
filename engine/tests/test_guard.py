"""Grounding guard: no number the simulation didn't produce."""

import asyncio

from commander.agent import CORRECTION, Commander
from commander.guard import SentenceGate, allowed_numbers, is_grounded, numbers_in_text, split_sentences, ungrounded
from commander.tools import CommanderTools
from test_commander_agent import FakeClient, engine, text_msg, tool_msg  # noqa: F401  (engine is a fixture)

SITUATION = {
    "towns": [{"town": "Paradise", "fire_reaches_within_30_min": {"simulations": 24, "of": 32},
               "median_minutes_until_fire": 22}],
    "fire": {"burned_acres": 1685},
}


def test_numbers_in_digits_and_words():
    assert numbers_in_text("24 of 32, about 1,685 acres, 16.5 m/s") == [24, 32, 1685, 16.5]
    assert sorted(numbers_in_text("twenty-four of thirty-two, in eight minutes")) == [8, 24, 32]
    assert numbers_in_text("one of the routes is cut") == []  # "one" isn't a figure


def test_allowed_numbers_cover_values_keys_percentages_and_the_question():
    allowed = allowed_numbers([SITUATION], "What if wind hits 12 m/s?")
    assert {24, 32, 22, 1685, 30, 75, 12} <= allowed  # 30 from the key, 75 = 24/32, 12 from the question


def test_spoken_rounding_is_grounded_but_new_numbers_are_not():
    allowed = {231.6, 1685.0, 22.0}
    assert is_grounded(230, allowed) and is_grounded(200, allowed) and is_grounded(1700, allowed)
    assert is_grounded(22, allowed) and not is_grounded(23.5, allowed)
    assert ungrounded("Paradise in 22 minutes, maybe 45.", allowed) == [45]


def test_sentence_gate_releases_good_sentences_and_stops_at_a_bad_one():
    out = []
    gate = SentenceGate(lambda: {24.0, 32.0}, out.append)
    for chunk in ["Paradise is thre", "atened in 24 of 32 simulations. Evac", "uate now. It burns in 90 minutes. Go."]:
        gate.feed(chunk)
    gate.flush()
    assert out == ["Paradise is threatened in 24 of 32 simulations.", "Evacuate now."]
    assert gate.failed


def test_split_sentences():
    assert split_sentences("One. Two!  Three?") == ["One.", "Two!", "Three?"]


def test_invented_number_triggers_one_corrective_retry(engine):  # noqa: F811
    client = FakeClient(
        tool_msg("get_situation", {}),
        text_msg("Paradise burns in 7777 minutes."),
        text_msg("Pulga is threatened in 32 of 32 simulations."),
    )
    said = []
    ans = asyncio.run(Commander(CommanderTools(engine), client=client).answer("Status?", on_sentence=said.append))
    assert ans.source == "llm" and ans.grounded and ans.text == "Pulga is threatened in 32 of 32 simulations."
    assert said == [ans.text]  # the bad sentence was never released
    correction = client.requests[2]["messages"][-1]["content"]
    assert correction == CORRECTION.format(bad="7777")


def test_bad_number_after_a_spoken_sentence_keeps_only_what_was_said(engine):  # noqa: F811
    client = FakeClient(
        tool_msg("get_situation", {}),
        text_msg("Pulga is threatened in 32 of 32 simulations. Chico burns in 7777 minutes."),
    )
    said = []
    ans = asyncio.run(Commander(CommanderTools(engine), client=client).answer("Status?", on_sentence=said.append))
    assert said == ["Pulga is threatened in 32 of 32 simulations."]
    assert ans.text == said[0] and ans.grounded and len(client.requests) == 2  # no retry once speech started


def test_bad_number_with_no_listener_retries_the_whole_answer(engine):  # noqa: F811
    # The server sends only the finished answer, so nothing was out yet (#153).
    client = FakeClient(
        tool_msg("get_situation", {}),
        text_msg("Pulga is threatened in 32 of 32 simulations. Chico burns in 7777 minutes."),
        text_msg("Pulga is threatened in 32 of 32 simulations."),
    )
    ans = asyncio.run(Commander(CommanderTools(engine), client=client).answer("Status?"))
    assert ans.source == "llm" and ans.grounded and ans.text == "Pulga is threatened in 32 of 32 simulations."
    assert len(client.requests) == 3


def test_still_ungrounded_after_retry_falls_back_to_rules(engine):  # noqa: F811
    client = FakeClient(
        tool_msg("get_situation", {}),
        text_msg("Paradise burns in 7777 minutes."),
        text_msg("Paradise burns in 8888 minutes."),
    )
    said = []
    ans = asyncio.run(Commander(CommanderTools(engine), client=client).answer("Status?", on_sentence=said.append))
    assert ans.source == "rules" and ans.grounded and said == split_sentences(ans.text)
