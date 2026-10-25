# Fireline: Wildfire Forecasting and Response Software

Fireline is decision-support software for people forecasting and responding to a wildfire. It forecasts where the fire will go, plans evacuation routes around roads that are about to burn, dispatches crews and tankers from real stations, recommends where to put them, and gives written briefings and answers through an AI incident commander. **The command console is the product.**

**The physical table is a demo extra, not the product.** A 3D-printed terrain model sits under an overhead projector and webcam, and the projector paints the live fire, topo colors, roads and towns onto it. It stands in for the real world seen from above, the way drone or aerial footage shows an incident. The camera looking down at the table plays the part of a drone looking down at the fire. A real operator wouldn't stand at a table placing tokens during an incident; they'd use the software. So the table is a showpiece for the demo, and features are judged by whether they help an operator who only has the software.

---

## Contents

1. [Stack](#stack)
2. [Architecture](#architecture)
3. [The Windows](#the-windows)
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
| Engine | **Python**: OpenCV, NumPy, networkx | Vision, simulation, forecasting, routing, LLM commander |
| Transport | **WebSocket** | Binary grids and JSON messages between engine and UI |
| Commander | Claude API (tool use) | Briefings and typed what-if questions (text only; TTS removed in #138, push-to-talk in #171) |

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
│  React window 1: OPERATOR CONSOLE (the product)       │
│  React window 2: EXERCISE CONTROL (plays the world)   │
│  React window 3: PROJECTOR VIEW   (projector, no UI)  │
└──────────────────────────┬────────────────────────────┘
                           │ WebSocket (JSON + binary frames)
┌──────────────────────────┴────────────────────────────┐
│  Python engine: vision · sim · forecaster · router ·  │
│                 LLM commander                         │
└───────────────────────────────────────────────────────┘
```

Inside the engine:

```
 Webcam ──► Vision (thread) ──► tokens[] in map coords ──┐
                                                         ▼
 Wind (exercise control) ──────────────────────► Sim tick (~10 Hz, NumPy)
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

- **Software first.** The console has to stand on its own as the operator's tool. Table-specific code (camera, calibration, projection) stays in `vision/` and the projector view, and no engine or console feature should depend on the table.
- **The Python engine holds all state.** Both windows are views of it, so restarting the UI never loses the fire.
- **One canonical coordinate frame: the map grid** (Paradise is 256×192; the size comes from the scenario's `terrain.json`, and the grid is not square). Every module speaks map coordinates. Only vision (camera→map) and the projector shader (map→projector) know about homographies.
- **The forecaster runs in its own process,** so rollouts never stall the sim or the render.
- **Virtual table mode from day one.** Mouse clicks in the projector or console window create fake tokens through the same message path real vision uses, so sim, AI, and UI work never waits on hardware.

### Message protocol

Define the schemas once as Pydantic models in `engine/protocol.py`, then generate TypeScript types for React with `make types` (Pydantic JSON schema → `json-schema-to-typescript` → `app/src/shared/protocol.ts`). JSON messages are discriminated on a `type` field.

**Binary frames** (engine → UI), with a 12-byte little-endian header (`type: u8`, 3 pad bytes, `tick: u32`, `width: u16`, `height: u16`). The header is mirrored by hand in `app/src/shared/binary.ts`:
- `sim_grid`: `uint8` cell states (0 unburnable, 1 fuel, 2 burning, 3 burned), 256×192 is 48 KB, every tick (10 Hz)
- `forecast_grid`: `uint8` burn probability (0–255), one `width×height` grid per horizon stacked in the order of `Hello.forecast_horizons_min` (T+30, T+60), in one frame. The header's tick is the sim tick the forecast started from. Sent each time a forecast lands, and all-zero on reset
- `plan_grid`: two `uint8` grids, P(burned by the plan's horizon) without and then with a plan's orders, both under its assumed wind. The header's tick is the `plan_result` id it belongs to. Sent right after each successful `plan_result`
- `camera_frame`: JPEG of the webcam with the vision overlay drawn in (960 px wide, 6 fps, only while `CAMERA` is set). The header's width/height are the JPEG's and its tick counts feed frames. It's broadcast to every window; the projector ignores it

**JSON messages:**
- engine → UI: `tokens`, `routes`, `recommendations`, `score`, `events` (town threatened, road cut, ...), `commander_message`, `calibration`, `scenario_state`
- UI → engine: `set_wind`, `ignite`, `reset`, `load_scenario`, `virtual_token_add/move/remove`, `calibration_step`, `commander_query`, `accept_recommendation`

Implemented so far: `hello` (protocol version, scenario name, map size, sim-minutes per tick, forecast horizons), `scenario_state` (tick, wind, burning and burned cell counts), `tokens`, `virtual_token_add/move/remove`, `ignite {x, y}`, `reset`, `set_wind {speed_ms, from_deg}`, `start_round`, `end_round`, `score`, `set_running`, `set_speed`, `step_once` (pause, speed and single steps; `scenario_state` carries `paused` and `speed`), `vision_status` (camera state, fps, corner markers seen, board locked), `situation` (the console's town board: per town, how many simulations reach it within 30 and 60 min with 90% intervals, median and 10th-percentile minutes until fire, route status; sent after each Monte Carlo forecast and replan, on reset and on connect), `evaluate_plan {id, orders, wind, horizon_min}` and its `plan_result` (#123), `evac_clock` and `order_evacuation {town, ordered}` (#121), `calibration_step` and `calibration` (the projector calibration wizard and its map→projector matrix), and the `sim_grid`, `forecast_grid`, `plan_grid` and `camera_frame` binary frames. Add the rest as each phase needs them.

**Wind convention** everywhere (protocol, sim, commander tools): `speed_ms` in m/s and `from_deg` meteorological, the direction the wind blows *from*, degrees clockwise from north (map up, −y). 270 is a west wind that pushes fire east.

**Token path.** Real vision and virtual table mode both report full per-source snapshots to `TokenTracker` (`engine/vision/tokens.py`); the rest of the engine only reads `tracker.tokens`. Virtual tokens come from `engine/vision/virtual.py`. Camera tokens come from `engine/vision/camera.py`, a thread that reads frames, detects markers, solves `H_cam→map` from the corner markers and debounces (`engine/vision/tracking.py`). The main loop only picks up its latest snapshot each tick. It's off unless `CAMERA` is set in `.env` (see the `vision-camera` skill).

**Windows.** One React bundle; `?view=console` (the default), `?view=control` or `?view=projector` picks the view. In Tauri the console is the `main` window from `tauri.conf.json`; exercise control opens from the console's header, and the projector from exercise control on the chosen monitor (fullscreen). Both are created by `app/src/platform/tauri.ts`. Closing the console quits the app. In a browser they're popups (press F to fullscreen the projector). Every window renders with `app/src/render/` (see [The Windows](#the-windows)).

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
  commander/            LLM tools, briefings, drafted orders and alerts
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

## The Windows

The operator console is the product. Exercise control and the projector exist for development, training exercises and the demo.

### Operator console (`app/src/console/`)

For an incident manager or planning chief. It answers three questions: what's happening, what needs a decision, and what each option would do. It never plays the world: no igniting, no setting the wind, no clock controls. The one exception is demo mode (#158), hidden unless the console is opened with `?demo=1` or Shift+D is pressed: a bar over the map with pause, step and sim speed, and an Autopilot that takes the top decision (dispatch a recommended crew, order a due evacuation) after a countdown shown on its card. It's for recording the video and live judging.

**Design (#130).** A light, map-first operations UI, deliberately unlike the projector's glowing art. The incident map fills the window, with pan and zoom, and draws with its own quiet shader (`render/carto.ts`: light hillshade, faint contours, the burned area in warm gray, active fire in red-orange with a crisp perimeter, the forecast as two translucent bands). Towns, routes, stations, units, orders, recommendations and labels are vector overlays (`console/map/layers.tsx`), so they stay sharp at any zoom. Around it: a top bar (incident, status, clock, modes), the mode's sidebar on the left, an inspector on the right for whatever is selected (a town's fire arrival and evacuation clock, a recommendation's effect with ranges, an order's unit), and the commander docked in the map's corner. Tokens live in `index.css`: neutral surfaces, one blue accent for actions, status colors only for status. `console/model.ts` joins the town board with the evacuation clock so every view agrees on a town's risk.

Three modes over the one incident map:

- **Monitor:** a **decision queue**, most urgent first: towns to evacuate (with the soonest and likely time fire arrives, and the way out), towns with no safe way out, crew recommendations with the station and ETA, units that can't get through. Each card has its action (dispatch, send a bus, try in plan, show on map). A **town board** lists every town with time until fire (10th percentile to median), the share of simulations reaching it within the hour with its interval, and route status. **Units and orders** shows free units per type and every standing order with its unit's status. Order tools on the map send a crew, dozer line, air drop or bus where you click.
- **Plan** (#123): try orders and an assumed wind without changing anything. Clicks add draft orders; each is assigned the free unit dispatch would send, and only acts once that unit could get there. The plan runs against doing nothing on paired simulations (`forecast/plan.py`, `rollout_paired` with the plan as one suppression schedule), so the difference is the plan, not luck. The map shades where the plan keeps fire out (green) or pushes it in (red); the panel shows acres and residents affected with intervals, and per-town reach. It re-runs a moment after each edit; the engine skips a plan that a newer one replaced. "Dispatch" sends the orders for real.
- **Review:** outcome so far (people evacuated, structures, acres, per town) and the event log. The after-action comparison against doing nothing is #124.

The commander (briefings and typed questions) sits beside every mode, as text: operators mostly want it on screen.

### Exercise control (`app/src/control/`)

Plays the real world. In a real incident this is the fire itself plus drone footage and weather stations. It holds ignite and reset, wind, pause/speed/step, the scenario picker, exercises (timed, limited rounds), the 3D virtual table with token placement, the camera feed, and projector controls. **Autopilot** accepts the top crew recommendation a few seconds after each one arrives, so a recorded demo plays out without clicking every card.

### Projector view

Pure WebGL, no UI chrome, fullscreen on the projector monitor.

**One projection shader** (`app/src/render/shaders.ts`) computes what the projector emits, per pixel in map coordinates: topo tint, hillshade, contours, labels, fire and token halos. The projector draws it on a flat quad. Exercise control's virtual table drapes the *same* shader over the terrain mesh, so what you see in 3D is what the real projector would throw onto the print, and the console's incident map is the same flat projection. The UI loads terrain straight from `assets/scenarios/<name>/` (`terrain.json` + `heightmap.npy`), picked by `VITE_SCENARIO` or `?scenario=`.

- The sim grid is uploaded as a texture each tick. A fragment shader maps cell states to visuals: topo base, flickering flame on burning cells, char on burned ones.
- Overlay layers include the forecast ghost (probability contours), glowing evacuation routes, pulsing recommendation markers, wind particles, town labels, and the token halos.
- **The calibration homography is a 3×3 matrix applied in the vertex shader.** Python never warps images.
- Embers, wind streaks, and route pulses are animated in shaders.

### Later: a field app

A second product for the people carrying out orders (fire crews, police and sheriff units, bus drivers): each sees their own assignment, route and ETA, what changed, and when to pull out. The console's orders and units are already per-unit, so it would read the same engine state. Not started; noted so engine work keeps orders addressable per unit.

---

## Core Systems

### Calibration

1. The projector goes black until the camera sees all four corner markers (projected light washes them out), then shows a dim white ring with a dot by its top-left corner, stretched over its whole window. The camera finds the ring's 8 corners in each frame minus the black one, over a few frames, giving `H_cam→proj`. Big plain shapes rather than a marker grid, because a projector blooms its whites into small markers' bits; the ring's outer edges bloom outward and its inner edges inward, so the fit cancels most of it. The ring stays in the middle of the frame so it lands on the board, not the floor.
2. ArUco markers on holders pinned to the four board corners, just outside the terrain, are detected, giving `H_cam→map`.
3. Combine them: `H_map→proj = H_cam→proj · H_map→cam`, which the projector's vertex shader applies (`uMapToProj`, keeping the homography's w as clip w so texturing stays perspective-correct). Projector coords are normalised to the projector window (0..1, y down), so the matrix doesn't depend on its resolution.
4. The console wizard (Projector panel, Shift+C) reviews the fit on the table with a test grid and corner crosses, then saves to `calibration.json` at the repo root (gitignored, per rig).
5. `H_cam→proj` is saved too. Camera and projector share a mount, so a bumped table only moves the board in the camera view: the engine re-derives `H_map→proj` from the saved `H_cam→proj` and the corner markers, with no recalibration. Recalibrate if the camera moves relative to the projector.

Code: `engine/vision/projector.py` (engine), `app/src/control/CalibrationPanel.tsx` and `app/src/render/ProjectionView.tsx` (UI).

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
| 13 m/s | 20,839 ac (14,044 before spotting) | 17,624 ac, 17% out (was 100%) | 19,435 ac |

The top recommendation's realized benefit fell from 985 to 708 (steady wind). It still beats a random front spot 19 of 32 times, and its prediction stays calibrated (689 predicted).

**Ember spotting.** In wind over `SPOT_MIN_WIND` (9 m/s), burning cells throw embers downwind (`_spot` in `engine/sim/fire.py`). Each ember flies an exponential distance (mean 12 cells, about 1.1 km, at 10 m/s, capped at 6.6 km) and lights fuel where it lands, less so under suppression. That lets a wind-driven fire outrun the one-cell-per-tick limit, as the Camp Fire did. Calm and moderate days are unchanged, and ember draws are shared across paired what-ifs.

**Checked against the real Camp Fire (#15).** `eval.campfire` replays the 2018 fire from its NIST origin near Pulga, with a 19 m/s ENE wind easing to 6 m/s by the afternoon. It scores the replay against real data in `assets/scenarios/paradise/real/`:
- 2,105 NIST TN 2135 observations ("fire was here by time t");
- NIFC and NASA FEDS perimeters at 7.1 h and 11.5 h.

| First 12 h | Without spotting | With spotting |
|---|---|---|
| NIST-observed cells reached in time (±30 min) | 80% | **87%** |
| Lateness at the 75th-percentile observation | 15 min | **0 min** |
| IoU with the 7.1 h / 11.5 h perimeters | 0.54 / 0.63 | 0.55 / 0.64 |
| Burned area vs the perimeters | 1.73x / 1.53x | 1.71x / 1.51x |

That table was measured at `C2` 0.22, where the replay burned about 1.5–1.7x the real area because the flanks spread too wide. `C2` is now 0.3 (see "Choosing C2" below), which brings the perimeters to IoU 0.66/0.78 at 1.32x/1.16x the area.

**Marshall Fire** (`cd engine && uv run python -m eval.marshall`, #107): a second real fire, grass into suburb under a steady 15–20 m/s westerly, scored against the NASA FEDS perimeter at 2.5 h and the WFIGS final perimeter. It has no timed per-house observations. It agrees with the Camp Fire: every top result of the search has `C2` 0.4, which matches the 2.5 h area (0.9–1.0x, IoU ~0.39), where 0.22 burns 4–5x too much. At every setting, though, the sim keeps running east through Louisville to the map edge where the real fire stopped, so the final perimeter is a fuel and structure question (suburbs burn like grass here), not a wind one. Under the measured wind (`--measured`: NCAR Mesa Lab's 5-min record in the foothills, 11–19 m/s from about 245° through the afternoon, gusts to 40 m/s, #141) the verdict holds: 0.22 burns 1.9–4x the real 2.5 h area at any speed scale, while 0.3 at 0.8x the station's speed (IoU 0.46, area 1.09x) and 0.4 at 1x (IoU 0.41, area 0.85x) fit. NOAA's airport record downwind (KBJC) saw only 5–9 m/s from shifting directions, so the foothill station is the one that represents the fire's wind. Suburban fuel is per scenario (#144): Boulder County's irrigated suburbs burn at residential 0.25 and commercial 0.3, while Paradise's forested lots keep 0.9 (its replay needs 0.6 or more). Under the measured wind that takes the best Marshall final perimeter from IoU 0.19 at 2.7x the area to IoU 0.38 at 0.84x (C2 0.4), and from 5.2x to 4.4x at 0.22. What's left is shape: the sim misses the real fire's north-west and south flanks.

**Choosing C2.** Both fires want a narrower head than 0.22, but a higher `C2` also slows backing and flank spread at every wind, so ordinary-wind fires shrink. The sweep scored `C2` 0.22/0.3/0.4 against both replays (Marshall under the measured wind) and `eval.early_attack` (Paradise, 8 ignitions × 2 seeds, 3 h, NE wind). It also tried a floor on the wind factor, so flanking and backing never drop below a fraction of calm spread:

| `C2` | Camp IoU 7.1 h / 11.5 h (area) | Marshall 2.5 h IoU (area), 0.8x wind | No-crew acres at 3 / 8 / 13 m/s (burned out alone at 8 m/s) |
|---|---|---|---|
| 0.22 | 0.55 / 0.63 (1.73x / 1.53x) | 0.38 (1.81x) | 5,095 / 6,287 / 21,864 (12%) |
| **0.3** | **0.66 / 0.78 (1.32x / 1.16x)** | **0.45 (1.01x)** | **2,579 / 2,646 / 11,057 (25%)** |
| 0.4 | 0.68 / 0.80 (1.14x / 1.01x) | 0.41 (0.50x) | 883 / 831 / 4,925 (62%) |

`C2` is 0.3: close to 0.4 on the Camp Fire, the best Marshall fit, and fires on a moderate day still grow. At 0.4 most fires at 3–8 m/s burn out by themselves, which real timber fires don't. The floor (0.3, 0.5 or 0.7 of calm spread) made both replays worse at every `C2`: Camp IoU fell to 0.38–0.54 and Marshall's 2.5 h area rose to 1.4–3.6x, because it widens the flanks of strong-wind fires too. So there's no floor.

- **Cell states:** `unburnable`, `fuel`, `burning`, `burned`. A burning cell burns for k ticks, giving the fire front visible thickness.
- **Layers:** `heightmap` (→ slope), `fuel_type`, `fuel_density`, `suppression`, `roads`, `towns`.
- **Vectorized:** 8 shifted-array operations per tick (one per neighbor direction), restricted to the bounding box of the burning cells. A step on Paradise takes well under 1 ms.
- Wind is set from exercise control (`set_wind`). There is no physical wind knob.
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
- **Calibrated burn envelope (#12, `engine/uq/conformal.py`).** The console draws the forecast's outline as an envelope that promises at most 10% of the ground that newly burns by T+30 / T+60 falls outside it. The raw contours can't promise that: they assume the wind and tokens hold, and miss 11–31% (`eval.run`, the 50% line).
  - **How it holds:** each envelope shown is remembered and scored when its horizon passes, as burned area outside / burned area. An online conformal update (adaptive conformal inference, conformal risk control) moves one knob per horizon: the probability cutoff, then a margin of extra cells once the cutoff hits 1/N. The long-run miss stays near 10% even under shifts, after a short catch-up.
  - **Measured:** step 0.1, `eval.run`, 4 episodes per schedule, missed share over the whole run:

    | Wind | T+30 | T+60 |
    |---|---|---|
    | Steady | 9.3% | 8.8% |
    | Shift | 10.5% | 12.0% |
    | Gusty | 11.3% | 11.7% |

    In gusty wind no fixed cutoff gets under 14%, while the envelope ends at a cutoff near 1/32 plus a 3-cell margin.
  - **Per scenario:** the knob learns per scenario. A scenario switch restarts from `ENVELOPE_WARM`, because a new map is a new distribution and conformal promises only transfer within one. A map reset keeps what was learned.
  - **Real units:** misses are counted in area, so the promise keeps its meaning across resolutions.
  - **On the wire:** the `forecast_envelope` message carries the cutoffs, margins and running miss rates.
- **Calibrated time-to-impact ranges (#13, `ArrivalCalibrator` in `engine/uq/conformal.py`).** Each threatened town shows "fire likely arrives in 25–40 min (90%)".
  - **The range:** the long forecast's 5–95% arrival, widened or narrowed by an online conformal correction (CQR) per lead-time bucket (<30, 30–120, >120 min).
  - **Calibration units:** towns catch fire too rarely to calibrate on, so the units are town-sized disks (radius 8 cells) dropped on unburned ground. Each is scored, like a town, by the first time fire touches it. Single cells held their own 90% but transferred badly to towns.
  - **Censoring:** a disk the forecast never sees burn scores as the smallest miss it could be, which can only make the ranges too narrow.
  - **Measured** (`eval.arrival`, Paradise, 4 episodes per schedule, 4 h forecasts), calibrated coverage of real town arrivals:

    | Wind | Calibrated | Raw |
    |---|---|---|
    | Steady | **89%** | 93% |
    | Wind shift | **56%** | 47% |
    | Gusty | **75%** | 34% |

  - **Known limit: an unforecast wind shift.** Every range issued before it is wrong at once, and the correction only learns afterwards.
    - Per-rollout wind spread (±20%, ±20°) lifted the shift case to 68%, but gave half as many towns a range and dropped steady to 79%. Wider spread left almost no town bounded. The long forecast stays without spread.
    - The real fix is a wind forecast (e.g. HRRR), not more statistics.
  - **Where it shows:** `TownThreat.eta_lo_min` / `eta_hi_min` (null when too few simulations reach the town to bound it), the threat cards and inspector, and the commander's town table.
  - **Per scenario:** the calibrator learns per scenario. A reset clears in-flight forecasts and keeps what was learned. It covers the simulator's own uncertainty plus shifts in wind and tokens, not the model's error against real fires; that's what the replays (#15, #107) check.
- **Learned emulator (#113, optional `ml` extra):** a small U-Net (`engine/emulator/`, MLX, 1.5M parameters) trained on our own simulator to predict P(burn by T+30/T+60) from the fire state, per-direction spread (fuel, slope, wind) and the suppression schedule.
  - **Speed and accuracy:** it takes 6 ms against ~0.6 s for 32 rollouts. On held-out fires its 50% area overlaps the 64-rollout reference by 88% (the 32-run forecast: 94%), and it is calibrated in every probability bin.
  - **Instant preview:** when the wind, tokens or fire change, the engine shows its prediction at once, and the next Monte Carlo forecast replaces it.
  - **Screening:** recommendations take 48 front spots, keep the emulator's best 8 for the paired Monte Carlo, and only Monte Carlo numbers are shown. It helps most after a wind shift. Over two measurements of 32 cases each, the top recommendation's realized benefit went from 159/163 to 173/181 after a shift, and it beat a random spot 19 and 23 times out of 32 (15 and 17 without screening). In steady wind it was within noise: 708 → 780, then 702 → 690.
  - **Not used for decisions:** routing, alerts and the commander never use it.
  - **How it was trained:** about 5,750 random fires on paradise and valley, labelled by 64-rollout forecasts of the current fire model (ember spotting included, #118). It's retrained whenever the fire model changes; see the `fire-emulator` skill.

### Evacuation routing

- The road network is a networkx graph built from the scenario's roads.
- Edge cost is `length × (1 + λ · P(burn at the moment the bus reaches it))`. **The arrival-time-aware cost is the key idea:** routes avoid roads that *will* burn, not only roads burning now.
- Routes are recomputed whenever the forecast updates, and drawn as glowing paths.
- **Data:** `roads.json` and `towns.json` per scenario, from OpenStreetMap via `tools/osm_to_layers.py` (see the `generate-road-layers` skill). Towns carry approximate population and structure counts; `safe_zones` are the map-edge exits (Paradise: Skyway toward Chico, Clark Rd and Hwy 70 toward Oroville). The scenario layout above lists `roads.geojson`; it's `roads.json` in map coords instead.
- **Approximation** (`engine/routing/evac.py`): per-edge P(burn by t) is precomputed at 5-sim-minute bins in one vectorized pass over the forecast's `first_burn`, then a label-setting Dijkstra carries the bus's free-flow arrival time along each label's path and reads the bin at each edge's midpoint. Edges at P ≥ 0.9 by arrival are impassable. Not an exact time-dependent shortest path, but a replan of every town is tens of milliseconds.

### Evacuation order clock (#121)

Fire tools (WFDSS/FSPro, Technosylva) forecast the fire, alerting tools (Genasys Protect, formerly Zonehaven) send the order, and Watch Duty shows it to the public. None of them tells a commander *when* each town's order has to go out, given how long that town takes to empty. Trigger-boundary research (k-PERIL, WUI-NITY) compares available against required evacuation time, but only for offline planning. The clock (`engine/routing/clearance.py`) makes that comparison live, for every town:

- **Available time:** when the fire first enters the town's disk, per rollout of a *long* forecast: 32 rollouts to T+600 (`forecast.runner.LongForecaster`, two worker processes, 2–4 s). It's separate from the live T+60 ghost because Paradise takes about 8 hours to empty.
- **Required time:** 20 min to mobilise, then the time to drain the town's vehicles (1.6 people each) through the tightest road on its exits. Road capacity comes from the OSM class (primary 1,800 vehicles/h, secondary 1,100, tertiary 900, minor 600). Evacuees keep to the biggest roads within 15 min of the shortest drive, and use every exit within 20 min of the best, split by capacity. Each road is shared fairly between the ordered towns on it: a town with L_i vehicles on it is through after Σ_j min(L_j, L_i) / capacity. So ordering Magalia slows Paradise on Skyway, which is how Paradise gridlocked in 2018.
- **Output per town:** a status (watch, order soon, order now, late, evacuating, all out, trapped), the latest safe order time (10th-percentile arrival minus required time, so 90% of simulations have the last car out first), and P(last car out before the fire) with its Wilson interval. An `evacuate_now` briefing goes out once when a town's order comes due.
- **Orders:** the clock drives the evacuation cards in the console's decision queue: "Order X to evacuate" when the order comes due (order soon, now, or late), with the shared exit roads and P(last car out first), then "X is evacuating" with a Cancel. Before the long forecast lands, a town gets a card from the hour-ahead forecast instead. Both the cards and the town inspector send `order_evacuation`. Once mobilised, an ordered town empties at its share of the bottleneck, and those people count in the score.
- **Checked against the real Camp Fire** (`eval.evac_clock`, using NIST observed arrival as truth). For all 4 towns the real fire reached, the clock said to order at its first forecast. Its order-by time was 5–48 min earlier than the real deadline (conservative, never late). Yankee Hill stayed on watch. The one false alarm, Butte Creek Canyon, comes from the replay's known flank over-burn. The required times say no order after ignition could have emptied Paradise or Magalia before the fire arrived.
- **Not modelled:** an exit burning while cars are still on it (the router avoids likely-to-burn roads, and a cut recomputes the clock), smoke slowing traffic, contraflow, and per-zone orders within a big town (Paradise had 14 zones). The long forecast assumes the wind holds.

### Crew recommendations

- Sample candidate cells along the predicted fire front.
- For each candidate, run a few rollouts with a crew placed there, then rank by population and structures saved.
- Project the top 3 as pulsing markers labeled, for example, "Saves Pinecrest in 87% of simulations."
- **Uncertainty** (`engine/uq/mc.py`): every "k of N" carries a 90% Wilson interval, and each recommendation's benefit a paired t interval. A recommendation is shown only if the *low* end of its benefit is above zero, and the top two are re-run head to head when their intervals overlap. Town threat briefings use the interval's bounds instead of the raw share. This is sampling uncertainty only; whether the forecast's assumptions hold is for conformal calibration (#12, #13).
- **Look-ahead and act-by time.** Each crew is scored over the next **2 hours** (`REC_HORIZON_TICKS`). Half the candidate spots come from where the evacuation clock's long forecast expects fire in 60–120 min (`Engine.lookahead`). Each card says when to act: the fire's likely arrival at the crew's area (10th percentile across simulations) minus the crew's travel time, which is "send within N min" or "send now". On Paradise the first recommendation for a threatened town now comes about 2 hours before the fire, up from 37–53 min. At 13 m/s, crews dig in a median 98 min ahead (16 min before), and none arrive late (4 of 10 before). Cards show the town-save range ("likely 31–68%") and an acres range ("300–900 acres", 90%).
- **Caveat:** the intervals are sampling uncertainty under a held wind. After a wind shift, the 2-hour predicted benefit overstates the realized benefit about 3.4x (849 vs 252 in `eval.run --schedules shift`; about 2x at 1 h). In steady wind it's calibrated (1,641 vs 1,549). Conformal calibration (#12/#13) is the planned correction.

### Incident commander (LLM)

**Drafted orders and alerts (#132, `engine/commander/drafts.py`).** When the operator sends a unit or orders a town out, the engine drafts the message for the people who act on it. The drafts sit under Decisions in Monitor, where the operator sends, edits or dismisses each one. Nothing is delivered anywhere: "send" records a `draft_sent` event for the after-action review.
- **Unit orders:** a radio-style order with where, how soon, the task, the wind and embers, and the escape route.
- **Evacuation alerts:** a public alert in English and Spanish, within the 360-character limit of a Wireless Emergency Alert. Cancelling drops an unsent alert, or drafts a "lifted" notice if one went out.
- **Briefings:** on request.
- **Templates first, Claude second:** every draft starts as a template filled from engine facts, so it works without a key. With a key, Haiku rewrites unit orders and briefings from the same facts. The rewrite is kept only if it finished and every number and named place comes from those facts. Alerts stay templated, because public wording and its Spanish must match exactly.

The LLM gets **tools**, not a raw state dump, so its answers come from real simulation calls:

| Tool | Returns |
|---|---|
| `get_situation()` | Fire extent, threatened towns, time to impact, active resources, wind |
| `forecast_whatif(wind_dir, wind_speed, horizon)` | Forecast summary under the hypothetical conditions |
| `evaluate_placement(token_type, x, y)` | Expected outcome change from placing a resource |
| `get_routes()` | Current evacuation routes and their risk |

- Triggered by events (town threatened, road cut) for proactive briefings, and by typed questions.
- Answers are kept to about two sentences. In-app text-to-speech was removed (#138); the text messages are what an external TTS would read if speech is wanted.
- Uses a fast model for low latency.

### Game layer

- **Scenarios:** two real fires: Paradise, CA (2018 Camp Fire) and Marshall, CO (2021 Marshall Fire, Superior and Louisville).
- **Limited resources:** for example 3 crews, 2 water drops (with cooldown), and 1 firebreak, which forces tradeoffs.
- **Scoring:** people evacuated, structures saved, acres burned.
- **Scenario timer** and an end-of-round summary.
- **Attract mode:** an idle animated state that draws judges in.

As built (`engine/sim/game.py`):

- **Sandbox vs round.** Outside a round nothing is limited or timed, so virtual table mode stays free play. `start_round` resets the map, ignites at the scenario's ignition point and turns the limits on; the round ends on time, when nothing is burning, or on `end_round`, and then the fire freezes so the summary matches the map. `reset` returns to the sandbox.
- **Limits** count tokens on the table per type (3 crews, 2 water, 1 firebreak, 2 buses). The first ones placed take effect; any over the limit do nothing and are listed in `score.inactive_tokens` so the UI can grey them out.
- **Scoring:** acres burned from burning and burned cells; structures lost as each town's structures times the share of its burnable disk that has caught; people evacuated by evacuation orders (at the clock's outflow, #121) and while an in-limit bus sits inside a town whose route isn't cut (a stand-in until buses drive their routes).
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
- Typed questions in, briefings out as text
- Proactive event-driven briefings

**Exit:** a judge asks "What if the wind shifts west?" (typed) and gets an answer backed by a real forecast.

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
  - corner holders for the calibration ArUco markers, kept off the terrain so they don't break immersion. L-shaped holders pin into the board's outer walls with the same filament pins, so they never move. The marker is printed into each holder's top in black on white (`marker_holders.3mf`, two colours on the AMS), so there's no paper to glue on crooked
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
| Vision | Calibration, token tracking, 3D projection | 2, 7 |
| Sim | Fire CA, terrain layers, suppression, rollouts | 1, 3, 4 (forecaster) |
| AI | Routing, recommendations, commander, uncertainty | 4 (routing), 5 |

---

## Hardware

- Projector (1080p, short-throw helps), mounted pointing straight down
- 1080p webcam mounted next to the projector
- Terrain tiles in matte white or light-gray PLA
- Printed tokens with laminated ArUco markers
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

Judging is virtual, so the demo is a recorded video. The full 3-minute script, shot flow and footage list are in [`tools/demo_video/SCRIPT.md`](tools/demo_video/SCRIPT.md); the outline below is the short version. Lead with the operator console; the table appears as the stand-in for the real world seen from above, like drone footage. Record the console with `?demo=1`: start the fire from exercise control off-camera, slow the clock to show a feature, speed it up to let the fire run, and turn on Autopilot where clicking every card would drag. The Camp Fire scenario outruns any operator above 1× (10 sim-minutes a second), so most of the video runs at 0.25–0.5×.

1. Open on the table under the projector, a fire starting at the Camp Fire origin: "this is what a drone sees."
2. Cut to the operator console, Monitor. The decision queue fills: Concow likely to see fire in about 40 minutes, evacuate via Highway 70; crew recommendations with stations and ETAs. The town board shows every town's time until fire, with ranges.
3. Dispatch a recommendation. The unit drives in from its station on the map; the forecast credits it from its arrival.
4. Plan mode: "what if the wind swings west?" Dial it in, add a dozer line, and watch the map shade what the plan saves against doing nothing, with intervals. Dispatch the plan.
5. The wind really shifts (exercise control). Routes reroute, a road is cut, the queue re-sorts, and the commander briefs it. Ask the commander a question out loud.
6. Review: the outcome town by town (and, with #124, what the decisions bought against doing nothing). Close with the Camp Fire replay against the real perimeter.
