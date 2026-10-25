# Fireline

**Wildfire forecasting and response software.** 🏆 Placed at **HackOhio 2026** and won the **AI for Social Good** award.

Fireline is decision-support software for people forecasting and responding to a wildfire. It forecasts where the fire will go, plans evacuation routes around roads that are about to burn, tells you when each town must be ordered out, dispatches crews and tankers from real stations, recommends where to put them, and answers questions through an AI incident commander.

**The rule behind all of it:** every number an operator sees comes from simulating the fire. The language model never invents figures; it only phrases numbers the simulations produced, and a guard rejects any answer that contains a number no tool returned.

For the demo, a 3D-printed terrain model sits under a projector and an overhead webcam. The projector paints the live fire onto the print, and the camera stands in for a drone looking down at the incident. The table is the showpiece. The command console is the product.

## Features

- **Fire forecast.** 32 Monte Carlo runs of a stochastic fire model give P(burn) for every cell at T+30 and T+60 min, plus a 10-hour forecast for evacuation planning. The model's constants are validated against the 2018 Camp Fire and the 2021 Marshall Fire.
- **Calibrated uncertainty.** Every probability carries a 90% interval. Online conformal calibration adjusts the burn outline so about 90% of new fire lands inside it, and gives town arrival ranges like "fire likely arrives in 25–40 min (90%)".
- **Evacuation routing.** Each town's best way out, routed around roads likely to burn by the time traffic reaches them.
- **Evacuation order clock.** When each town must be ordered out so the last car leaves before the fire arrives, using a traffic queue model that shares road capacity between towns.
- **Crew recommendations.** Paired Monte Carlo what-ifs find where a crew helps most and which towns it saves. A recommendation is shown only when its benefit is clearly above zero.
- **Plan mode.** Try a set of orders and an assumed wind, and see acres and residents saved against doing nothing, without touching the live incident.
- **Learned emulator.** A 1.5M-parameter U-Net (MLX) previews the forecast in about 6 ms and shortlists crew spots for the full simulation to score.
- **AI incident commander.** Claude answers typed questions using four simulation tools (situation, wind what-ifs, crew placement, routes). It falls back to rule-based answers when offline.
- **Drafts.** Unit orders, crew briefings and bilingual (English/Spanish) evacuation alerts within the 360-character Wireless Emergency Alert limit, each approved by the operator.

See [`AI_README.md`](AI_README.md) for how each model works and how to read its uncertainty, and [`PLAN.md`](PLAN.md) for the full design.

## Architecture

```
┌────────────────────── Tauri app ──────────────────────┐
│  Operator console (the product)                       │
│  Exercise control (plays the world: fire, wind, clock)│
│  Projector view   (fullscreen on the terrain print)   │
└──────────────────────────┬────────────────────────────┘
                           │ WebSocket (JSON + binary grids)
┌──────────────────────────┴────────────────────────────┐
│  Python engine: vision · sim · forecaster · router ·  │
│                 uncertainty · LLM commander           │
└───────────────────────────────────────────────────────┘
```

| Path | What | Stack |
|---|---|---|
| `app/` | Tauri shell and React UI (console, exercise control, projector) | TypeScript, React, Vite, Tailwind, WebGL |
| `engine/` | Simulation, forecasting, routing, uncertainty, vision, commander | Python, NumPy, OpenCV, networkx, MLX, Claude API |
| `assets/` | Scenarios (Paradise / Camp Fire, Marshall), marker sheets | |
| `tools/` | Terrain, fuel and road pipelines from DEM and OpenStreetMap data | Python |

The Python engine holds all state and runs a 10 Hz tick loop. Forecasts and recommendations run in worker processes so they never stall it.

## Running it

Requires macOS, [uv](https://docs.astral.sh/uv/), [pnpm](https://pnpm.io/) and, for the desktop app, the Rust toolchain.

```sh
cp .env.example .env   # optionally add ANTHROPIC_API_KEY for the commander
make install
make dev               # engine + Tauri app
```

To run in a browser instead, start `make engine` and `make web`, then open `http://localhost:1420/?view=console` (and `?view=control` to drive the fire). No camera or projector is needed: virtual table mode works everywhere.

Set `ENGINE_EXTRAS=ml` in `.env` to enable the learned emulator (Apple silicon). Run the tests with `make test`.

## Team

Built at HackOhio 2026 by Adarsh Muralidharan, Aditya Vadlamani, Jayson Clark and Jalen Francis.
