# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

@AGENTS.md

## Beyond AGENTS.md

**Narrower checks.** No linter or formatter is configured.
- One test: `cd engine && uv run pytest tests/test_tokens.py::test_virtual_tokens_flow_through_tracker -q`. Run pytest from `engine/` because `tests/conftest.py` puts `engine/` on `sys.path` for the flat imports.
- App typecheck only: `cd app && pnpm exec tsc --noEmit`

**How the code fits together** (the design is in `PLAN.md` → Architecture):
- `engine/server.py` `Engine` holds all state. `run()` is the 10 Hz tick loop, `dispatch()` routes validated client messages (`client_message_adapter`), and messages go out with `broadcast(clients, Model(...).model_dump_json())`. On connect, a client gets the full current state, so windows can reload freely.
- Each fire step (`step_fire`), the sim advances (`engine/sim/`), burning roads close at once, and the round is scored (`sim/game.py`). When a forecast lands from its worker process (`engine/forecast/`), routes are replanned in a thread (`engine/routing/`), crew recommendations run in a second worker process (`forecast/recommend.py`), and the commander's briefings are checked (`engine/commander/`). Slow work never runs on the tick loop.
- Tokens enter the engine only through `TokenTracker.update(source, full_snapshot)` (`engine/vision/tokens.py`). Camera vision and virtual table clicks (`vision/virtual.py`) both report that way, and the game layer decides which tokens are within the round's limits.
- `app/src/shared/engine.ts` is the only WebSocket client and the store (`useEngine()` via `useSyncExternalStore`, `send()` for client messages). Each window opens its own connection and reconnects every second.
- `app/src/main.tsx` chooses the Console or Projector view from `?view=`. Tauri calls go through `getPlatform()` in `app/src/platform/`, which lazy-loads `tauri.ts` so the browser build never imports `@tauri-apps/api`.

**Project skills** in `.claude/skills/` cover running the app, protocol changes, terrain, roads, fuel, fire tuning, the camera, the commander and voice, and the agent board. Each `SKILL.md` says when to use it; check there before rediscovering a workflow.
