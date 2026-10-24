"""Push-to-talk speech-to-text for the commander (#41).

The engine owns the microphone, like it owns the camera (PLAN.md): the
console sends ptt_start / ptt_stop, the engine records between them,
transcribes locally with Whisper (mlx-whisper, small.en, on the Apple
silicon GPU), and asks the commander the transcript. Local means venue
Wi-Fi can't break it. A 2-second question takes about 0.1 s to transcribe
on an M2 once the model is loaded.

Needs the optional voice extra (`cd engine && uv sync --extra voice`). The
first run downloads the model (~480 MB) to ~/.cache/huggingface. Without
the extra, `available` is False and push-to-talk reports that instead.

Place names are the likeliest thing to mishear ("Kankao" for Concow), so
the transcriber gets a short natural sentence that uses the scenario's
names as a prompt.
"""

import logging
import threading

import numpy as np

log = logging.getLogger("listen")

MODEL = "mlx-community/whisper-small.en-mlx"
RATE = 16000
MIN_SECONDS = 0.3  # shorter than this is a slip of the button, not a question
MAX_SECONDS = 15.0


def vocabulary_prompt(towns: list[str], roads: list[str]) -> str:
    """A sentence that uses every name, which steers Whisper's spelling
    without pushing it into Title Case the way a bare list does."""
    def join(names):
        return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]

    parts = []
    if towns:
        parts.append(f"The fire is near {join(towns)}.")
    if roads:
        parts.append(f"Evacuate by {join(roads)}.")
    parts.append("Send a crew, a water drop or a firebreak.")
    return " ".join(parts)


class Listener:
    def __init__(self, prompt: str) -> None:
        self.prompt = prompt
        self._chunks: list[np.ndarray] = []
        self._lock = threading.Lock()
        self._stream = None
        try:
            import mlx_whisper  # noqa: F401
            import sounddevice  # noqa: F401

            self.available = True
            self.reason = ""
        except ImportError:
            self.available = False
            self.reason = "speech-to-text isn't installed (cd engine && uv sync --extra voice)"

    @property
    def recording(self) -> bool:
        return self._stream is not None

    def start(self) -> None:
        """Open the mic and start buffering. Raises if the mic can't be opened."""
        import sounddevice as sd

        self.stop()
        with self._lock:
            self._chunks = []
        self._stream = sd.InputStream(samplerate=RATE, channels=1, dtype="float32", callback=self._on_audio)
        self._stream.start()

    def _on_audio(self, data, frames, time_info, status) -> None:  # PortAudio's thread
        with self._lock:
            if sum(len(c) for c in self._chunks) < MAX_SECONDS * RATE:
                self._chunks.append(data[:, 0].copy())

    def stop(self) -> np.ndarray:
        """Close the mic and return what was recorded (float32 mono, 16 kHz)."""
        stream, self._stream = self._stream, None
        if stream is not None:
            stream.stop()
            stream.close()
        with self._lock:
            audio = np.concatenate(self._chunks) if self._chunks else np.zeros(0, np.float32)
            self._chunks = []
        return audio[: int(MAX_SECONDS * RATE)]

    def transcribe(self, audio: np.ndarray) -> str:
        """Blocking; call from a worker thread. Empty string for too-short audio."""
        if len(audio) < MIN_SECONDS * RATE:
            return ""
        import mlx_whisper

        result = mlx_whisper.transcribe(
            audio.astype(np.float32), path_or_hf_repo=MODEL, language="en",
            initial_prompt=self.prompt, condition_on_previous_text=False,
        )
        return result["text"].strip()

    def warm(self) -> None:
        """Load the model now (blocking; run in a thread) so the first question is fast."""
        if self.available:
            try:
                self.transcribe(np.zeros(RATE, np.float32))
            except Exception as err:  # e.g. no network for the first download
                log.warning("speech-to-text warm-up failed: %s", err)
