# Demo video script (3:00)

One script to read from. The read-along table below is the video's clock: the narrator records the voiceover to it with the prompter, and the editor drops each shot into its slot. The footage comes from the takes in `takes/` (see `README.md`) plus a phone shot of the table.

```sh
make prompter     # http://127.0.0.1:8792/prompter.html: Space starts, words fill in time
```

**Tone.** Present it like a thesis talk, not a trailer: the question, how the system answers it, how well that holds up, and where it doesn't. Every number is in "Claims and sources" with where it comes from. If a number changes, change it there and in the line.

## Read-along

Times are in the final cut. A line's words fill evenly between its start and end; the gaps between lines are breaths. Pace is about 135 words a minute. `A·2` means take A, scene 2.

| Start | End | Picture | Line | On screen |
|---|---|---|---|---|
| 0:00 | 0:08 | `A·1` wide: the fire leaving Pulga | Fireline is decision support for wildfire incident command. This is a replay of the 2018 Camp Fire. | Lower third: Fireline |
| 0:08 | 0:15 | `A·1`: zoom on the fire and its forecast bands | It started near Pulga, California, under a north-easterly wind of about nineteen metres per second. | Badge: 0.5× |
| 0:16 | 0:29 | `A·2`: Paradise's inspector, past its latest safe order time | We asked a narrow question: what is the latest time each town can be ordered out, with the last car clear of the fire in nine runs out of ten? | |
| 0:30 | 0:40 | Phone: the table, wide and locked off, the fire spreading | To test it on something physical, we built a stand-in for aerial footage: a 3D-printed model of the terrain under a projector. | Lower third: Physical table, standing in for drone footage |
| 0:41 | 0:49 | Split, synced on the slate: phone (left), `F·2` camera view (right) | The projector paints the simulated fire, and an overhead camera films it, as a drone would. | Labels: The table · What the camera sees |
| 0:50 | 0:58 | `F·3`: forecast, routes and towns come on; `F·4`: the console, Map then Drone | Fireline draws its forecast, routes and towns over that photo, and the console uses the same feed. | |
| 0:59 | 1:07 | `F·5`: the console's map on the drone photo, the bands around the fire | The forecast is thirty-two runs of a cellular fire model on real terrain, fuel and wind. | |
| 1:08 | 1:17 | `A·1`, later: the bands growing toward Concow | Its outline is recalibrated as the fire burns, aiming for at most one acre in ten of new fire outside it. | |
| 1:18 | 1:28 | `B1`: the queue's first card, read close | For each town, the clock compares the fire's arrival in each run with the time to drain its cars through the tightest exit. | Badge: 0.25× |
| 1:29 | 1:37 | `B1`: Order evacuation; the queue re-sorts; the drafted alert | The card reports how often the last car gets out first, and the order drafts the public alert. | |
| 1:38 | 1:50 | `B2·1` the crew recommendation, `B2·2` Dispatch and the drive-in | Crew recommendations compare runs with and without the crew, from real stations, and appear only when the low end of the confidence interval still saves ground. | Badge: 0.25× → 1× |
| 1:51 | 1:58 | `C·1`: the wind slider swings east | Plan mode tries a scenario before committing to it: here, the wind turning east. | Badge: Paused · planning |
| 1:59 | 2:08 | `C·2`: crews, a dozer line, the green saved area and the outcome numbers | The plan and doing nothing share the same random draws, so the green area is the plan's effect, not chance. | |
| 2:09 | 2:21 | `D·1` the road cut and replan at 2×, `D·2` the commander's dock | When fire closes a road, routes and clocks are recomputed. Claude Haiku drafts the briefings, and a draft is kept only if its numbers all come from the engine. | Badge: 2× |
| 2:22 | 2:34 | Card: results, over `E·3` Review dimmed | We checked it against the real fire. On NIST's timeline, the clock called for all four towns the fire reached at its first forecast, before the real deadline. | 4 of 4 towns flagged at first forecast, 5–48 min early |
| 2:35 | 2:45 | Card, next row | The fire model is weaker: perimeter overlap of 0.35 and 0.46, at two to two and a half times the area. | Camp Fire IoU 0.35 / 0.46 at 7.1 h / 11.5 h, 2.0–2.6× the area |
| 2:46 | 2:55 | Card, last rows | Its uncertainty covers the simulator, not its error against real fires, and after a wind shift it overstates crew benefit. | Forecast outline misses 11–13% (target 10%) · Crew benefit after a shift: predicted 3.4× realized |
| 2:56 | 3:00 | Phone: the table, slow push-in → end card | Fireline: forecasts turned into decisions, with the limits stated. | End card: Fireline · team · repo URL |

## Recording the voiceover

1. `make prompter` and open the link. Put it on a second screen at eye level.
2. Start the audio recording (QuickTime: File → New Audio Recording, or a phone), then press Space. The prompter counts in 3-2-1, then runs the clock.
3. Read the highlighted line. Its words fill in time with the cut, so keep pace with the fill rather than running ahead. If you fall behind, pause at the next gap (Space), breathe and resume. The gaps are there for that.
4. If one line goes wrong, re-record just that line: ← and → step between lines, and each line starts at its own time, so it drops back into its slot.
5. The prompter's **Captions** button downloads the lines as an `.srt` with the same times, for burned-in captions (many judges watch muted).

The voice should be one person, one take, in a quiet room. Music, if any, stays well under it.

## The synced table shot

The same moment from two sides: the real table on a phone, next to what the overhead camera made of it. Take F starts with a slate for this: the projector flashes its test grid for one second while the fire is paused. The grid is bright cyan, so it's obvious in both the phone video and the camera view on screen.

1. Phone on a tripod, landscape, 60 fps if it has it, framed on the whole table. Dim the room until the projection reads well on the phone. No handheld moves.
2. Start the phone recording, then run `make demo-video TAKES=F`. Stay out of the frame and off the mouse and keyboard until it ends.
3. In the editor, line the two clips up on the first frame of the grid flash, then cut the slate off both.
4. Use the phone clip for 0:30–0:49 and the closing push-in (a slow digital push-in on the wide shot is fine).

## Footage

| Source | Used at | Notes |
|---|---|---|
| `A-see-it` | 0:00–0:29, 1:08–1:17 | Scene 1's later part has the bands growing toward Concow |
| `F-table-camera` | 0:41–1:07 | Scene 1 is the slate; cut it after syncing |
| Phone, table | 0:30–0:49, 2:56–3:00 | Shot during take F (above) |
| `B1-order-evacuation` | 1:18–1:37 | |
| `B2-dispatch-crew` | 1:38–1:50 | Trim the wait before the unit moves |
| `C-plan-what-if` | 1:51–2:08 | Trim the wait for "Saves" |
| `D-road-cut-commander` | 2:09–2:21 | |
| `E-autopilot-review` | 2:22–2:55 | Only scene 3 (Review), dimmed under the results card |
| Results card, end card | 2:22–2:55, 3:00 | Text from "Claims and sources" |

Never speed footage up silently. The sim-speed badge is already burned into each take; cut waits instead of speeding them.

## Claims and sources

Check these against `main` before recording; the commands re-measure them.

| Line says | Source |
|---|---|
| Camp Fire replay: started near Pulga under about 19 m/s from the north-east | `PLAN.md`, "Checked against the real Camp Fire" (`eval.campfire`: NIST origin, 19 m/s ENE easing to 6 m/s) |
| Latest safe order time = last car out first in 9 of 10 runs | `PLAN.md`, evacuation clock: 10th-percentile arrival minus the time to clear |
| 32 runs of a cellular fire model on real terrain, fuel and wind | `PLAN.md`, forecasting: the live forecast is 32 rollouts; terrain from a DEM (`tools/dem_to_assets.py`), fuel from OSM land cover (`tools/osm_to_fuel.py`) |
| Outline aims for at most 10% of new fire outside; measured 11–13% | `PLAN.md`, "Calibrated burn envelope" (online conformal, `eval.run`, extended Paradise map) |
| Drain time through the tightest exit | `PLAN.md`, evacuation clock: 20 min to mobilise, then vehicles through the bottleneck road |
| Crew cards appear only when the low end of the interval is above zero | `PLAN.md`, recommendations: paired t interval on the benefit |
| Plan and doing nothing share random draws | `PLAN.md`, Plan (#123): paired simulations |
| Claude Haiku drafts; kept only if its numbers come from the engine | `engine/commander/agent.py` (`DEFAULT_MODEL`), `PLAN.md` "Templates first, Claude second" |
| 4 of 4 towns at first forecast, 5–48 min before the real deadline | `PLAN.md`, evacuation clock (`cd engine && uv run python -m eval.evac_clock`). **Re-run on the extended map (#200) before recording** |
| Perimeter IoU 0.35 / 0.46 at 2.0–2.6× the area | `PLAN.md`, "On the extended map (#200)": the replay at its default settings (`eval.campfire`). The best of the 432-setting search is 0.39 / 0.53, and the old map's 0.66 / 0.78 no longer holds; quote the default |
| Uncertainty covers the simulator, not model error | `PLAN.md`, arrival ranges: "not the model's error against real fires" |
| After a wind shift, predicted crew benefit is 3.4× realized | `PLAN.md`, recommendations caveat (849 vs 252, `eval.run --schedules shift`) |

## What changed from the first draft

- **One script.** The timeline, voiceover and shot list are one table, read with the prompter, so the read and the cut share a clock.
- **A plainer tone.** No death toll in the first line and no slogans. It opens on what Fireline is and the question it answers, and ends on results and limits.
- **Current, fair numbers.** The perimeter IoU is the extended map's default replay (0.35 / 0.46), not the old map's 0.66 / 0.78, and the line says the fire model is the weaker part. The outline's measured 11–13% miss rate and the crew-benefit caveat are on screen.
- **The table gets a real segment** (0:30–0:58), with the synced phone and camera views and a slate to line them up.
- **Cut for time:** the autopilot beat (Review stays, as the results backdrop) and the agent board, which fits better in the Devpost write-up.
