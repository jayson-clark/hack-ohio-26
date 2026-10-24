---
name: commander-voice
description: Set up, try, or debug the incident commander (Claude answers, templated briefings, grounding guard), its voice (text-to-speech) and push-to-talk (speech-to-text). Use when asked to run or test the commander, add an API key, change the commander's model, measure its latency, turn on voice, or debug push-to-talk.
---

Code: `engine/commander/` (`tools.py` simulation tools, `agent.py` Claude loop and template fallback, `guard.py` grounding, `briefings.py` unprompted briefings, `voice.py` TTS, `listen.py` STT). Design: `PLAN.md` → Incident commander.

## Answers (LLM)
- Put `ANTHROPIC_API_KEY` in the root `.env`. `make engine` exports it. Without a key, the commander answers from templates, and briefings never need one.
- `COMMANDER_MODEL` (default `claude-haiku-5-5`, about a tenth of a cent per question) and `COMMANDER_EFFORT` (default `low`) are also read from `.env`. Haiku has no server-side refusal fallback, so a refusal falls back to the templates. Opus and Sonnet get `fallbacks="default"`.
- Try one question without the UI: `cd engine && uv run python -m commander.ask "What if the wind shifts west?"`. It prints LLM or rules, grounded or not, the tools used, time to first sentence, and total time.
- Measure before changing the model or effort: `cd engine && uv run python -m commander.eval.run --effort low --out report.md`. That's 20 scripted questions, so with a key it makes real API calls.
- An answer with `grounded: false` never happens on purpose. The guard retries once, then falls back to templates. If answers keep falling back, check the engine log for `ungrounded numbers`.

## Voice (text-to-speech)
- Off by default. Use the console header toggle: **Console** (Web Speech in that window; browsers only allow speech after a click, and the toggle click counts) or **Mac say** (the engine runs macOS `say`).
- Speech text goes through `voice.speakable()` ("Oroville via Highway 70"). Add new road or unit spellings there.

## Push-to-talk (speech-to-text)
- Optional extra (it pulls in mlx-whisper and PyTorch): `cd engine && uv sync --extra voice`, then run the engine with `uv run --extra voice server.py`. A plain `make engine` won't have it, and the "Hold to talk" button stays disabled.
- The first run downloads `mlx-community/whisper-small.en-mlx` (~480 MB) to `~/.cache/huggingface`. Do that before the venue.
- **Microphone permission:** the first press makes macOS ask whether the app that launched the engine (Terminal, iTerm, or the Tauri app) may use the mic. If you said no, enable it in System Settings → Privacy & Security → Microphone. The UI shows "can't open the microphone".
- Hold the button, or hold Space, in the console. Releasing it transcribes (~0.1 s on Apple silicon), shows what was heard, and asks the commander.
- Test without speaking: `say -o q.wav --file-format=WAVE --data-format=LEI16@16000 "How long until the fire reaches Pulga?"`, then feed the samples to `Listener.transcribe` (see `engine/tests/test_listen.py`).
- Place names misheard? The prompt is built from `towns.json` towns and exit roads (`listen.vocabulary_prompt`). Keep it a natural sentence, because a bare list pushes Whisper into Title Case.
