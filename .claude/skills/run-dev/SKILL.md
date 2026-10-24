---
name: run-dev
description: Start the Python engine and the UI (Tauri app or plain browser) for local development. Use when asked to run, start, or test the app, or to check that engine and UI connect.
---

From the repo root:

- `make install` once (or after pulling dependency changes).
- `make dev` runs the engine and the Tauri app together. Or run `make engine` and `make app` in two terminals.
- No Tauri? `make engine` + `make web`, then open `http://localhost:1420/?view=console` and `http://localhost:1420/?view=projector`.

Check it works: the console header shows "Engine connected". The console opens on the 3D virtual table; clicking the terrain adds a virtual token, and it appears in both windows. Drag a puck to move it, right-click to remove; drag empty space to orbit. Keys 1–4 pick the token type in both windows.

No sim yet? The fire layer renders `sim_grid` binary frames (cell states 0–3, PLAN.md order). Until the sim sends them, a throwaway websocket stub on port 8765 that broadcasts `pack_binary(BinaryType.SIM_GRID, ...)` frames is enough to check the visuals.

Gotchas:
- Vite needs port 1420 (`strictPort`). Kill a stale `vite` if it fails to start.
- The engine listens on `ENGINE_PORT` (default 8765). The UI reads `VITE_ENGINE_URL`. Both come from the root `.env`.
- Terrain comes from `assets/scenarios/$VITE_SCENARIO` (default `paradise`); `?scenario=<name>` overrides it per window.
- The UI reconnects every second, so restarting the engine is safe. Engine state (tokens) resets on restart.
- First `make app` compiles Rust (~30 s+). Later runs are fast.
- Projector window: pick a monitor in the console's Projector panel and click "Open projector". It goes fullscreen on that monitor.
