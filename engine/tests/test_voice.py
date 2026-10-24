"""Voice: speakable text, routing by mode, and the `say` queue rules."""

import asyncio
import json

import pytest

import commander.voice as voice_mod
from commander.voice import MacVoice, speakable
from protocol import CommanderKind, VoiceMode
from test_commander_agent import engine  # noqa: F401  (fixture)


def test_speakable_reads_names_and_units():
    assert speakable("Evacuate toward Oroville (Hwy 70).") == "Evacuate toward Oroville via Highway 70."
    assert speakable("Go to Chico (Skyway) or Oroville (Clark Rd).") == "Go to Chico via Skyway or Oroville via Clark Road."
    assert speakable("Wind at 12 m/s, about 15% less burns.") == "Wind at 12 meters per second, about 15 percent less burns."


@pytest.fixture
def sent(monkeypatch):
    out = []
    monkeypatch.setattr("server.broadcast", lambda clients, msg: out.append(json.loads(msg)))
    return out


def test_console_mode_streams_answer_sentences_then_the_transcript(engine, sent, monkeypatch):  # noqa: F811
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    engine.voice_mode = VoiceMode.CONSOLE

    async def go():
        engine.ask("Is Paradise's evacuation route safe?")
        await engine._query_task

    asyncio.run(go())
    speech = [m for m in sent if m["type"] == "commander_speech"]
    [answer] = [m for m in sent if m["type"] == "commander_message"]
    assert speech and len({m["utterance"] for m in speech}) == 1
    assert all(m["kind"] == "answer" and not m["urgent"] for m in speech)
    assert "via Skyway" in " ".join(m["text"] for m in speech)  # speakable, unlike the transcript
    assert "(Skyway)" in answer["text"]


def test_voice_off_sends_no_speech_and_mac_mode_uses_say(engine, sent, monkeypatch):  # noqa: F811
    calls = []
    monkeypatch.setattr(engine.mac_voice, "speak", lambda *a: calls.append(a))
    engine.voice_mode = VoiceMode.OFF
    engine.speak("b1", CommanderKind.BRIEFING, "Pulga is threatened.")
    assert sent == [] and calls == []
    engine.voice_mode = VoiceMode.MAC
    engine.speak("b2", CommanderKind.BRIEFING, "Go to Oroville (Hwy 70).")
    assert sent == [] and calls == [("b2", "briefing", "Go to Oroville via Highway 70.")]


class FakeProc:
    def __init__(self, text, log, seconds):
        self.text, self.log, self.returncode = text, log, None
        self._done = asyncio.Event()
        asyncio.get_running_loop().call_later(seconds, self._finish)

    def _finish(self):
        if self.returncode is None:
            self.returncode = 0
            self.log.append(("done", self.text))
            self._done.set()

    def terminate(self):
        if self.returncode is None:
            self.returncode = -15
            self.log.append(("cut", self.text))
            self._done.set()

    async def wait(self):
        await self._done.wait()
        return self.returncode


@pytest.fixture
def say_log(monkeypatch):
    log = []

    async def fake_exec(*args, **kwargs):
        return FakeProc(args[-1], log, 0.05)

    monkeypatch.setattr(voice_mod.asyncio, "create_subprocess_exec", fake_exec)
    return log


def run_voice(steps):
    async def go():
        v = MacVoice()
        v.available = True
        for delay, args in steps:
            await asyncio.sleep(delay)
            v.speak(*args)
        await asyncio.sleep(0.4)

    asyncio.run(go())


def test_new_answer_cuts_off_a_briefing(say_log):
    run_voice([(0, ("b1", "briefing", "Pulga is threatened.")), (0.02, ("a1", "answer", "Concow is clear."))])
    assert say_log == [("cut", "Pulga is threatened."), ("done", "Concow is clear.")]


def test_briefings_wait_for_an_answer_and_only_the_newest_waits(say_log):
    run_voice([
        (0, ("a1", "answer", "First sentence.")),
        (0, ("a1", "answer", "Second sentence.")),
        (0.01, ("b1", "briefing", "Old news.")),
        (0.01, ("b2", "briefing", "New news.")),
    ])
    assert say_log == [("done", "First sentence."), ("done", "Second sentence."), ("done", "New news.")]
