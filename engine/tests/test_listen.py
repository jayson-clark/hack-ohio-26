"""Push-to-talk: prompt, engine flow with a fake mic, and (if installed) real transcription."""

import asyncio
import json
import shutil
import subprocess
import wave
from pathlib import Path

import numpy as np
import pytest

from commander.listen import MODEL, RATE, Listener, vocabulary_prompt
from test_commander_agent import engine  # noqa: F401  (fixture)


def test_vocabulary_prompt_is_a_sentence_with_every_name():
    p = vocabulary_prompt(["Paradise", "Concow", "Pulga"], ["the Skyway", "Highway 70"])
    assert p == ("The fire is near Paradise, Concow and Pulga. Evacuate by the Skyway and Highway 70. "
                 "Send a crew, a water drop or a firebreak.")


def test_engine_prompt_uses_scenario_towns_and_exit_roads(engine):  # noqa: F811
    assert "Magalia" in engine.listener.prompt and "the Skyway" in engine.listener.prompt
    assert "Highway 70" in engine.listener.prompt


@pytest.fixture
def sent(monkeypatch):
    out = []
    monkeypatch.setattr("server.broadcast", lambda clients, msg: out.append(json.loads(msg)))
    return out


class FakeListener:
    available, reason = True, ""

    def __init__(self, heard):
        self.heard, self.recording = heard, False

    def start(self):
        self.recording = True

    def stop(self):
        self.recording = False
        return np.zeros(RATE * 2, np.float32)

    def transcribe(self, audio):
        return self.heard


def test_push_to_talk_transcribes_and_asks(engine, sent, monkeypatch):  # noqa: F811
    asked = []
    engine.listener = FakeListener("Would a crew near Magalia keep the fire out?")
    monkeypatch.setattr(engine, "ask", asked.append)

    async def go():
        engine.ptt_start()
        assert engine.listener.recording
        engine.ptt_stop()
        await asyncio.sleep(0.05)

    asyncio.run(go())
    assert [m for m in sent if m["type"] == "transcript"] == [
        {"type": "transcript", "text": "Would a crew near Magalia keep the fire out?", "error": None}
    ]
    assert asked == ["Would a crew near Magalia keep the fire out?"]


def test_nothing_heard_says_so_and_asks_nothing(engine, sent, monkeypatch):  # noqa: F811
    asked = []
    engine.listener = FakeListener("")
    monkeypatch.setattr(engine, "ask", asked.append)

    async def go():
        engine.ptt_start()
        engine.ptt_stop()
        await asyncio.sleep(0.05)

    asyncio.run(go())
    [t] = [m for m in sent if m["type"] == "transcript"]
    assert t["error"] == "didn't catch that" and asked == []


def test_without_the_voice_extra_ptt_explains(engine, sent):  # noqa: F811
    engine.listener.available = False
    engine.listener.reason = "speech-to-text isn't installed"
    engine.ptt_start()
    [t] = [m for m in sent if m["type"] == "transcript"]
    assert t == {"type": "transcript", "text": "", "error": "speech-to-text isn't installed"}


def test_too_short_audio_is_not_transcribed():
    assert Listener("").transcribe(np.zeros(RATE // 10, np.float32)) == ""


def _model_cached() -> bool:
    return (Path.home() / ".cache/huggingface/hub" / ("models--" + MODEL.replace("/", "--"))).exists()


@pytest.mark.skipif(shutil.which("say") is None or not _model_cached(), reason="needs macOS say and the cached model")
def test_real_transcription_gets_place_names_right(tmp_path):
    pytest.importorskip("mlx_whisper")
    wav = tmp_path / "q.wav"
    subprocess.run(["say", "-o", str(wav), "--file-format=WAVE", "--data-format=LEI16@16000",
                    "How long until the fire reaches Pulga near Concow?"], check=True)
    with wave.open(str(wav)) as w:
        audio = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768.0
    listener = Listener(vocabulary_prompt(["Paradise", "Magalia", "Concow", "Pulga"], ["the Skyway"]))
    text = listener.transcribe(audio)
    assert "Pulga" in text and "Concow" in text, text


def test_speakable_reads_names_and_units():
    """The STT vocabulary prompt uses spoken forms of road and exit names."""
    from commander.listen import speakable

    assert speakable("Evacuate toward Oroville (Hwy 70).") == "Evacuate toward Oroville via Highway 70."
    assert speakable("Go to Chico (Skyway) or Oroville (Clark Rd).") == "Go to Chico via Skyway or Oroville via Clark Road."
    assert speakable("Wind at 12 m/s, about 15% less burns.") == "Wind at 12 meters per second, about 15 percent less burns."
