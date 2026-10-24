"""Speaking the commander's words (PLAN.md, Incident commander; #40).

Voice is off by default: the console transcript is the main channel, and
voice is a toggle for the demo. Two ways to speak:

- "console": the engine sends commander_speech and the console window
  speaks it with the Web Speech API (app/src/shared/speech.ts).
- "mac": the engine speaks with macOS `say`, for when the webview's voices
  are poor or missing. MacVoice below.

Both get text from speakable(), so names and units read naturally either way.

Interruption rules, the same in both places: a new answer interrupts
anything; a briefing waits for an answer to finish; at most one briefing
waits at a time (the newest), because stale news is worse than none.
"""

import asyncio
import logging
import re
import shutil

log = logging.getLogger("voice")

_REPLACEMENTS = [
    (re.compile(r"\bHwy\b"), "Highway"),
    (re.compile(r"\bRd\b"), "Road"),
    (re.compile(r"\bm/s\b"), "meters per second"),
    (re.compile(r"\bmph\b"), "miles per hour"),
    (re.compile(r"(\d)\s*%"), r"\1 percent"),
    (re.compile(r"~\s*"), "about "),
    (re.compile(r"\bCA (\d+)"), r"State Route \1"),
]
_PAREN_ROUTE = re.compile(r"(\w[\w .'-]*?) \(([^)]+)\)")


def speakable(text: str) -> str:
    """'Evacuate toward Oroville (Hwy 70).' -> 'Evacuate toward Oroville via Highway 70.'"""
    for pattern, repl in _REPLACEMENTS:
        text = pattern.sub(repl, text)
    return _PAREN_ROUTE.sub(r"\1 via \2", text)


class MacVoice:
    """Speaks with macOS `say` as a subprocess, so speaking never blocks the
    engine, and can be cut off mid-sentence."""

    RATE_WPM = 200

    def __init__(self) -> None:
        self.available = shutil.which("say") is not None
        self._proc: asyncio.subprocess.Process | None = None
        self._utterance: str | None = None
        self._kind: str | None = None
        self._queue: list[str] = []  # the rest of the current utterance
        self._waiting: tuple[str, str] | None = None  # (utterance, text) of one briefing
        self._task: asyncio.Task | None = None

    def speak(self, utterance: str, kind: str, text: str) -> None:
        if not self.available:
            return
        if kind == "answer":
            if utterance != self._utterance:
                self.interrupt()
                self._utterance, self._kind = utterance, kind
            self._queue.append(text)
        elif self._busy() and (self._kind == "answer" or self._utterance == utterance):
            self._waiting = (utterance, text)
        else:
            self.interrupt()
            self._utterance, self._kind = utterance, kind
            self._queue.append(text)
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    def interrupt(self) -> None:
        self._queue.clear()
        self._utterance = self._kind = None
        if self._proc is not None and self._proc.returncode is None:
            self._proc.terminate()

    def _busy(self) -> bool:
        return bool(self._queue) or (self._proc is not None and self._proc.returncode is None)

    async def _run(self) -> None:
        while True:
            if not self._queue and self._waiting:
                self._utterance, text = self._waiting
                self._kind, self._waiting = "briefing", None
                self._queue.append(text)
            if not self._queue:
                self._utterance = self._kind = None
                return
            text = self._queue.pop(0)
            try:
                self._proc = await asyncio.create_subprocess_exec(
                    "say", "-r", str(self.RATE_WPM), text,
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                )
                await self._proc.wait()
            except OSError as err:
                log.warning("say failed: %s", err)
                self.available = False
                return
