# Firewatch: Projection-Mapped Wildfire Command Table

A 3D-printed terrain model sits on a table under an overhead projector and webcam. The projector paints a live, spreading wildfire onto the terrain, along with topo colors, wind, roads, and towns. Players place physical tokens (fire crews, water drops, firebreaks, evacuation buses) on the map. The camera tracks them, the simulation reacts in real time, and an AI incident commander forecasts the fire, plans evacuations, and recommends where to deploy resources. Everything is projected back onto the terrain.

---

## Contents

1. [Stack](#stack)
2. [Architecture](#architecture)
3. [The Two Windows](#the-two-windows)
4. [Core Systems](#core-systems)
5. [Phases](#phases)
6. [Pre-Event Prep](#pre-event-prep)
7. [Ownership](#ownership)
8. [Hardware](#hardware)
9. [Risks](#risks)
10. [Demo Script](#demo-script)

---

## Stack

| Layer | Tech | Responsibility |
|---|---|---|
| Desktop shell | **Tauri** (Rust, kept thin) | Launch the engine, manage windows and monitors, fullscreen projector window |
| UI | **React + Vite + Tailwind + shadcn/ui** | Command console and projector view |
| Projector rendering | **WebGL** via Three.js (one projection shader; 3D only for the virtual table) | Shaders for fire, terrain, forecast ghost, routes |
| Engine | **Python**: OpenCV, NumPy, networkx, pyserial | Vision, simulation, forecasting, routing, LLM commander, wind knob |
| Transport | **WebSocket** | Binary grids and JSON messages between engine and UI |
| Commander | Claude API (tool use) + speech-to-text + TTS | Spoken briefings and what-if questions |

### Why Tauri + React

- Web layouts and design (React, Tailwind, CSS animation, WebGL) with a native app feel: real windows, no browser chrome, an app icon.
- Tauri's monitor API puts a borderless fullscreen window on the projector display.
- Rust stays thin because all the logic lives in the Python engine.

### Things to know about Tauri

- **The whole team is on macOS,** so the only target is Tauri's macOS webview (WKWebView, the Safari engine). WebGL works well there. Test shaders in Safari rather than only in Chrome, and skip WebGPU.
- **Set up the Rust toolchain before the event.** The first build is slow.
- **The webview never touches the webcam.** Python owns the camera and streams frames to the console.

### Fallback rule

The React app must also run unchanged in a plain browser (`vite dev` plus two Chrome windows). **All Tauri API calls live in one `app/src/platform/` module**, with a browser implementation as fallback. If Tauri causes trouble, the switch takes seconds.

---

## Architecture

```
┌────────────────────── Tauri app ──────────────────────┐
│  Rust (thin): launch engine, window/monitor mgmt,     │
│               fullscreen projector window             │
│                                                       │
│  React window 1: COMMAND CONSOLE  (laptop screen)     │
│  React window 2: PROJECTOR VIEW   (projector, no UI)  │
└──────────────────────────┬────────────────────────────┘
                           │ WebSocket (JSON + binary frames)
┌──────────────────────────┴────────────────────────────┐
│  Python engine: vision · sim · forecaster · router ·  │
│                 LLM commander · wind knob (pyserial)  │
└───────────────────────────────────────────────────────┘
```

Inside the engine:

```
 Webcam ──► Vision (thread) ──► tokens[] in map coords ──┐
                                                         ▼
 Wind knob / console dial ─────────────────────► Sim tick (~10 Hz, NumPy)
                                                         │ state snapshot
                       ┌─────────────────────────────────┼─────────────────┐
                       ▼                                 ▼                 ▼
          Forecaster (separate process)        Router (networkx)    Commander (async)
          N stochastic rollouts → P(burn, t)   cost = f(P(burn,t))  LLM + tools
                       └───────────────┬─────────────────┘
                                       ▼
                         WebSocket broadcast → both windows
```

### Principles

- **The Python engine holds all state.** Both windows are views of it, so restarting the UI never loses the fire.
- **One canonical coordinate frame: the map grid** (Paradise is 256×192; the size comes from the scenario's `terrain.json`, and the grid is not square). Every module speaks map coordinates. Only vision (camera→map) and the projector shader (map→projector) know about homographies.
- **The forecaster runs in its own process,** so rollouts never stall the sim or the render.
- **Virtual table mode from day one.** Mouse clicks in the projector or console window create fake tokens through the same message path real vision uses, so sim, AI, and UI work never waits on hardware.

### Message protocol

Define the schemas once as Pydantic models in `engine/protocol.py`, then generate TypeScript types for React with `make types` (Pydantic JSON schema → `json-schema-to-typescript` → `app/src/shared/protocol.ts`). JSON messages are discriminated on a `type` field.

**Binary frames** (engine → UI), with a 12-byte little-endian header (`type: u8`, 3 pad bytes, `tick: u32`, `width: u16`, `height: u16`). The header is mirrored by hand in `app/src/shared/binary.ts`:
- `sim_grid`: `uint8` cell states (0 unburnable, 1 fuel, 2 burning, 3 burned), 256×192 is 48 KB, every tick (10 Hz)
- `forecast_grid`: `uint8` burn probability (0–255), one `width×height` grid per horizon stacked in the order of `Hello.forecast_horizons_min` (T+30, T+60), in one frame. The header's tick is the sim tick the forecast started from. Sent each time a forecast lands, and all-zero on reset
- `camera_frame`: JPEG of the webcam with the vision overlay drawn in (960 px wide, 6 fps, only while `CAMERA` is set). The header's width/height are the JPEG's and its tick counts feed frames. It's broadcast to every window; the projector ignores it

**JSON messages:**
- engine → UI: `tokens`, `routes`, `recommendations`, `score`, `events` (town threatened, road cut, ...), `commander_message`, `calibration`, `scenario_state`
- UI → engine: `set_wind`, `ignite`, `reset`, `load_scenario`, `virtual_token_add/move/remove`, `calibration_step`, `commander_query`, `accept_recommendation`

Implemented so far: `hello` (protocol version, scenario name, map size, sim-minutes per tick, forecast horizons), `scenario_state` (tick, wind, burning and burned cell counts), `tokens`, `virtual_token_add/move/remove`, `ignite {x, y}`, `reset`, `set_wind {speed_ms, from_deg}`, `start_round`, `end_round`, `score`, `set_running`, `set_speed`, `step_once` (pause, speed and single steps; `scenario_state` carries `paused` and `speed`), `vision_status` (camera state, fps, corner markers seen, board locked), and the `sim_grid`, `forecast_grid` and `camera_frame` binary frames. Add the rest as each phase needs them.

**Wind convention** everywhere (protocol, sim, commander tools): `speed_ms` in m/s and `from_deg` meteorological, the direction the wind blows *from*, degrees clockwise from north (map up, −y). 270 is a west wind that pushes fire east.

**Token path.** Real vision and virtual table mode both report full per-source snapshots to `TokenTracker` (`engine/vision/tokens.py`); the rest of the engine only reads `tracker.tokens`. Virtual tokens come from `engine/vision/virtual.py`. Camera tokens come from `engine/vision/camera.py`, a thread that reads frames, detects markers, solves `H_cam→map` from the corner markers and debounces (`engine/vision/tracking.py`). The main loop only picks up its latest snapshot each tick. It's off unless `CAMERA` is set in `.env` (see the `vision-camera` skill).

**Windows.** One React bundle; `?view=console` or `?view=projector` picks the view. In Tauri the console is the `main` window from `tauri.conf.json`, and the projector is created on demand by `app/src/platform/tauri.ts` on the chosen monitor, then made fullscreen. Closing the console quits the app. In a browser, the projector is a popup (press F to fullscreen). Both windows render with `app/src/render/` (see [The Two Windows](#the-two-windows)).

### Repo layout

```
app/                    Tauri + React
  src/
    platform/           all Tauri API calls (with browser fallback)
    console/            command console window
    projector/          projector view (fullscreen projection)
    render/             projection shader, flat projection view, 3D virtual table
    shared/             ws client + store (engine.ts), generated types (protocol.ts), scenario loader
  src-tauri/            thin Rust shell
engine/                 Python
  server.py             WebSocket server + main loop
  vision/               calibration, marker tracking
  sim/                  fire CA, suppression, layers
  forecast/             batched rollouts, crew recommendations
  routing/              road graph, evac routing
  commander/            LLM tools, speech-to-text/TTS
  uq/                   uncertainty: sampling intervals (mc.py); conformal calibration to come
  protocol.py           Pydantic message models
  gen_schema.py         protocol JSON schema for `make types`
  tests/                pytest
assets/
  scenarios/<name>/     terrain.yaml (DEM generator input), heightmap.npy, terrain.json, preview.png,
                        fuel.png, roads.geojson, towns.json, config.yaml
  stl/<name>/           generated print tiles (gitignored, regenerate them)
  markers/              printable ArUco sheets (markers.pdf, from tools/make_markers.py)
tools/
  dem_to_assets.py      DEM → heightmap.npy + STL tiles (single source of truth)
  osm_to_fuel.py        OSM land cover → fuel.png (the fire's fuel layer)
  make_markers.py       ArUco IDs → assets/markers/markers.pdf (vector, print at 100%)
```

---

## The Two Windows

### Projector view

Pure WebGL, no UI chrome, fullscreen on the projector monitor.

**One projection shader** (`app/src/render/shaders.ts`) computes what the projector emits, per pixel in map coordinates: topo tint, hillshade, contours, labels, fire and token halos. The projector draws it on a flat quad. The console's virtual table drapes the *same* shader over the terrain mesh, so what you see in 3D is what the real projector would throw onto the print. The UI loads terrain straight from `assets/scenarios/<name>/` (`terrain.json` + `heightmap.npy`), picked by `VITE_SCENARIO` or `?scenario=`.

- The sim grid is uploaded as a texture each tick. A fragment shader maps cell states to visuals: topo base, flickering flame on burning cells, char on burned ones.
- Overlay layers include the forecast ghost (probability contours), glowing evacuation routes, pulsing recommendation markers, wind particles, town labels, and the token halos.
- **The calibration homography is a 3×3 matrix applied in the vertex shader.** Python never warps images.
- Embers, wind streaks, and route pulses are animated in shaders.

### Command console

Looks polished and native, on the laptop screen.

- **Virtual table:** a 3D view of the print on the table (true mm dimensions, tile seams, corner marker holders), with the projection draped over it and token pucks you can place, drag and remove. Camera presets and fly-to for places. Works with no hardware.
- **Projection view:** the flat projector output, for checking exactly what gets projected
- **Camera feed** with detected markers overlaid (for debugging, and to show judges the vision working)
- **Calibration wizard:** a step-by-step flow with a recalibrate button
- **Scenario controls:** ignite, reset, scenario picker, wind dial (synced with the physical knob)
- **Commander panel:** transcript, push-to-talk, recommendation cards with an "accept" button
- **Scoreboard:** people evacuated, structures saved, acres burned, resources left

---

## Core Systems

### Calibration

1. The projector shows a ChArUco pattern at known projector-pixel positions. The camera detects it, giving `H_cam→proj`.
2. ArUco markers on holders pinned to the four board corners, just outside the terrain, are detected, giving `H_cam→map`.
3. Combine them: `H_map→proj = H_cam→proj · H_map→cam`, which the projector shader uses.
4. Save to `calibration.json`. The console has a hotkey and button to recalibrate in seconds when someone bumps the table.

**Height parallax.** Projected points land offset by roughly `h × d / H` (feature height × distance from the projector's center axis ÷ projector height). With a projector about 150 cm up, a 4 cm hill 30 cm off-axis shifts about 0.8 cm. That's acceptable with low relief. The full fix (rendering the terrain mesh from a calibrated projector pose) is in Phase 7.

### Token tracking

- Each token carries an ArUco marker (`DICT_4X4_50`), and its marker ID determines its type: corners 0–3 (NW, NE, SE, SW), crew 10–14, firebreak 20–24, water 30–34, bus 40–44 (`engine/vision/markers.py`). Only printed IDs are accepted, so a misread can't become a phantom token. On the wire a token's id is `m<marker id>`, so sim effects survive brief dropouts.
- **Board homography:** `H_cam→map` is re-solved from the four corner-marker centres on every frame where all four are visible, and the last good one is kept while a corner is covered. So a bumped table or camera fixes itself.
- **Debounce:** a token counts as placed after 3 frames in a row, and as removed after 15 frames missing (~0.5 s).
- **Smoothing:** positions and angles are low-passed, with a small deadband so still tokens don't re-broadcast. A jump of more than 3 cells is taken at once.
- **White halo:** the projector draws a solid white ring under each known token so its marker stays high-contrast under colored fire light. It doubles as a "selected" visual.

| Token | Effect |
|---|---|
| Fire crew | Raises suppression within a radius over time |
| Firebreak strip | Removes fuel along its line (two markers, one at each end, or one oriented marker) |
| Water drop | Instant knockdown in a radius, with a cooldown |
| Evac bus | Moves along the computed route and picks up residents from a town |

**Dispatch (#104).** A crew, firebreak or water token is an order, not a teleport. The fastest free unit of that type is sent: an engine crew or dozer from a real fire station (`stations.json`, from OSM) driving the road graph at 50 km/h, skipping burning roads, then hiking the last stretch; or a tanker flying from the Chico air base, grounded above 13 m/s wind. Every order pays a 3-minute turnout. The token only acts on the fire once its unit arrives (`engine/sim/dispatch.py`, travel times in `engine/routing/units.py`). Moving a token re-routes its unit, removing it frees the unit, and a unit whose road burns re-routes or reports blocked. Buses are not dispatched. Units go out as a `units` message and the projector draws each one's route and ETA. Forecasts credit en-route units from their arrival tick, and recommendations and the commander's what-ifs start a crew digging in only when one could get there, with the station named ("a crew from Jarbo Gap, about 17 minutes out").

### Fire model

Based on **Alexandridis et al. (2008)**, a cellular automaton validated against a real fire on Spetses island, with Rothermel-inspired wind and slope terms.

```
p_burn = p_h · (1 + p_veg) · (1 + p_den) · p_wind · p_slope · (1 − suppression)

p_wind  = exp(c1·V) · exp(c2·V·(cos θ − 1))   # θ = angle between wind and spread direction
p_slope = exp(a · slope_angle)                 # uphill spreads faster, downhill slower
```

**Crews hold flanks, not the head.** Partial suppression (a crew's line, a wet patch) is scaled by `1 / (1 + (p / HOLD_P)²)`, where `p` is the strongest single-neighbour spread chance into the cell. So it holds backing fire, flanks and calm fire, but barely slows a wind-driven head. Full suppression (a firebreak, the tick a water drop lands) still stops anything. Measured with `eval.early_attack` (three crews ordered onto each eval ignition, acres burned after 3 h):

| Wind | No crews | Instant crews (old exploit) | Crews dispatched from stations |
|---|---|---|---|
| 3 m/s | 5,343 ac | 331 ac, 92% out | 3,281 ac |
| 8 m/s | 6,336 ac | 2,449 ac, 58% out (was 100%) | 5,845 ac |
| 13 m/s | 14,044 ac | 10,920 ac, 0% out (was 100%) | 13,188 ac |

The top recommendation's realized benefit fell from 985 to 708 (steady wind). It still beats a random front spot 19 of 32 times, and its prediction stays calibrated (689 predicted).

- **Cell states:** `unburnable`, `fuel`, `burning`, `burned`. A burning cell burns for k ticks, giving the fire front visible thickness.
- **Layers:** `heightmap` (→ slope), `fuel_type`, `fuel_density`, `suppression`, `roads`, `towns`.
- **Vectorized:** 8 shifted-array operations per tick (one per neighbor direction), restricted to the bounding box of the burning cells. A step on Paradise takes well under 1 ms.
- Wind comes from the physical knob (Arduino potentiometer → pyserial) or the console dial.
- **Time scale:** one tick is one sim-minute (`SIM_MINUTES_PER_TICK` in `engine/sim/fire.py`), so 10 Hz is 10 sim-minutes per second and T+60 is 60 ticks. A fire can move at most one 94 m cell per tick (≈5.6 km/h), about the Camp Fire's run through Paradise.
- **Constants are tuned for the table, not the paper:** `p_h` is lower (cells burn for 8 ticks, so neighbors get 8 tries), the wind terms are about 3× Alexandridis' so the wind visibly steers the fire, and the slope term is softened because Paradise's real canyon walls made the paper's value impassable downhill. Slope uses the real heightmap in metres, not the print's exaggerated relief. See the `tune-fire` skill.
- **Fuel:** uniform until a fuel map exists. `fuel.png` (grayscale, black = unburnable) and `roads.json` (roads are a partial fuel break) are loaded if present.
- **Suppression** is the one knob for every intervention (`engine/sim/effects.py` turns tokens into it each tick). Suppression of exactly 1 also puts out burning cells, which is how water knockdowns and firebreaks laid over flames work. Crews top out at 0.9, so they hold a line but don't snuff fire.

### Forecasting

- **Batched stochastic rollouts:** stack N copies of the state into an array of shape `(N, H, W)` and advance them all with one vectorized step.
- Record the first time each cell burns in each rollout, giving `P(burn by t)` for each horizon.
- `forecast.rollout(snapshot, n, ticks, wind=..., extra_suppression=...)` returns that first-burn time as `(n, H, W)` float32, with optional wind and crew what-ifs; `forecast.burn_probability` turns it into `P(burn by horizon)`. The live forecast (32 rollouts to T+60) runs in a worker process, one at a time, and lands on `Engine.latest_forecast` for routing and the commander. Suppression follows the tokens' schedule (`TokenEffects.schedule`, carried on the snapshot): crews keep digging in and wet ground dries out over the forecast, exactly as the live sim would if the tokens stay put (#56). Paired what-ifs can be `TimedLayer`s that start at an arrival tick.
- **Paired what-ifs:** `forecast.rollout_paired(snapshot, n, ticks, variants)` runs a baseline plus K suppression variants (e.g. a crew at each candidate spot) in one batch, as `(K+1, n, H, W)`. Rollout i of every variant shares its random draws (`advance(..., group=K+1)`), so the difference between a variant and the baseline is the intervention's effect, not luck. Recommendations rely on this.
- **Wind spread (optional):** `WindSpread(speed_frac, dir_deg)` gives each rollout its own wind (`advance(..., wind_rows=...)`). It's off for the live forecast (`forecast.runner.WIND_SPREAD = None`), and when it's on, `Forecast.wind_spread` records it.
- The projector shows a translucent ghost with 50% and 90% contours at T+30 and T+60 sim-minutes.

### Evacuation routing

- The road network is a networkx graph built from the scenario's roads.
- Edge cost is `length × (1 + λ · P(burn at the moment the bus reaches it))`. **The arrival-time-aware cost is the key idea:** routes avoid roads that *will* burn, not only roads burning now.
- Routes are recomputed whenever the forecast updates, and drawn as glowing paths.
- **Data:** `roads.json` and `towns.json` per scenario, from OpenStreetMap via `tools/osm_to_layers.py` (see the `generate-road-layers` skill). Towns carry approximate population and structure counts; `safe_zones` are the map-edge exits (Paradise: Skyway toward Chico, Clark Rd and Hwy 70 toward Oroville). The scenario layout above lists `roads.geojson`; it's `roads.json` in map coords instead.
- **Approximation** (`engine/routing/evac.py`): per-edge P(burn by t) is precomputed at 5-sim-minute bins in one vectorized pass over the forecast's `first_burn`, then a label-setting Dijkstra carries the bus's free-flow arrival time along each label's path and reads the bin at each edge's midpoint. Edges at P ≥ 0.9 by arrival are impassable. Not an exact time-dependent shortest path, but a replan of every town is tens of milliseconds.

### Crew recommendations

- Sample candidate cells along the predicted fire front.
- For each candidate, run a few rollouts with a crew placed there, then rank by population and structures saved.
- Project the top 3 as pulsing markers labeled, for example, "Saves Pinecrest in 87% of simulations."
- **Uncertainty** (`engine/uq/mc.py`): every "k of N" carries a 90% Wilson interval, and each recommendation's benefit a paired t interval. A recommendation is shown only if the *low* end of its benefit is above zero, and the top two are re-run head to head when their intervals overlap. Town threat briefings use the interval's bounds instead of the raw share. This is sampling uncertainty only; whether the forecast's assumptions hold is for conformal calibration (#12, #13).

### Incident commander (LLM)

The LLM gets **tools**, not a raw state dump, so its answers come from real simulation calls:

| Tool | Returns |
|---|---|
| `get_situation()` | Fire extent, threatened towns, time to impact, active resources, wind |
| `forecast_whatif(wind_dir, wind_speed, horizon)` | Forecast summary under the hypothetical conditions |
| `evaluate_placement(token_type, x, y)` | Expected outcome change from placing a resource |
| `get_routes()` | Current evacuation routes and their risk |

- Triggered by events (town threatened, road cut) for proactive briefings, and by push-to-talk questions.
- Answers are kept to about two sentences so they work spoken aloud.
- Uses a fast model for low latency.

### Game layer

- **Scenarios:** a fictional training valley, and Paradise, CA (Camp Fire).
- **Limited resources:** for example 3 crews, 2 water drops (with cooldown), and 1 firebreak, which forces tradeoffs.
- **Scoring:** people evacuated, structures saved, acres burned.
- **Scenario timer** and an end-of-round summary.
- **Attract mode:** an idle animated state that draws judges in.

As built (`engine/sim/game.py`):

- **Sandbox vs round.** Outside a round nothing is limited or timed, so virtual table mode stays free play. `start_round` resets the map, ignites at the scenario's ignition point and turns the limits on; the round ends on time, when nothing is burning, or on `end_round`, and then the fire freezes so the summary matches the map. `reset` returns to the sandbox.
- **Limits** count tokens on the table per type (3 crews, 2 water, 1 firebreak, 2 buses). The first ones placed take effect; any over the limit do nothing and are listed in `score.inactive_tokens` so the UI can grey them out.
- **Scoring:** acres burned from burning and burned cells; structures lost as each town's structures times the share of its burnable disk that has caught; people evacuated while an in-limit bus sits inside a town whose route isn't cut (a stand-in until buses drive their routes).
- **Per-scenario settings** (round length, limits, ignition, bus rate) live in an optional `assets/scenarios/<name>/game.json`. Paradise: 600 sim-minutes, ignition at the Camp Fire origin, 40 people per minute per bus.

---

## Phases

Each phase ends in a demoable state. The exit criteria say when to move on, and no phase depends on a later one.

### Phase 0: Foundations
- Monorepo scaffold (`app/`, `engine/`, `assets/`, `tools/`)
- WebSocket protocol with Pydantic models and generated TS types
- Tauri shell with two windows, the projector window fullscreen on a chosen monitor
- `platform/` module with Tauri and browser implementations
- Virtual table mode: clicks create fake tokens through the vision message path

**Exit:** engine and UI connect, and a clicked fake token shows up in both windows.

### Phase 1: Fire on a flat table
- Fire CA with wind speed and direction
- Projector shader rendering cell states
- Console wind dial, ignite and reset

**Exit:** fire spreads visibly with the wind and changes direction live when the dial turns.

### Phase 2: Physical loop
- Calibration pipeline and console wizard, with the recalibrate hotkey
- ArUco token tracking with debouncing and smoothing
- White halos under tracked tokens
- All four token types wired into the sim
- Physical wind knob

**Exit:** a real crew token on the table makes the projected fire around it die.

### Phase 3: Terrain-aware
- Slope layer from the shared heightmap
- Fuel, road, and town layers aligned to the print
- Topo-colored base render with contour lines that land on the physical ridges

**Exit:** fire visibly runs faster uphill on the real model, and the projected towns sit in the right spots.

### Phase 4: Prediction
- Forecaster process with batched rollouts
- Forecast ghost overlay with probability contours
- Arrival-time-aware evacuation routing, with bus tokens following the routes

**Exit:** the ghost predicts where the fire goes, and routes change before roads burn.

### Phase 5: Incident commander
- Crew placement recommendations, projected and shown as cards in the console
- LLM commander with the simulation tools
- Push-to-talk speech-to-text in, TTS briefings out
- Proactive event-driven briefings

**Exit:** a judge asks "What if the wind shifts west?" and hears a spoken answer backed by a real forecast.

### Phase 6: Game and polish
- Scenarios, limited resources, cooldowns, timer, scoring, end summary
- Attract mode
- Sound design (crackle, radio chatter)
- Visual polish and transitions in both windows

**Exit:** a stranger can play a full scenario with no explanation.

### Phase 7: Stretch
- **Camp Fire replay:** real ignition point and wind, compared against the actual 2018 perimeter (public data from NIFC) for validation
- **3D-corrected projection:** calibrate the projector as a pinhole camera and render the terrain mesh from its pose in Three.js, so projections stay aligned on tall features
- **Multiple players:** role-specific tokens and parallel objectives

---

## Pre-Event Prep

The 3D prints start the day before the competition, so everything that affects them must be locked in first.

- **The heightmap is the single source of truth.** Choose the area, resolution, and vertical exaggeration, then generate the STL tiles *and* the sim's `heightmap.npy` from the same script (`tools/dem_to_assets.py`).
  - Every setting lives in `assets/scenarios/<name>/terrain.yaml`: region, model size, base, relief, mesh resolution, tile grid, pins, and marker holders. See the `generate-terrain` skill.
  - **Paradise defaults:** 24 × 18 km around the Camp Fire (Pulga → Paradise) on a 330 × 248 mm (13 × 9.75 in) board, printed as 2×2 tiles of 165 × 124 mm. 1 mm = 73 m horizontally, 35 mm relief (2.12× exaggeration). The sim grid is 256 × 192 at 94 m per cell.
  - `terrain.json` records the map-frame positions of the corner markers (for `H_cam→map`; they sit outside the grid, so the coordinates are negative or larger than the grid) and of the towns.
- **Keep the relief low** (about 3–4 cm max) to limit projection parallax.
- **Build registration into the prints:**
  - alignment pins between tiles
  - corner holders for the calibration ArUco markers, kept off the terrain so they don't break immersion. One L-shaped holder STL (print 4) pins into the board's outer walls with the same filament pins, so they never move
- **Matte white or light-gray PLA,** which is essential for projection.
- **Tokens:** print them with flat tops, then laminate and attach the ArUco markers.
- **Toolchain:** Rust, Node, and Python environments installed and building on every laptop.
- **Mounting:** sort out the overhead projector and camera mount (stand or boom) in advance.

---

## Ownership

Virtual table mode means nobody is blocked waiting for hardware.

| Owner | Areas | Phases |
|---|---|---|
| App | Tauri shell, console UI, projector shaders, polish | 0, 1 (render), 6 |
| Vision | Calibration, token tracking, wind knob, 3D projection | 2, 7 |
| Sim | Fire CA, terrain layers, suppression, rollouts | 1, 3, 4 (forecaster) |
| AI | Routing, recommendations, commander, voice | 4 (routing), 5 |

---

## Hardware

- Projector (1080p, short-throw helps), mounted pointing straight down
- 1080p webcam mounted next to the projector
- Terrain tiles in matte white or light-gray PLA
- Printed tokens with laminated ArUco markers
- Arduino and potentiometer for the wind knob
- Black cloth or pop-up canopy to block ambient light
- Speaker and microphone for the commander

---

## Risks

| Risk | Mitigation |
|---|---|
| Bright venue washes out the projection | Bring a canopy or black cloth, and test in the actual venue early |
| Table gets bumped and calibration drifts | Corner markers on pinned holders, one-click recalibration |
| Projected light confuses marker detection | White halos under tokens, ArUco's contrast robustness, debouncing |
| WKWebView renders differently from Chrome | Test shaders in Safari / the Tauri build, use the browser fallback |
| Calibration perfectionism eats time | Use a plain homography first, keep 3D correction in Phase 7 |
| LLM latency or outages | Short answers, fast model, and the demo works fully without the commander |
| Live demo failure | Rehearse often, record a backup video |

---

## Demo Script

1. A judge walks up to the attract mode: topo-lit terrain, glowing towns, drifting wind.
2. A lightning strike ignites a ridge.
3. The fire races uphill. The commander announces: *"Pinecrest threatened in 12 minutes."* An evacuation route lights up.
4. The judge places crews and a firebreak. The fire bends around them in real time.
5. The judge turns the wind knob. The forecast ghost swings, routes reroute, and the commander re-briefs.
6. The judge asks, "What if the wind shifts west?" The commander answers from a real forecast.
7. Round ends with a score summary. Close with the Camp Fire replay against the real perimeter.
