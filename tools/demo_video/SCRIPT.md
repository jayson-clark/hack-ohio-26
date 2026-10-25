# Demo video script (3:00)

The one script for the submission video. The read-along table below is the video's clock: the narrator records the voiceover to it with the prompter, and the editor drops each shot into its slot. It merges the read-along draft (#219) with v3 (#216): the simulation, honest uncertainty, the table as a stand-in for a drone, and the agent board.

```sh
make prompter     # http://127.0.0.1:8792/prompter.html: Space starts, words fill in time
```

**The thread:** a forecast is only useful if you know when to trust it.

**Tone:** present it like a thesis talk, not a trailer: the question, the model, how far to trust it, what it's for, how it was built. Every number is in "Claims and sources" with where it comes from. If a number changes, change it there and in the line.

## Read-along

Times are in the final cut. A line's words fill evenly between its start and end, and the gaps between lines are breaths. Lines run at 2.0–2.5 spoken words a second (about 135 a minute). `G·2` means take G, scene 2.

| Start | End | Picture | Line | On screen |
|---|---|---|---|---|
| 0:00 | 0:08 | `A·1` wide: the fire leaving Pulga | Fireline is decision support for wildfire incident command. This is a replay of the 2018 Camp Fire. | Lower third: Fireline |
| 0:08 | 0:17 | `A·1`: 2.2× on the fire and its forecast bands | The real fire reached Paradise in about eighty minutes; emptying it takes hours. So when must each town be ordered out? | Badge: 0.5× |
| 0:18 | 0:28 | `A·1`, later: the bands growing toward Concow | Underneath is a fire model on real terrain, fuel and roads, at ninety-four metre cells, with embers that jump ahead in strong wind. | |
| 0:29 | 0:36 | Insert: Camp Fire replay over the real perimeters | We tested it by replaying two real fires, rather than tuning it by eye. | |
| 0:37 | 0:43 | Insert, Marshall row | On the Marshall Fire, it matches the burned area at two and a half hours. | Marshall Fire, 2.5 h: area 1.01×, IoU 0.45 |
| 0:44 | 0:51 | Insert, Camp Fire row | On the Camp Fire, it gets the direction right, but burns about twice the real area. | Camp Fire, 7 h / 11.5 h: IoU 0.39 / 0.53 (best replay settings; 0.35 / 0.46 at defaults), about 2× the area |
| 0:52 | 1:01 | `B1`: 3.5× on Pulga's evacuation card | Every number comes from running the fire forward thirty-two times, so we show it as a count, like seventeen of thirty-two. | 17 of 32 simulations |
| 1:02 | 1:10 | `B2·1`: the crew recommendation card | A crew card appears only when even the pessimistic end of its range still helps. | Crew cards: 16 paired runs, shown only if the low end is above zero |
| 1:11 | 1:21 | `G·1`: Concow's label with its calibrated range | A count can't see a wind shift, so the outline and town ranges are calibrated as the fire burns, against what actually burned. | Fire in 1h 07m–1h 37m |
| 1:22 | 1:31 | `G·1`: the legend's live miss rate | The outline aims for one acre in ten of new fire outside it, and the legend shows how well that's holding. | Target 10% outside · measured 11–13% |
| 1:32 | 1:40 | `G·2`: the wind shifts; the legend turns orange, Widening; the outline grows | When the wind shifts, that number rises, and the outline widens to catch up. | Badge: Wind shift NE → ESE |
| 1:41 | 1:50 | Card: the limits, over the console | Town arrival ranges hold ninety-five percent of the time in steady wind, but about two in three right after a shift. | Steady wind 95% · after a shift 67% |
| 1:51 | 2:00 | Card, next lines | We don't forecast the wind or fuel moisture, and the ranges cover the simulator, not its error against real fires. | No wind forecast · no fuel moisture · no house-to-house spread |
| 2:01 | 2:09 | `B1`: Order evacuation; the queue re-sorts; the drafted alert | Within those limits, decisions land in one queue, most urgent first, and an evacuation order drafts the alert. | Badge: 0.25× · Replay check: all 4 towns the fire reached were called at the first forecast, 1–43 min before the real deadline |
| 2:10 | 2:16 | `B2·2`: Dispatch; the crew drives in | A dispatched crew is credited in the forecast from when it arrives. | Badge: 1× |
| 2:17 | 2:25 | Phone: the table, wide and locked off, the fire spreading | On a real fire, the view comes from a drone. Our stand-in is a 3D print of the terrain. | Lower third: Physical table, standing in for drone footage |
| 2:26 | 2:33 | Split, synced on the slate: phone (left), `F·2` camera view (right) | The projector paints only ground and fire, and the camera overhead plays the drone. | Labels: The table · What the camera sees |
| 2:34 | 2:43 | `F·3`: the map layers come on over the photo; `F·4`: the console on the same feed | It corrects for the terrain's height, straightens the view into a map, and the console works from that picture. | |
| 2:44 | 2:54 | Agent board, live: a question and its answer, a claim, a merge | Four of us built this, each with coding agents that shared findings and claimed work on one live board. | hack.apps.jaysonc.dev · 108 PRs [count on the day] |
| 2:55 | 3:00 | Phone: the table, slow push-in → end card | Fireline: know when to act, and how far to trust the forecast. | End card: Fireline · team · repo URL |

## Before recording

- **`.env`:** `EMULATOR=off` (#213), so every forecast, outline and number is the 32-run Monte Carlo and its calibration; the engine log says "fire emulator switched off". `FIRE_SEED=7` (#220), so every take starts from the same fire and it doesn't die out early. The camera settings (`CAMERA_EXPOSURE=20`, `CAMERA_GAIN=0`, `CAMERA_WHITE_BALANCE=5000`) for take F.
- **Restart the engine before take G.** Miss rates carry over from earlier rounds on the map, so an earlier shift leaves the legend orange.
- **Update the counts on the day:** PRs (`gh pr list --state merged --limit 500 --json number -q length`) and the board's findings.

## Recording the voiceover

1. `make prompter` and open the link. Put it on a second screen at eye level.
2. Start the audio recording (QuickTime: File → New Audio Recording, or a phone), then press Space. The prompter counts in 3-2-1, then runs the clock.
3. Read the highlighted line. Its words fill in time with the cut, so keep pace with the fill rather than running ahead. If you fall behind, pause at the next gap (Space), breathe and resume. The gaps are there for that.
4. If one line goes wrong, re-record just that line: ← and → step between lines, and each line starts at its own time, so it drops back into its slot.
5. The prompter's **Captions** button downloads the lines as an `.srt` with the same times, for burned-in captions (many judges watch muted).

The voice should be one person, one take, in a quiet room. Music, if any, stays well under it.

## The synced table shot

The same moment from two sides: the real table on a phone, next to what the overhead camera made of it. Take F starts with a slate for this: the projector flashes its test grid for one second while the fire is paused. The grid is bright cyan, so it's obvious in both the phone video and the camera view on screen.

Record the phone in its own Camera app, started before `make demo-video TAKES=F`, then build the side-by-side with `tools/demo_video/split.py` (see its docstring). It finds the grid flash in both recordings and lines them up, crops the phone to the print, and frames both panels on the takes' wallpaper with their labels and the speed badge:

```sh
cd engine && uv run --with pillow python ../tools/demo_video/split.py \
    "<Recordly recordings>/recording-….mp4" ~/Downloads/IMG_….MOV ~/Movies/fireline-demo/F-split-synced.mp4 --from 6.6 --to 41
```

Recordly's own webcam (a Continuity Camera phone) also works (`--mirror --offset 0`), but it records at 640×480. Turn Do Not Disturb on first: switching the phone between Continuity Camera and its Camera app leaves a "Disconnected" banner over the app for the whole take.

Either way: a tripod, landscape, the print filling as much of the frame as you can, the room dim enough for the projection to read, and nobody in frame or on the mouse and keyboard until the take ends. Use the phone for 2:17–2:33 and the closing push-in (a slow digital push-in on a wide shot is fine). Cut the take to its slots rather than speeding it up: the burned-in 0.5× badge would be wrong at any other speed.

## Footage

| Source | Used at | Notes |
|---|---|---|
| `A-see-it` | 0:00–0:28 | Scene 1 only; its later part has the bands growing toward Concow |
| Camp Fire replay insert | 0:29–0:51 | A frame from `eval.campfire`: the sim over the real NIFC/FEDS perimeters, with the two result rows |
| `B1-order-evacuation` | 0:52–1:01, 2:01–2:09 | The card close-up first, then the order and re-sort |
| `B2-dispatch-crew` | 1:02–1:10, 2:10–2:16 | Scene 1's card, then scene 2's dispatch |
| `G-calibration-wind-shift` | 1:11–1:40 | Scene 1 (paused: Concow's range, the legend), then scene 2 (the shift) |
| Limits card | 1:41–2:00 | Over the console, dimmed |
| Phone, table | 2:17–2:33, 2:55–3:00 | Shot during take F (above) |
| `F-table-camera` | 2:26–2:43 | Scene 1 is the slate; cut it after syncing |
| Agent board | 2:44–2:54 | About 15 s of https://hack.apps.jaysonc.dev during a busy stretch (Recordly, by hand); blur tokens |
| End card | 3:00 | |

Takes C, D and E aren't in this cut. They stay in `takes/` for other uses. Never speed footage up silently: the sim-speed badge is burned into each take, so cut waits instead of speeding them.

## Claims and sources

| Line says | Source |
|---|---|
| The fire reached Paradise in about 80 minutes; emptying it takes hours | `eval.evac_clock` (NIST arrival 80 min after ignition; the model needs 934 min to clear Paradise on the extended map) |
| Real terrain, fuel and roads, 94 m cells, embers in strong wind | `PLAN.md`, fire model: DEM terrain (`tools/dem_to_assets.py`), OSM fuel and roads, 93.75 m cells, ember spotting above 9 m/s |
| Marshall: matches the area at 2.5 h | `PLAN.md`, Marshall Fire (`eval.marshall`): 2.5 h IoU 0.45 at 1.01× the area at `C2` 0.3 |
| Camp Fire: direction right, about twice the area | Board [258] and `PLAN.md` "On the extended map (#200)" (`eval.campfire`, 512×480 map, rebuilt truth): best of the 432-setting search at `C2` 0.3 is IoU 0.39 / 0.53 at 2.2× / 1.7×; the default replay is 0.35 / 0.46 at 2.55× / 2.0×. The old map's 0.66 / 0.78 doesn't hold |
| 32 runs; shown as a count | `PLAN.md`, forecasting: the live forecast is 32 rollouts; counts carry 90% Wilson intervals |
| Crew card only when the pessimistic end helps | `PLAN.md`, recommendations: shown only if the low end of the paired interval is above zero (16 paired runs on the card) |
| Outline aims for 10% outside; measured 11–13% | `PLAN.md`, "Calibrated burn envelope" (online conformal, `eval.run`): 10.9% steady, 11.7 / 12.6% shift, 12.4 / 12.2% gusty (T+30 / T+60) |
| Arrival ranges: 95% steady, about two in three after a shift | `PLAN.md`, arrival ranges (`eval.arrival`): 95% steady, 67% shift, 65% gusty |
| No wind forecast or fuel moisture; ranges cover the simulator | `PLAN.md`: the long forecast assumes the wind holds; "not the model's error against real fires"; board [258] on fuel moisture |
| The camera corrects for height and straightens the view | `PLAN.md`, height parallax (solvePnP camera pose, rays to the heightmap) and the rectified orthophoto (#194) |
| Projector paints only ground and fire | `PLAN.md`, projector: drone layers by default (#198) |
| Clock: all 4 towns called at the first forecast, 1–43 min early | `cd engine && uv run python -m eval.evac_clock` on `main` after #219 (Paradise 39, Magalia 22, Concow 43, Pulga 1 min before the real deadline; Butte Creek Canyon is the one false alarm) |
| PR count | `gh pr list --state merged`, on the day (108 at the time of writing) |
