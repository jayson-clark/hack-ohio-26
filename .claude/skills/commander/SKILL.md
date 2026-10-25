---
name: commander
description: Set up, try, or debug the incident commander (Claude answers, templated briefings, grounding guard, drafted orders and alerts). Use when asked to run or test the commander, add an API key, change the commander's model, or measure its latency.
---

Code: `engine/commander/` (`tools.py` simulation tools, `agent.py` Claude loop and template fallback, `guard.py` grounding, `briefings.py` unprompted briefings, `drafts.py` orders and alerts). Design: `PLAN.md` → Incident commander.

## Answers (LLM)
- Put `ANTHROPIC_API_KEY` in the root `.env`. `make engine` exports it. Without a key, the commander answers from templates, and briefings never need one.
- `COMMANDER_MODEL` (default `claude-haiku-5-5`, about a tenth of a cent per question) and `COMMANDER_EFFORT` (default `low`) are also read from `.env`. Haiku has no server-side refusal fallback, so a refusal falls back to the templates. Opus and Sonnet get `fallbacks="default"`.
- Try one question without the UI: `cd engine && uv run python -m commander.ask "What if the wind shifts west?"`. It prints LLM or rules, grounded or not, the tools used, time to first sentence, and total time.
- Measure before changing the model or effort: `cd engine && uv run python -m commander.eval.run --effort low --out report.md`. That's 20 scripted questions, so with a key it makes real API calls.
- The eval asks independent questions, so it can't catch follow-up problems. History keeps only question and answer text; without the system prompt's "don't revisit earlier answers" rule, follow-ups retract earlier figures as unsourced (#153). After a prompt change, also ask a chain of 3–4 follow-ups through one `Commander`, with no `on_sentence`, as the server does.
- An answer with `grounded: false` never happens on purpose. The guard retries once, then falls back to templates. If answers keep falling back, check the engine log for `ungrounded numbers`.

## Drafted orders and alerts (#132)
- `commander/drafts.py` (`DraftDesk`). Triggers: a dispatch "sent" event (`flush_dispatch`), `order_evacuation` (on or off), and `request_briefing`. The console shows them in Monitor under Decisions (`console/DispatchDrafts.tsx`).
- To try it: `make engine` (so `.env` loads the key), start a round, place a crew, order a town out. Unit orders show `source: llm` when Claude's rewrite passed, else `template`.
- A rewrite is rejected if it was cut off (`stop_reason` isn't `end_turn`), has a number not in the facts, or names a known place, town or station the facts don't (`grounded_in`, names set per scenario by `Engine._name_drafts`). The template then stands.
- Alerts are never rewritten. Keep both templates within 360 characters (`WEA_MAX`).

## No voice
In-app TTS (the console's Web Speech voice and macOS `say`) was removed in #138, and push-to-talk speech-to-text in #171. Questions are typed. The commander's output is the `commander_message` text (answers and briefings). If speech is wanted, feed those messages to an external TTS.
