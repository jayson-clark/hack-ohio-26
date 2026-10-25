# Fireline demo video, draft v3 (3:00): simulator-only calibration

A rework of the #206 script around four things: the simulation, honest uncertainty, the table as a stand-in for a drone, and the agent board. Console takes reuse `tools/demo_video/takes/`.

**What changed from v2:** we record with the simulator only (`EMULATOR=off`, PR #213), so every forecast, outline and number on screen comes from the 32-run Monte Carlo and its conformal calibration, never from the learned emulator. The numbers are re-measured on the extended maps (#200, #211) with the valley fuel fix (#212). All numbers are measured (PR #214).

**Thread through the whole video:** a forecast is only useful if you know when to trust it.

| Time | Picture | Voiceover | On screen |
|---|---|---|---|
| **0:00–0:10** Cold open | Take A·1: fire leaves Pulga, forecast bands growing | "November 8th, 2018. A fire near Pulga, California, reaches Paradise in about eighty minutes. Paradise needed eight hours to evacuate." | Caption only |
| **0:10–0:16** Title | Title card | "This is Fireline: decisions ahead of the fire, and honest about what it doesn't know." | **Fireline** |
| **0:16–0:40** The simulation | Take A·1 wide, then 2.2× on the bands. Insert: Camp Fire replay overlay, sim vs the real NIFC/FEDS perimeters | "Underneath is a fire model on real terrain, fuel and roads, at 94-metre cells, with embers that jump ahead in strong wind. We didn't tune it by eye: we replayed two real fires. On the Marshall Fire it matches the burned area at two and a half hours. On the Camp Fire it gets the direction and the towns right, but burns about twice the real area, and we'll show you how the software copes with that." | "Camp Fire IoU 0.39 / 0.53, ~2× the real area", "Marshall 2.5 h area 1.01×" |
| **0:40–1:20** Honest uncertainty | Take A·2 / B2: a recommendation card reading "in 24 of 32 simulations", the forecast outline, then the layers menu showing "Forecast outline: X% fell outside lately (target 10%)" at 3.5× | "Every number comes from running the fire forward 32 times: not a language model, not a learned shortcut. So we show it as a count, like 24 of 32 simulations, and a crew card only appears when even the pessimistic end of its range helps. But simulations are wrong in ways a count can't see: the wind shifts. So the forecast outline is calibrated as the fire burns, checking every past forecast against what actually burned. It aims for one acre in ten outside it, and the console shows how well that's holding right now. When the wind shifts, you watch that number jump, and the outline widen to catch up." | "24 of 32 → likely 61–85%", "Target: 10% outside · measured 11–13% (steady, shift, gusty)" |
| **1:20–1:35** Saying what we don't know | Card: three short lines over the console | "We're upfront about the limits. Our replay of the Camp Fire burns about twice the real area. Town arrival ranges hold more than nine times in ten in steady wind, but only about two in three right after a shift, because we don't forecast the wind. There's no fuel moisture model, and fire doesn't spread house to house." | "Camp Fire replay ~2× the area", "Steady wind 95% · after a shift 67%", "No wind forecast · no fuel moisture · no house-to-house spread" |
| **1:35–1:50** Decide | Take B1 then B2: order evacuation, dispatch the recommended crew | "Within those limits, every decision lands in one queue, most urgent first. Order an evacuation, and the alert is drafted. Dispatch a crew, and the forecast credits it from the moment it arrives." | Badge: 0.25× |
| **1:50–2:20** The table as a drone | Table wide (projector shows only ground and fire), then hard cut to the console's Camera view: the camera's top-down picture with the map layers over it. A hand places a crew token; the console picks it up | "On a real fire, the operator sees it from a drone. Our stand-in is a 3D print of the real terrain. The projector paints only what a drone would see, ground and fire. The camera overhead is the drone: it corrects for the terrain's height, straightens the view into a top-down map, and spots units on the ground, so the software works from what it sees, not what we tell it." | Lower third: "Physical table = drone footage stand-in" |
| **2:20–2:48** How four people built it | Agent board, live: a question, its answer, a claim, a merge in the feed. Optional: a 3-pin map of where we each worked | "Four of us built this from different places, each with a team of coding agents. They shared what they learned on one live board: findings, decisions, questions to each other, and which files they were touching. When one agent changed how the wind steers fire, another asked why, and got an answer with the test results. When one of us ran out of time, another's agent picked up the work from the board. 94 pull requests, 34 shared findings, and almost no stepping on each other." | "hack.apps.jaysonc.dev", "94 PRs · 34 shared findings" [update on the day] |
| **2:48–3:00** Close | Table, slow push-in → end card | "Fireline: see the fire, decide ahead of it, and know how far to trust the forecast." | End card: team · repo |

About 410 words of voiceover, roughly 2:55 at 140 words a minute. Trim the 1:35 segment first if the read runs long.

## Why this order

- **Simulation before uncertainty:** the replay numbers earn the right to talk about limits; they show we measured the model before trusting it.
- **Uncertainty gets the most time (55 s):** it's what separates us from a pretty fire animation. The beat to land is the live miss-rate readout: a forecast that grades itself in front of the operator.
- **The limits slide is deliberate.** Saying "70% after a wind shift" on camera is more credible than a perfect number.
- **The table is framed as a drone, not a gimmick** (board decision [17]): the projector draws only ground and fire, and the camera does the seeing.
- **The board is about distributed velocity,** with two real examples from the board's history: the C2 question in [60] and the map extension handoff in [196].

## Footage needed

0. **Record with `EMULATOR=off` in `.env`** (#213). The engine log should say 'fire emulator switched off'. The emulator's weights predate the map extension and fuel fix, and with it off every frame is Monte Carlo with the calibrated outline.
1. **Console:**
   - existing takes A, B1, B2;
   - a new 3.5× insert of the layers menu with the outline's miss rate visible;
   - ideally a wind-shift take where the miss rate rises and the outline widens.
2. **Calibration close-ups (PR #213 merged first):**
   - the map legend: 'Calibrated outline' with its live miss rate underneath (it turns orange and says 'Widening' after a wind shift);
   - a town label on the map showing the calibrated range ('Fire in 25–40 min');
   - optional insert: `docs/images/calibration/envelope_maps.png` (PR #210), the outline before, just after and an hour after a wind shift.
3. **Insert cards:**
   - the Camp Fire replay overlay (frame from `eval.campfire`);
   - the limits card;
   - the uncertainty captions.
4. **Table:** a wide shot, a close-up of a hand placing a token, and the Camera view split-screen (table and orthophoto with overlays side by side).
5. **Board:** about 15 s of a busy stretch, including one question-and-answer thread and the GitHub merge feed. Blur tokens.

## To check before recording

- [x] Camp Fire replay re-measured on the 512x480 map with rebuilt truth files: IoU 0.39 / 0.53, 2.2x / 1.7x the area, C2 stays 0.3 (board [258]).
- [x] Envelope miss on the new maps: 10.9% steady, 11.7 / 12.6% shift, 12.4 / 12.2% gusty (T+30 / T+60).
- [ ] Arrival-range coverage (98% / 70%) and Marshall 1.01x on the extended maps: re-measuring now.
- [ ] #213 merged (simulator-only toggle, legend, calibrated town labels) before recording.
- [ ] PR and knowledge counts on the day.
- [x] The outline's miss rate is in the map legend now (#213), not only the layers menu.
- [ ] The narrator, decided by the team.
