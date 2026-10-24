"""The incident commander's question answering (PLAN.md, Incident commander).

A question ("what if the wind shifts west?") goes to Claude with the four
simulation tools from commander/tools.py. Claude calls tools, the tools run
real forecasts, and the answer comes back in about two spoken sentences.

If there's no API key, the model refuses, the network fails, or the answer
takes longer than ANSWER_TIMEOUT_S, the commander answers from the same tools
with a template instead (rule_based_answer), so the demo never goes quiet.

Conversation history: within one question the tool loop is append-only
(thinking blocks must be replayed unchanged). Across questions only plain
question/answer text is kept, so trimming old turns never edits a turn that
carries thinking.
"""

import asyncio
import json
import logging
import os
import re
from collections import deque
from collections.abc import Callable

from commander.guard import SentenceGate, allowed_numbers, split_sentences, ungrounded
from commander.tools import COMPASS, TOOL_SPECS, CommanderTools

log = logging.getLogger("commander")

DEFAULT_MODEL = "claude-opus-5-5"
# Short spoken answers: low effort keeps latency down. Thinking can't be
# turned off on this model, so effort is the latency lever.
EFFORT = os.environ.get("COMMANDER_EFFORT") or "low"
MAX_TOKENS = 4000
MAX_TOOL_ROUNDS = 4
ANSWER_TIMEOUT_S = 6.0
HISTORY_TURNS = 3  # previous Q&A pairs kept for follow-ups
FALLBACK_BETA = "server-side-fallback-2026-07-01"

SYSTEM = """You are the incident commander for a wildfire on a projected terrain table: the Camp Fire country \
around Paradise, California. Crew bosses ask you questions out loud, and your answer is spoken back to them.

How to answer:
- Before stating any number, call a tool. Every figure you say must come from a tool result in this \
conversation. Never estimate, extrapolate, or invent one.
- Answer in at most two short sentences, plain spoken English: no lists, no markdown, no map coordinates.
- Say probabilities the way the tools give them: "in 24 of 32 simulations". Don't convert them to \
percentages unless the tool gave a percentage.
- Counts come with "likely_percent" (the range the true chance is likely in, given only that many \
simulations) and "confidence". When confidence is "moderate" or "low", say the range ("likely 60 to 85 \
percent") or hedge ("probably"); never sound more certain than that.
- If a tool returns an error, or the data doesn't answer the question, say so briefly instead of guessing.
- For "what if the wind..." questions, use forecast_whatif and compare with the current forecast.
- For "where should crews go" questions, use get_situation (it includes the current recommendations) or \
evaluate_placement for a specific spot.
- For evacuation questions, use get_routes.
- For "how are we doing", time left, score or resources, use get_situation (its "round" part)."""

def has_credentials() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


TOOLS = [{**t, "strict": True} for t in TOOL_SPECS]
# Requests render tools, then system, then messages. Both of the first two are
# identical on every call, so a breakpoint at the end of the system prompt
# caches them together. Nothing volatile (time, tick, state) goes in either.
SYSTEM_BLOCKS = [{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}]


class Answer:
    def __init__(self, text: str, tools_used: list[str], tool_results: list[dict], source: str,
                 grounded: bool = True) -> None:
        self.text = text
        self.tools_used = tools_used
        self.tool_results = tool_results
        self.source = source  # "llm" or "rules"
        self.grounded = grounded  # every number in text came from a tool (checked for LLM answers)


SentenceCallback = Callable[[str], None]

CORRECTION = ("Your answer used numbers that aren't in the tool results: {bad}. Answer again in at most two "
              "sentences, using only numbers from the tool results.")


class Commander:
    def __init__(self, tools: CommanderTools, client=None, model: str | None = None, effort: str | None = None) -> None:
        self.tools = tools
        self.model = model or os.environ.get("COMMANDER_MODEL") or DEFAULT_MODEL
        self.effort = effort or EFFORT
        self._client = client
        self.history: deque[tuple[str, str]] = deque(maxlen=HISTORY_TURNS)

    @property
    def client(self):
        if self._client is None and has_credentials():
            from anthropic import AsyncAnthropic

            self._client = AsyncAnthropic(max_retries=1)
        return self._client

    def reset(self) -> None:
        self.history.clear()

    async def answer(self, question: str, on_sentence: SentenceCallback | None = None) -> Answer:
        """Answer a question with the LLM if it can, else from rules. Never raises.

        `on_sentence` gets each sentence as soon as it's known to be grounded
        (for text-to-speech). Whatever it receives is exactly the start of the
        final answer's text.
        """
        said: list[str] = []

        def emit(sentence: str) -> None:
            said.append(sentence)
            if on_sentence is not None:
                on_sentence(sentence)

        result = None
        if self.client is not None:
            try:
                result = await asyncio.wait_for(self._llm_answer(question, emit, said), ANSWER_TIMEOUT_S)
            except asyncio.TimeoutError:
                log.warning("commander answer timed out; using rules")
            except asyncio.CancelledError:
                raise
            except Exception as err:  # network, auth, bad request: the demo keeps going
                log.warning("commander LLM failed (%s); using rules", err)
        if result is None and said:
            # Part of an answer was already spoken; finish there rather than
            # start a second, different answer.
            result = Answer(" ".join(said), [], [], "llm", grounded=True)
        if result is None:
            result = await rule_based_answer(self.tools, question)
            for sentence in split_sentences(result.text):
                emit(sentence)
        self.history.append((question, result.text))
        return result

    async def _llm_answer(self, question: str, emit: SentenceCallback, said: list[str]) -> Answer | None:
        messages: list[dict] = []
        for q, a in self.history:
            messages += [{"role": "user", "content": q}, {"role": "assistant", "content": a}]
        messages.append({"role": "user", "content": question})
        used: list[str] = []
        results: list[dict] = []
        gate = SentenceGate(lambda: allowed_numbers(results, question), emit)
        retried = False
        for _ in range(MAX_TOOL_ROUNDS + 1):
            msg = await self._turn(messages, gate)
            if msg is None:
                return None
            tool_uses = [b for b in msg.content if b.type == "tool_use"]
            if not tool_uses:
                text = " ".join(b.text.strip() for b in msg.content if b.type == "text").strip()
                if not text:
                    return None
                bad = ungrounded(text, allowed_numbers(results, question))
                if not bad and not gate.failed:
                    return Answer(text, used, results, "llm", grounded=True)
                log.warning("commander answer had ungrounded numbers %s: %r", bad, text)
                if said or retried:
                    return None  # caller keeps what was said, or falls back to rules
                retried = True
                gate.failed = False
                messages.append({"role": "assistant", "content": msg.content})
                messages.append({"role": "user", "content": CORRECTION.format(bad=", ".join(f"{n:g}" for n in bad))})
                continue
            if msg.stop_reason == "max_tokens":
                return None  # a truncated tool call; don't run it
            messages.append({"role": "assistant", "content": msg.content})
            blocks = []
            for b in tool_uses:
                out = await self.tools.call(b.name, b.input if isinstance(b.input, dict) else {})
                used.append(b.name)
                results.append(out)
                blocks.append({"type": "tool_result", "tool_use_id": b.id, "content": json.dumps(out),
                               "is_error": "error" in out})
            messages.append({"role": "user", "content": blocks})
        return None

    async def _turn(self, messages: list[dict], gate: SentenceGate):
        """One streamed request. Returns the final message, or None on refusal."""
        async with self.client.beta.messages.stream(
            model=self.model,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_BLOCKS,
            tools=TOOLS,
            messages=messages,
            output_config={"effort": self.effort},
            betas=[FALLBACK_BETA],
            fallbacks="default",
        ) as stream:
            async for text in stream.text_stream:
                gate.feed(text)
            msg = await stream.get_final_message()
        gate.flush()
        usage = msg.usage
        log.info("commander turn: stop=%s in=%s cached=%s out=%s", msg.stop_reason, usage.input_tokens,
                 usage.cache_read_input_tokens, usage.output_tokens)
        if msg.stop_reason == "refusal":
            log.warning("commander refused: %s", getattr(msg, "stop_details", None))
            return None
        return msg


# --- Rule-based answers: no LLM, same tools ----------------------------------

_SPEED = re.compile(r"(\d+(?:\.\d+)?)\s*(m/s|meters? per second|metres? per second|mph|miles per hour)", re.I)


def _wind_direction(q: str) -> str | None:
    words = re.findall(r"north-?east|north-?west|south-?east|south-?west|north|south|east|west", q.lower())
    if not words:
        return None
    w = words[0].replace("northeast", "north-east").replace("northwest", "north-west")
    w = w.replace("southeast", "south-east").replace("southwest", "south-west")
    return w if w in COMPASS else None


def _wind_speed(q: str) -> float | None:
    m = _SPEED.search(q)
    if not m:
        return None
    v = float(m.group(1))
    return v / 2.237 if m.group(2).lower().startswith(("mph", "mile")) else v


def _named(q: str, names) -> str | None:
    """The first of `names` mentioned in the question (longest names first)."""
    for name in sorted(names, key=len, reverse=True):
        if name.lower() in q:
            return name
    return None


def _reach_phrase(row: dict, key: str = "fire_reaches_within_60_min") -> str:
    r = row[key]
    return f"{r['simulations']} of {r['of']}"


def _round_line(r: dict) -> str:
    if "minutes_elapsed" not in r:
        return "No round is running, so there's no clock or score yet."
    names = {"crew": ("crew", "crews"), "water": ("water drop", "water drops"),
             "firebreak": ("firebreak", "firebreaks"), "bus": ("bus", "buses")}
    left = [f"{x['left']} {names.get(x['type'], (x['type'], x['type'] + 's'))[x['left'] != 1]}"
            for x in r["resources"] if x["left"] is not None]
    score = (f"{r['people_evacuated']:,} of {r['people_total']:,} people are out and "
             f"{r['structures_lost']:,} of {r['structures_total']:,} structures lost")
    if r["phase"] == "ended":
        return f"The round is over because {r['ended_because']}: {score}, with {r['acres_burned']:,} acres burned."
    text = f"{r['minutes_left']} minutes left: {score}."
    if left:
        text += f" You have {', '.join(left[:-1]) + ' and ' + left[-1] if len(left) > 1 else left[0]} left."
    return text


def _town_line(t: dict) -> str:
    r30, r60 = t["fire_reaches_within_30_min"], t["fire_reaches_within_60_min"]
    if t.get("fire_inside_town_now"):
        return f"Fire is already inside {t['town']}."
    if r60["simulations"] == 0:
        return f"No simulation has fire reaching {t['town']} within the hour."
    text = f"Fire reaches {t['town']} within 30 minutes in {_reach_phrase(t, 'fire_reaches_within_30_min')} simulations"
    if r30["simulations"] == 0:
        text = f"Fire reaches {t['town']} within the hour in {_reach_phrase(t)} simulations"
    shown = r30 if r30["simulations"] else r60
    if shown.get("confidence") in ("moderate", "low") and "likely_percent" in shown:
        lo, hi = shown["likely_percent"]
        text += f" (likely {lo} to {hi} percent)"
    if t.get("median_minutes_until_fire") is not None:
        text += f", about {t['median_minutes_until_fire']} minutes out"
    return text + "."


async def rule_based_answer(tools: CommanderTools, question: str) -> Answer:
    """A templated answer from the tools, for when the LLM isn't available.
    Picks the tool from keywords, and uses any town, place, wind direction or
    speed named in the question."""
    q = question.lower()
    town_names = [t.name for t in tools.e.towns]
    place = _named(q, [v[2] for v in tools.places.values()])

    # Round questions first: "how many crews do I have left" is about the round, not placement.
    if any(w in q for w in ("how are we doing", "score", "time left", "how long is left", "how much time",
                            "minutes left", "resources", "left to", "crews left", "do we have left",
                            "do i have left", "round")):
        out = await tools.call("get_situation", {})
        return Answer(_round_line(out["round"]), ["get_situation"], [out], "rules")

    if "wind" in q:
        direction, speed = _wind_direction(q), _wind_speed(q)
        if direction or speed is not None:
            frm = direction or tools._wind(tools.e.fire.wind)["from"]
            out = await tools.call("forecast_whatif", {"wind_from": frm, "wind_speed_ms": speed})
            if "error" in out:
                return Answer(f"I can't run that forecast: {out['error']}.", ["forecast_whatif"], [out], "rules")
            rows = sorted(out["towns"], key=lambda r: r["fire_reaches_within_60_min"]["simulations"], reverse=True)
            top = rows[0]
            wind = f"wind from the {frm}" + (f" at {out['hypothetical_wind']['speed_ms']:g} meters per second"
                                             if speed is not None else "")
            if top["fire_reaches_within_60_min"]["simulations"] == 0:
                text = f"With {wind}, no town is reached within the hour in any simulation."
            else:
                text = (f"With {wind}, {top['town']} is most at risk: fire reaches it within the hour in "
                        f"{_reach_phrase(top)} simulations, against "
                        f"{_reach_phrase(top, 'current_forecast_reaches_within_60_min')} now.")
            return Answer(text, ["forecast_whatif"], [out], "rules")

    if any(w in q for w in ("crew", "where", "place", "deploy", "put")):
        if place and any(w in q for w in ("crew", "put", "place", "deploy")) and "where" not in q:
            out = await tools.call("evaluate_placement", {"place": place, "x": None, "y": None})
            if "error" in out:
                return Answer(f"I can't test that spot: {out['error']}.", ["evaluate_placement"], [out], "rules")
            at = out["placement"]["at"]
            if out["keeps_fire_out_of"]:
                k = max(out["keeps_fire_out_of"], key=lambda e: e["simulations"])
                text = f"A crew at {at} keeps the fire out of {k['town']} in {k['simulations']} of {k['of']} simulations."
            elif out["less_of_town_burns"]:
                k = out["less_of_town_burns"][0]
                text = f"A crew at {at} shields {k['town']}: about {k['percent']} percent less of it burns in the next hour."
            elif out["helps"]:
                text = f"A crew at {at} holds back about {out['acres_saved_within_60_min']} acres over the next hour."
            else:
                text = f"A crew at {at} makes little difference over the next hour."
            return Answer(text, ["evaluate_placement"], [out], "rules")
        out = await tools.call("get_situation", {})
        if out["recommendations"]:
            return Answer(out["recommendations"][0], ["get_situation"], [out], "rules")
        return Answer("No crew placement clearly helps right now.", ["get_situation"], [out], "rules")

    if any(w in q for w in ("route", "evacuat", "road", "bus", "way out", "get out")):
        out = await tools.call("get_routes", {})
        town = _named(q, town_names)
        mine = next((r for r in out["routes"] if r["for"] == town), None) if town else None
        if mine is not None:
            if mine["status"] == "cut":
                text = f"{town} has no safe way out right now."
            else:
                text = (f"{town}'s route to {mine['exit']} is {mine['status']}, "
                        f"about {round(mine['drive_minutes'])} minutes' drive.")
            return Answer(text, ["get_routes"], [out], "rules")
        bad = [r for r in out["routes"] if r["status"] != "clear"]
        if not bad:
            text = "Every evacuation route is clear right now."
        else:
            parts = [f"{r['for']}'s route is {'cut' if r['status'] == 'cut' else 'risky'}" for r in bad[:2]]
            text = " and ".join(parts) + ("; the others are clear." if len(bad) < len(out["routes"]) else ".")
        return Answer(text, ["get_routes"], [out], "rules")

    out = await tools.call("get_situation", {})
    if not out["fire"]["active"]:
        return Answer("There's no active fire right now.", ["get_situation"], [out], "rules")
    if "acre" in q or "how big" in q or "burned" in q:
        f = out["fire"]
        text = f"About {f['burned_acres']} acres have burned, and {f['burning_acres']} are burning now."
        return Answer(text, ["get_situation"], [out], "rules")
    rows = [t for t in out["towns"] if "fire_reaches_within_30_min" in t]
    town = _named(q, town_names)
    if town:
        row = next((t for t in rows if t["town"] == town), None)
        if row is not None:
            return Answer(_town_line(row), ["get_situation"], [out], "rules")
    # The most useful answer is the next town in line, not one already burning.
    ahead = [t for t in rows if not t.get("fire_inside_town_now")]
    ahead.sort(key=lambda t: (t["fire_reaches_within_30_min"]["simulations"],
                              t["fire_reaches_within_60_min"]["simulations"]), reverse=True)
    burning = [t["town"] for t in rows if t.get("fire_inside_town_now")]
    if ahead and ahead[0]["fire_reaches_within_60_min"]["simulations"] > 0:
        text = f"{ahead[0]['town']} is most threatened. {_town_line(ahead[0])}"
    elif burning:
        text = f"Fire is inside {' and '.join(burning[:2])}, and no other town is reached within the hour."
    else:
        text = f"About {out['fire']['burned_acres']} acres have burned, and no town is threatened within the hour."
    return Answer(text, ["get_situation"], [out], "rules")
