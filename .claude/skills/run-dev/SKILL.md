---
name: run-dev
description: Start the Python engine and the UI (Tauri app or plain browser) for local development. Use when asked to run, start, or test the app, or to check that engine and UI connect.
---

From the repo root:

- `make install` once (or after pulling dependency changes).
- `make dev` runs the engine and the Tauri app together. Or run `make engine` and `make app` in two terminals.
- Optional engine extras: set `ENGINE_EXTRAS="ml voice"` in `.env` (or `make engine ENGINE_EXTRAS=ml`). `ml` turns on the learned fire emulator (instant forecast previews, crew-spot screening); `voice` turns on push-to-talk. A plain `uv run server.py` drops extras.
- No Tauri? `make engine` + `make web`, then open `http://localhost:1420/?view=console` (the operator console), `?view=control` (exercise control) and `?view=projector`.

Check it works: the console header shows "Engine connected". The console is the operator's view and can't light fires: click "Exercise control ↗" in its header, then ignite on the 3D virtual table there (I, then click). Within a few seconds the console's decision queue and town board fill in. In the console, keys 1–4 pick an order tool (a click sends that unit), Esc goes back to looking, M/P/R switch Monitor/Plan/Review, and holding Space talks to the commander. In exercise control, 1–4 pick a token type, I ignites, and Space pauses.
- Second engine for testing without touching a running one: `ENGINE_PORT=8775 ENGINE_ORIGINS=http://localhost:1430 uv run server.py` from `engine/`, and `VITE_ENGINE_URL=ws://localhost:8775 pnpm exec vite --port 1430 --strictPort` from `app/` (shell env beats `.env`).

No sim yet? The fire layer renders `sim_grid` binary frames (cell states 0–3, PLAN.md order). Until the sim sends them, a throwaway websocket stub on port 8765 that broadcasts `pack_binary(BinaryType.SIM_GRID, ...)` frames is enough to check the visuals.

Gotchas:
- Vite needs port 1420 (`strictPort`). Kill a stale `vite` if it fails to start.
- The engine listens on `ENGINE_PORT` (default 8765). The UI reads `VITE_ENGINE_URL`. Both come from the root `.env`.
- Terrain comes from `assets/scenarios/$VITE_SCENARIO` (default `paradise`); `?scenario=<name>` overrides it per window.
- The UI reconnects every second, so restarting the engine is safe. Engine state (tokens) resets on restart.
- First `make app` compiles Rust (~30 s+). Later runs are fast.
- Projector window: pick a monitor in exercise control's Projector panel and click "Open projector". It goes fullscreen on that monitor.
