"""Grounding guard: the commander never says a number the simulation didn't give it.

Every number in an answer must match a number from this turn's tool
results (values, or numbers inside keys like "within_30_min"), or one the
asker said. Rounding the way people speak is fine: "about 230 acres" for
227, "about 200" for 231. So is turning a count into a percentage
("24 of 32" as "75 percent"). Anything else is ungrounded.

SentenceGate applies this sentence by sentence while an answer streams, so
streaming consumers only ever receive sentences that passed.
"""

import math
import re
from collections.abc import Callable, Iterable

_NUMBER = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?")
_ONES = {
    "zero": 0, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19,
}  # "one" is left out: "one of the routes" isn't a figure
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
_WORD_NUMBER = re.compile(
    r"\b(?:(" + "|".join(_TENS) + r")(?:[- ](" + "|".join(k for k in _ONES if _ONES[k] < 10) + r"))?|("
    + "|".join(_ONES) + r"))\b",
    re.I,
)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def numbers_in_text(text: str) -> list[float]:
    """Numbers as written in digits ("1,200", "16.5") or words ("twenty-four")."""
    out = [float(m.group().replace(",", "")) for m in _NUMBER.finditer(text)]
    for m in _WORD_NUMBER.finditer(text):
        tens, unit, ones = m.groups()
        if tens:
            out.append(_TENS[tens.lower()] + (_ONES[unit.lower()] if unit else 0))
        else:
            out.append(_ONES[ones.lower()])
    return out


def allowed_numbers(tool_results: Iterable, question: str = "") -> set[float]:
    """Every number the answer may use: tool values, numbers in tool keys,
    count-to-percent conversions, and the asker's own numbers."""
    found: set[float] = set(numbers_in_text(question))

    def walk(obj):
        if isinstance(obj, bool) or obj is None:
            return
        if isinstance(obj, (int, float)):
            found.add(float(obj))
        elif isinstance(obj, str):
            found.update(numbers_in_text(obj))
        elif isinstance(obj, dict):
            if isinstance(obj.get("simulations"), int) and obj.get("of"):
                found.add(float(round(100 * obj["simulations"] / obj["of"])))
            for k, v in obj.items():
                found.update(float(n) for n in re.findall(r"\d+", str(k)))
                walk(v)
        elif isinstance(obj, (list, tuple)):
            for v in obj:
                walk(v)

    walk(list(tool_results))
    return found


def _round_sig(x: float, sig: int) -> float:
    if x == 0:
        return 0.0
    return round(x, sig - 1 - int(math.floor(math.log10(abs(x)))))


def is_grounded(n: float, allowed: set[float]) -> bool:
    for v in allowed:
        if abs(n - v) <= 0.5:
            return True
        if abs(v) >= 10 and any(_round_sig(v, s) == n for s in (1, 2)):
            return True
    return False


def ungrounded(text: str, allowed: set[float]) -> list[float]:
    return [n for n in numbers_in_text(text) if not is_grounded(n, allowed)]


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_END.split(text) if s.strip()]


class SentenceGate:
    """Buffers streamed text and releases whole sentences whose numbers are
    grounded. After the first bad sentence it releases nothing more, and
    `failed` says so (the caller then falls back)."""

    def __init__(self, allowed: Callable[[], set[float]], emit: Callable[[str], None]) -> None:
        self._allowed = allowed  # read at release time: tool results keep arriving
        self._emit = emit
        self._buf = ""
        self.failed = False

    def feed(self, chunk: str) -> None:
        self._buf += chunk
        parts = _SENTENCE_END.split(self._buf)
        for sentence in parts[:-1]:
            self._release(sentence)
        self._buf = parts[-1]

    def flush(self) -> None:
        if self._buf.strip():
            self._release(self._buf)
        self._buf = ""

    def _release(self, sentence: str) -> None:
        sentence = sentence.strip()
        if not sentence or self.failed:
            return
        if ungrounded(sentence, self._allowed()):
            self.failed = True
            return
        self._emit(sentence)
