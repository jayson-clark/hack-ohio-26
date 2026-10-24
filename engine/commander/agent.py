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
from collections.abc import Awaitable, Callable

from commander.tools import COMPASS, TOOL_SPECS, CommanderTools

log = logging.getLogger("commander")

DEFAULT_MODEL = "claude-opus-5-5"
# Short spoken answers: low effort keeps latency down. Thinking can't be
# turned off on this model, so effort is the latency lever.
EFFORT = "low"
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
- If a tool returns an error, or the data doesn't answer the question, say so briefly instead of guessing.
- For "what if the wind..." questions, use forecast_whatif and compare with the current forecast.
- For "where should crews go" questions, use get_situation (it includes the current recommendations) or \
evaluate_placement for a specific spot.
- For evacuation questions, use get_routes."""

TextCallback = Callable[[str], Awaitable[None] | None]


def has_credentials() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


TOOLS = [{**t, "strict": True} for t in TOOL_SPECS]
# Requests render tools, then system, then messages. Both of the first two are
# identical on every call, so a breakpoint at the end of the system prompt
# caches them together. Nothing volatile (time, tick, state) goes in either.
SYSTEM_BLOCKS = [{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}]


class Answer:
    def __init__(self, text: str, tools_used: list[str], tool_results: list[dict], source: str) -> None:
        self.text = text
        self.tools_used = tools_used
        self.tool_results = tool_results  # for the grounding guard
        self.source = source  # "llm" or "rules"


class Commander:
    def __init__(self, tools: CommanderTools, client=None, model: str | None = None) -> None:
        self.tools = tools
        self.model = model or os.environ.get("COMMANDER_MODEL") or DEFAULT_MODEL
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

    async def answer(self, question: str, on_text: TextCallback | None = None) -> Answer:
        """Answer a question with the LLM if it can, else from rules. Never raises."""
        result = None
        if self.client is not None:
            try:
                result = await asyncio.wait_for(self._llm_answer(question, on_text), ANSWER_TIMEOUT_S)
            except asyncio.TimeoutError:
                log.warning("commander answer timed out; using rules")
            except asyncio.CancelledError:
                raise
            except Exception as err:  # network, auth, bad request: the demo keeps going
                log.warning("commander LLM failed (%s); using rules", err)
        if result is None:
            result = await rule_based_answer(self.tools, question)
        self.history.append((question, result.text))
        return result

    async def _llm_answer(self, question: str, on_text: TextCallback | None) -> Answer | None:
        messages: list[dict] = []
        for q, a in self.history:
            messages += [{"role": "user", "content": q}, {"role": "assistant", "content": a}]
        messages.append({"role": "user", "content": question})
        used, results = [], []
        for _ in range(MAX_TOOL_ROUNDS):
            async with self.client.beta.messages.stream(
                model=self.model,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_BLOCKS,
                tools=TOOLS,
                messages=messages,
                output_config={"effort": EFFORT},
                betas=[FALLBACK_BETA],
                fallbacks="default",
            ) as stream:
                async for text in stream.text_stream:
                    if on_text is not None:
                        r = on_text(text)
                        if r is not None:
                            await r
                msg = await stream.get_final_message()
            usage = msg.usage
            log.info("commander turn: stop=%s in=%s cached=%s out=%s", msg.stop_reason, usage.input_tokens,
                     usage.cache_read_input_tokens, usage.output_tokens)
            if msg.stop_reason == "refusal":
                log.warning("commander refused: %s", getattr(msg, "stop_details", None))
                return None
            tool_uses = [b for b in msg.content if b.type == "tool_use"]
            if not tool_uses:
                text = " ".join(b.text.strip() for b in msg.content if b.type == "text").strip()
                return Answer(text, used, results, "llm") if text else None
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


# --- Rule-based answers: no LLM, same tools ----------------------------------

def _wind_direction(q: str) -> str | None:
    words = re.findall(r"north-?east|north-?west|south-?east|south-?west|north|south|east|west", q.lower())
    if not words:
        return None
    w = words[0].replace("northeast", "north-east").replace("northwest", "north-west")
    w = w.replace("southeast", "south-east").replace("southwest", "south-west")
    return w if w in COMPASS else None


def _reach_phrase(row: dict, key: str = "fire_reaches_within_60_min") -> str:
    r = row[key]
    return f"{r['simulations']} of {r['of']}"


async def rule_based_answer(tools: CommanderTools, question: str) -> Answer:
    """A templated answer from the tools, for when the LLM isn't available."""
    q = question.lower()
    if "wind" in q and (direction := _wind_direction(q)):
        out = await tools.call("forecast_whatif", {"wind_from": direction, "wind_speed_ms": None})
        if "error" in out:
            return Answer(f"I can't run that forecast: {out['error']}.", ["forecast_whatif"], [out], "rules")
        rows = sorted(out["towns"], key=lambda r: r["fire_reaches_within_60_min"]["simulations"], reverse=True)
        top = rows[0]
        if top["fire_reaches_within_60_min"]["simulations"] == 0:
            text = f"With wind from the {direction}, no town is reached within the hour in any simulation."
        else:
            text = (f"With wind from the {direction}, {top['town']} is most at risk: fire reaches it within the hour "
                    f"in {_reach_phrase(top)} simulations, against {_reach_phrase(top, 'current_forecast_reaches_within_60_min')} now.")
        return Answer(text, ["forecast_whatif"], [out], "rules")
    if any(w in q for w in ("route", "evacuat", "road", "bus", "way out")):
        out = await tools.call("get_routes", {})
        bad = [r for r in out["routes"] if r["status"] != "clear"]
        if not bad:
            text = "Every evacuation route is clear right now."
        else:
            parts = [f"{r['for']}'s route is cut" if r["status"] == "cut" else f"{r['for']}'s route is risky"
                     for r in bad[:2]]
            text = " and ".join(parts) + "; the others are clear."
            text = text[0].upper() + text[1:]
        return Answer(text, ["get_routes"], [out], "rules")
    out = await tools.call("get_situation", {})
    if any(w in q for w in ("crew", "where", "place", "deploy", "put")):
        if out["recommendations"]:
            return Answer(out["recommendations"][0], ["get_situation"], [out], "rules")
        return Answer("No crew placement clearly helps right now.", ["get_situation"], [out], "rules")
    towns = [t for t in out["towns"] if "fire_reaches_within_30_min" in t]
    towns.sort(key=lambda t: t["fire_reaches_within_30_min"]["simulations"], reverse=True)
    if not out["fire"]["active"]:
        text = "There's no active fire right now."
    elif towns and towns[0]["fire_reaches_within_30_min"]["simulations"] > 0:
        t = towns[0]
        text = (f"{t['town']} is most threatened: fire reaches it within 30 minutes in "
                f"{_reach_phrase(t, 'fire_reaches_within_30_min')} simulations.")
    else:
        text = f"About {out['fire']['burned_acres']} acres have burned, and no town is threatened in the next half hour."
    return Answer(text, ["get_situation"], [out], "rules")
