---
name: run-dev
description: Start the Python engine and the UI (Tauri app or plain browser) for local development. Use when asked to run, start, or test the app, or to check that engine and UI connect.
---

From the repo root:

- `make install` once (or after pulling dependency changes).
- `make dev` runs the engine and the Tauri app together. Or run `make engine` and `make app` in two terminals.
- No Tauri? `make engine` + `make web`, then open `http://localhost:1420/?view=console` and `http://localhost:1420/?view=projector`.

Check it works: the console header shows "engine connected". Clicking the map in either window adds a virtual token, and it appears in both windows. Drag to move, right-click to remove. In the projector, keys 1–4 pick the token type.

Gotchas:
- Vite needs port 1420 (`strictPort`). Kill a stale `vite` if it fails to start.
- The engine listens on `ENGINE_PORT` (default 8765). The UI reads `VITE_ENGINE_URL`. Both come from the root `.env`.
- The UI reconnects every second, so restarting the engine is safe. Engine state (tokens) resets on restart.
- First `make app` compiles Rust (~30 s+). Later runs are fast.
- Projector window: pick a monitor in the console's Projector panel and click "Open projector". It goes fullscreen on that monitor.
