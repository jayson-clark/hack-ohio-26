# Demo video: script and shot flow (3:00)

The plan for the submission video. The console footage comes from the takes in `takes/` (see `README.md`). The table and agent-board shots are filmed by hand (shot list below). **This is a draft for review.** Comment on the PR or reply on the agent board (`#general`, "demo video script").

## The idea in one line

Fireline turns a wildfire forecast into the operator's decisions: who to evacuate, where to send crews, and what each choice buys.

## Rules we're following

These come from organizer guidelines and screencast practice; sources are in the PR.

- **The product is on screen within 10 s.** No team slide or logo up front.
- **About 55% of the runtime is the live console.** It plays as one continuous incident (the Camp Fire), not a feature tour.
- **The voiceover is a real human voice, about 400 words at roughly 140 wpm.** No TTS. Music is optional and kept well under the voice.
- **Narrate what the viewer can't see** (why it matters, how it's computed), not "now I click Dispatch".
- **Never speed footage up silently.** The sim speed is the badge in the top-right corner, and the takes already show it. Cut waits rather than speeding them up.
- **Zooms:**
  - Open each segment wide for about 2 s so the viewer gets their bearings.
  - Then zoom 2.2× (depth 4) on the region the voiceover is about, or 3.5× (depth 5) to read a single card.
  - Move between nearby targets with a pan, not by zooming out and back in.
  - Hold each zoom at least as long as its sentence.
- **Burn in captions.** Many judges watch muted. Keep them to two lines and about 17 characters a second.
- **Use one concrete number per claim and name the model.** Avoid vague AI language.

## Timeline

Times are in the final cut. "Take" names a file in `takes/`, and `A·1` means take A, scene 1. VO is the voiceover. The VO comes to about 415 words (about 2:57 at 140 wpm, so trim it if the read runs long); time it read aloud and cut lines before speeding anything up.

| Time | Picture | VO | On screen |
|---|---|---|---|
| **0:00–0:12** Cold open | `A·1`: the fire leaves Pulga, wide for 2 s, then 2.2× on the fire and its forecast bands | "November 8th, 2018. A fire starts near Pulga, California. By nightfall it has burned through Paradise and killed 85 people." | Caption only. No title yet |
| **0:12–0:24** The problem | `A·2`: Paradise's inspector, "3h 45m past the latest safe order time" | "Paradise needed almost eight hours to evacuate. By the time anyone saw the fire, that order was already late. Commanders make these calls from radio traffic and paper maps." | Title card at 0:22, 1.5 s: **Fireline**, "wildfire decisions, ahead of the fire" |
| **0:24–0:34** The world | **Table, wide**: the projector paints the live fire on the 3D-printed terrain | "This is our stand-in for the real world: a 3D-printed model of the Camp Fire's terrain. The projector paints the live fire, and the camera above it plays the drone." | Lower third: "Physical table: stands in for drone footage" |
| **0:34–0:48** Forecast | `A·1` again, later in the take: bands growing toward Concow | "Fireline runs 32 fire simulations every few seconds, on real terrain, fuel and wind. The bands are where the fire will likely be in 30 and 60 minutes, calibrated so no more than one acre in ten burns outside them." | |
| **0:48–1:00** Decide: evacuate | `B1`: 3.5× on the queue's first card, Order evacuation, the queue re-sorts (Paradise, hours overdue, rises), pan to "Pulga is evacuating" and the drafted alert | "Every decision lands in one queue, most urgent first, and each card says why: how long the town needs, by which road, and how often the last car beats the fire. Order it, and the public alert is already drafted, ready to send." | Badge: 0.25× |
| **1:00–1:14** Decide: crews | `B2·1` → `B2·2`: read the crew recommendation, Dispatch, the unit drives in at 1× | "Crew recommendations come with the station, the drive time and the acres saved. We only show one when even the low end of its range helps. Dispatch, and the forecast credits the crew from the moment it arrives." | |
| **1:14–1:20** Table cutaway | **Table, close**: a hand sets a crew token on the terrain; hard cut to the console as the unit appears | "On the table, a crew is a token the camera picks up, the way a drone would spot an engine." | |
| **1:20–1:46** What if | `C·1` the wind-direction slider at 3.5×; `C·2` crews, a dozer line and the green "saved" shading; pan to the outcome numbers; `C·3` dispatch the plan | "Plan mode answers the question commanders actually ask: what if the wind swings round to the east? Add crews and a dozer line, and Fireline runs the plan and doing nothing on the same simulations, so the difference is the plan, not luck. Green is what it saves. One click sends the whole plan." | Badge: "Paused · planning" |
| **1:46–2:02** The fire moves | `D·1`: 2×, the fire runs west and cuts the road out of Paradise, and routes turn and reroute; `D·2`: the commander's dock | "When the fire cuts a road, every evacuation route replans on its own. The commander, Claude Haiku, briefs each change in plain words, and every number and place it names is checked against the engine first." | Badge: 2× |
| **2:02–2:12** Autopilot and Review | `E·1` autopilot countdown cards (5 s), then `E·3` Review | "Autopilot lets us run the whole incident hands-off, and Review scores it afterward, town by town." | Badge: 0.5× → 4× |
| **2:12–2:34** Does it hold up? | Card, Camp Fire replay: the sim's perimeter over the real NIFC/FEDS perimeters (from `eval.campfire`), plus one line of numbers | "We checked it against the real Camp Fire. Our replay overlaps the real perimeters at 7 and 11 hours by 0.66 and 0.78. And against NIST's timeline, the evacuation clock flagged every town the fire reached at its first forecast, before the real deadline." | "IoU 0.66 / 0.78 vs real perimeters", "4 of 4 towns flagged on time" |
| **2:34–2:44** How we built it | Agent board at hack.apps.jaysonc.dev, live: agents posting findings and claiming issues (8 s), then a one-frame architecture diagram | "Four of us built this during the hackathon with a team of coding agents that shared what they learned on a live board: 87 merged pull requests." | Lower third: "Agent board: how the team's agents coordinated" |
| **2:44–3:00** Close | **Table, wide, slow push-in** (or console Review wide) → end card | "Fireline: see the fire, decide ahead of it, and know what every decision buys. Thanks for watching." | End card: Fireline · team names · repo URL |

## Footage to get

**Console (scripted).** `make demo-video` records all six takes into `~/Movies/fireline-demo/`. The cut uses:

| Take | Length | Used for |
|---|---|---|
| `A-see-it` | ~30 s | Cold open, problem, forecast |
| `B1-order-evacuation` | ~13 s | Evacuate |
| `B2-dispatch-crew` | ~25 s | Crews |
| `C-plan-what-if` | ~40 s | What if (trim the wait for "Saves") |
| `D-road-cut-commander` | ~28 s | Road cut and commander |
| `E-autopilot-review` | ~45 s | Autopilot (first 5 s) and Review (last 6 s) |

**Table (by hand).** Shoot on a tripod with the room dark enough for the projection to read, with no handheld pans. Use the camera, not a phone, for anything that's on screen for more than a few seconds.

1. Wide, locked off, 10 s: the whole table with the fire spreading at 1×.
2. Close, 6 s: a hand places a crew token on the slope; the projection updates around it.
3. Slow push-in, 8 s, for the close.
4. Optional: picture-in-picture of the table and the console's camera view together, to show the camera tracking.

**Agent board (Recordly, by hand).** Record about 15 s of https://hack.apps.jaysonc.dev during a busy stretch. Use about 8 s of it. Blur any tokens and DMs.

**Cards and diagrams.**
- Title card.
- Camp Fire replay overlay: export a frame from `eval.campfire`.
- Architecture diagram: engine (sim, Monte Carlo forecast, routing, commander), then WebSocket, then console and projector.
- End card.

## Open questions for reviewers

1. Is the cold open too dark for a hackathon? The alternative is to open on the table shot and save the Camp Fire facts for 0:12.
2. Should the commander segment show a typed question and its answer (`ask`)? It's more impressive but riskier on camera, and it adds about 8 s.
3. Does the agent-board beat earn its 10 s, or should it go into the Devpost write-up instead?
4. Who narrates? We need one clear voice, a quiet room and a decent mic.
5. The replay numbers (IoU, 4 of 4 towns) come from `PLAN.md`. Sim owners, are they still current after #179 and #187?
