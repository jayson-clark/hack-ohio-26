"""The commander's question answering, with a fake Anthropic client (no network)."""

import asyncio
import json
from types import SimpleNamespace as NS

import pytest

import commander.agent as agent_mod
from commander.agent import Commander, rule_based_answer
from commander.tools import CommanderTools
from test_commander_tools import burning_engine


def text_msg(text, stop="end_turn"):
    return NS(stop_reason=stop, content=[NS(type="text", text=text)],
              usage=NS(input_tokens=10, cache_read_input_tokens=0, output_tokens=5))


def tool_msg(name, args, tool_id="tu_1"):
    return NS(stop_reason="tool_use", content=[NS(type="tool_use", id=tool_id, name=name, input=args)],
              usage=NS(input_tokens=10, cache_read_input_tokens=0, output_tokens=5))


class FakeStream:
    def __init__(self, msg, delay=0.0, error=None):
        self.msg, self.delay, self.error = msg, delay, error

    async def __aenter__(self):
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return self

    async def __aexit__(self, *exc):
        return False

    @property
    def text_stream(self):
        async def gen():
            for block in self.msg.content:
                if block.type == "text":
                    for word in block.text.split(" "):
                        yield word + " "
        return gen()

    async def get_final_message(self):
        return self.msg


class FakeClient:
    """Plays back scripted responses and records every request."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []
        self.beta = NS(messages=NS(stream=self._stream))

    def _stream(self, **kwargs):
        self.requests.append(json.loads(json.dumps(kwargs, default=lambda o: vars(o))))
        nxt = self.responses.pop(0)
        return nxt if isinstance(nxt, FakeStream) else FakeStream(nxt)


@pytest.fixture
def engine():
    e = burning_engine(40)
    yield e
    e.forecaster.shutdown()
    e.long_forecaster.shutdown()
    e.recommender.shutdown()


def run(coro):
    return asyncio.run(coro)


def test_tool_loop_and_request_shape(engine):
    client = FakeClient(tool_msg("get_situation", {}), text_msg("Pulga is threatened in 32 of 32 simulations."))
    cmd = Commander(CommanderTools(engine), client=client, model="claude-opus-5-5")
    sentences = []
    ans = run(cmd.answer("How bad is it?", on_sentence=sentences.append))
    assert ans.source == "llm" and ans.text == "Pulga is threatened in 32 of 32 simulations."
    assert ans.grounded and ans.tools_used == ["get_situation"] and "towns" in ans.tool_results[0]
    assert sentences == [ans.text]

    first, second = client.requests
    assert first["model"] == "claude-opus-5-5" and first["fallbacks"] == "default"
    assert first["betas"] == ["server-side-fallback-2026-07-01"]
    assert first["output_config"] == {"effort": "low"}
    assert "tool_choice" not in first and "thinking" not in first
    assert all(t["strict"] for t in first["tools"])
    assert first["system"][0]["cache_control"] == {"type": "ephemeral"}
    # The second request replays the assistant turn unchanged, then the tool result.
    assert second["messages"][1]["role"] == "assistant"
    [result] = second["messages"][2]["content"]
    assert result["type"] == "tool_result" and result["tool_use_id"] == "tu_1" and not result["is_error"]
    assert "towns" in json.loads(result["content"])


def test_follow_ups_carry_plain_text_history_only(engine):
    client = FakeClient(text_msg("First answer."), text_msg("Second answer."))
    cmd = Commander(CommanderTools(engine), client=client)
    run(cmd.answer("First question?"))
    run(cmd.answer("And then?"))
    msgs = client.requests[1]["messages"]
    assert msgs == [
        {"role": "user", "content": "First question?"},
        {"role": "assistant", "content": "First answer."},
        {"role": "user", "content": "And then?"},
    ]


@pytest.mark.parametrize("trouble", [
    "refusal",
    "error",
    "timeout",
])
def test_llm_trouble_falls_back_to_rules(engine, monkeypatch, trouble):
    monkeypatch.setattr(agent_mod, "ANSWER_TIMEOUT_S", 0.2)
    stream = {
        "refusal": FakeStream(text_msg("", stop="refusal")),
        "error": FakeStream(text_msg("x"), error=RuntimeError("network down")),
        "timeout": FakeStream(text_msg("too late"), delay=1.0),
    }[trouble]
    cmd = Commander(CommanderTools(engine), client=FakeClient(stream))
    ans = run(cmd.answer("Which town is in danger?"))
    assert ans.source == "rules" and ans.grounded
    assert any(t.name in ans.text for t in engine.towns)  # the live fire isn't seeded, so which town varies


class StallingStream(FakeStream):
    """Streams its first sentence, then hangs."""

    @property
    def text_stream(self):
        async def gen():
            first, _ = self.msg.content[0].text.split(". ", 1)
            for word in (first + ". ").split(" "):
                yield word + " "
            await asyncio.sleep(1.0)
        return gen()


@pytest.mark.parametrize("listening", [True, False])
def test_timeout_mid_answer_keeps_only_what_a_listener_heard(engine, monkeypatch, listening):
    monkeypatch.setattr(agent_mod, "ANSWER_TIMEOUT_S", 0.2)
    first = "Pulga is threatened in 32 of 32 simulations."
    stream = StallingStream(text_msg(first + " Concow is next."))
    cmd = Commander(CommanderTools(engine), client=FakeClient(tool_msg("get_situation", {}), stream))
    said = []
    ans = run(cmd.answer("Which town is in danger?", on_sentence=said.append if listening else None))
    if listening:
        assert said == [first] and ans.text == first  # already out; finish there
    else:
        assert ans.source == "rules"  # half an answer is never sent as if it were whole (#153)


def test_no_key_means_rules(engine, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    cmd = Commander(CommanderTools(engine))
    assert cmd.client is None
    assert run(cmd.answer("Status?")).source == "rules"


def test_rule_based_answers_pick_the_right_tool(engine):
    async def go():
        await engine.recommender.warm()
        tools = CommanderTools(engine)
        wind = await rule_based_answer(tools, "What if the wind shifts to come from the west?")
        assert wind.tools_used == ["forecast_whatif"] and "wind from the west" in wind.text
        routes = await rule_based_answer(tools, "Are the evacuation routes OK?")
        assert routes.tools_used == ["get_routes"]
        status = await rule_based_answer(tools, "How bad is it?")
        assert status.tools_used == ["get_situation"] and any(t.name in status.text for t in engine.towns)

    run(go())


def test_engine_answers_and_a_newer_question_cancels_the_older(engine, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    sent = []
    monkeypatch.setattr("server.broadcast", lambda clients, msg: sent.append(json.loads(msg)))

    async def go():
        engine.ask("First?")
        first = engine._query_task
        engine.ask("How bad is it?")
        await asyncio.gather(first, engine._query_task, return_exceptions=True)
        assert first.cancelled()

    run(go())
    answers = [m for m in sent if m["type"] == "commander_message"]
    assert len(answers) == 1 and answers[0]["kind"] == "answer" and answers[0]["grounded"] is True


def test_default_model_is_haiku_without_server_fallbacks(engine, monkeypatch):
    monkeypatch.delenv("COMMANDER_MODEL", raising=False)
    client = FakeClient(text_msg("No round is running."))
    cmd = Commander(CommanderTools(engine), client=client)
    assert cmd.model == "claude-haiku-5-5"
    run(cmd.answer("Status?"))
    [req] = client.requests
    assert req["model"] == "claude-haiku-5-5" and req["max_tokens"] == 1500
    assert "fallbacks" not in req and "betas" not in req  # Haiku has no server-side fallback
    assert req["output_config"] == {"effort": "low"}


def test_system_prompt_names_the_loaded_scenario(engine):
    """The commander is told where the fire is from the scenario, not a
    hard-coded Paradise (#157), and nothing says answers are spoken (#140)."""
    def system_text(cmd):
        return cmd.client.requests[-1]["system"][0]["text"]

    cmd = Commander(CommanderTools(engine), client=FakeClient(text_msg("Pulga is threatened.")))
    run(cmd.answer("Status?"))
    assert "Paradise" in system_text(cmd) and "spoken back" not in system_text(cmd)
    engine.switch_scenario("marshall")
    cmd = Commander(engine.tools, client=FakeClient(text_msg("Superior is threatened.")))
    run(cmd.answer("Status?"))
    text = system_text(cmd)
    assert "Marshall" in text and "Louisville" in text and "Paradise" not in text


def test_setting_falls_back_to_the_towns():
    from types import SimpleNamespace

    from commander.agent import scenario_setting

    e = SimpleNamespace(game=SimpleNamespace(config={}), towns=[SimpleNamespace(name="A"), SimpleNamespace(name="B")],
                        scenario=SimpleNamespace(name="x"))
    assert scenario_setting(e) == "the country around A and B"
