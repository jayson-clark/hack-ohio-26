# Fireline AI: models, features and how to read their uncertainty

This page covers everything in the engine that forecasts, recommends, plans or talks, and how to read the uncertainty that comes with each number. The design and the reasons behind it are in `PLAN.md`. Module paths are relative to `engine/`.

**One rule runs through all of it:** every number an operator sees comes from simulating the fire. The language models never invent figures; they only phrase numbers the simulations produced. The learned emulator only draws previews and shortlists crew spots. Nothing it predicts is shown as a result.

## At a glance

| Feature | What it is | Model | Where |
|---|---|---|---|
| Fire forecast | P(burn by T+30 / T+60) for every cell, plus a 10 h forecast for evacuation | Monte Carlo over the stochastic fire model (32 runs) | `forecast/rollout.py`, `forecast/runner.py`, `sim/fire.py` |
| Calibrated burn outline | The forecast outline, adjusted so about 90% of new fire lands inside it | Online conformal risk control | `uq/conformal.py` (`EnvelopeLedger`) |
| Town arrival ranges | "Fire likely arrives in 25–40 min (90%)" | Online conformalized quantiles (CQR) | `uq/conformal.py` (`ArrivalCalibrator`) |
| Evacuation routes | The best way out per town, avoiding roads that will burn by the time traffic gets there | Dijkstra on a burn-risk cost | `routing/evac.py`, `routing/tracker.py` |
| Evacuation order clock | When each town must be ordered out | Fluid traffic queue against forecast fire arrival | `routing/clearance.py` |
| Crew recommendations | Where a crew helps most, with the towns it saves | Paired Monte Carlo what-ifs, emulator shortlist | `forecast/recommend.py` |
| Plan what-ifs | The operator's whole set of orders compared with doing nothing | Paired Monte Carlo | `forecast/plan.py` |
| Learned emulator | An instant forecast preview, and a shortlist of crew spots | U-Net (MLX, 1.5M parameters) | `emulator/` |
| Incident commander Q&A | Typed or spoken questions answered in two sentences | Claude (`claude-haiku-5-5` by default) with 4 simulation tools | `commander/agent.py`, `commander/tools.py` |
| Grounding guard | Rejects any answer with a number no tool produced | Rules | `commander/guard.py` |
| Briefings | Short text alerts in the commander feed ("Paradise is threatened…") | Rules, no LLM | `commander/briefings.py` |
| Dispatch and alert drafts | Unit orders, bilingual evacuation alerts, crew briefings | Templates; Claude rewrites only unit orders and briefings, which must pass the guard | `commander/drafts.py` |

## The foundation: the fire model and Monte Carlo

Everything else builds on a stochastic cellular automaton: each cell is 94 m and each tick is one simulated minute (`sim/fire.py`).
- **Spread:** each tick, a burning cell lights each neighbour with probability `P_H × fuel × slope × wind × (1 − suppression)`.
- **Wind:** the wind term is `e^(C1·v) · e^(C2·v·(cos θ − 1))`, with `C1 = 0.14` and `C2 = 0.3`.
- **Embers:** above 9 m/s, burning cells throw embers downwind.
- **Validation:** the constants are checked against two real fires, the 2018 Camp Fire (`eval/campfire.py`) and the 2021 Marshall Fire (`eval/marshall.py`). PLAN.md's "Choosing C2" has the scores.

A **forecast** runs 32 copies of the current fire forward, each with its own random draws, and records when each cell first burned in each run. From that:
- **The burn probability** is the share of runs that burned a cell by T+30 or T+60. The console's forecast "ghost" draws it.
- **Town arrival** is the first time fire touches any cell of a town, in each run.
- **The long forecast** (600 min, 32 runs) feeds the evacuation clock and the arrival ranges.

Forecasts run in worker processes, so they never stall the engine's 10 Hz loop.

**What-ifs are paired.** A "crew here vs no crew" comparison runs both sides on the same random draws (`rollout_paired`). The difference is then the crew's effect, not luck, which makes the estimate far less noisy than comparing two independent forecasts.

## The features

### Evacuation routing (`routing/evac.py`, `routing/tracker.py`)
- **Cost:** each road costs `length × (1 + 8 × P(it burns by the time traffic reaches it))`. Traffic is assumed to move at 25 km/h, as on the jammed roads of 2018.
- **Closed roads:** a road burning now, or at least 90% likely to burn by arrival, is impassable.
- **Status:** a route turns *risky* when its risk is above 25%.
- **Stable routes:** routes don't flicker between runs. A town keeps its route unless that route is cut, or a new one is at least 15% cheaper and the current one has been shown for 20 ticks.
- **Events:** every switch and cut is logged with its reason.

### Evacuation order clock (`routing/clearance.py`)
The clock compares, for each town:
- **Time available:** fire arrival in each run of the 10 h forecast.
- **Time needed:** 20 min to mobilise, then the time for the town's vehicles to drain through its tightest exit road. Road capacity is shared with other towns already ordered out, so ordering Magalia slows Paradise.

**Order-by time:** the latest order time at which, in 90% of simulations, the last car gets out before the fire arrives.

**Statuses:**

| Status | When it shows |
|---|---|
| watch | The order-by time is more than 30 min away, or there's no forecast yet. |
| order soon | The order-by time is within 30 min. |
| order now | The order-by time has passed, but at least half of simulations still get the last car out first. |
| late | The order-by time has passed and fewer than half of simulations get everyone out first. |
| evacuating | The town has been ordered out. |
| trapped | The town has no open exit. |
| clear | Nobody is left in the town. |

If a town takes longer to empty than the 10 h forecast covers, the clock says so instead of claiming a precise time.

### Crew recommendations (`forecast/recommend.py`)
1. **Candidates:** unburned cells on the predicted front, where P(burn by T+30) is between 0.2 and 0.8. They are weighted by nearby population and kept at least a crew's reach apart. With the emulator installed, 48 candidates are screened to 8 in milliseconds.
2. **Score:** each candidate is scored by a paired what-if 2 h ahead. The score is the population-weighted share of each town the fire reaches, plus a small weight on acres, and it accounts for when the crew can actually arrive.
3. **Fresh re-run:** the top 3 are re-run on fresh random seeds. This guards against the winner's curse: the best of 8 noisy estimates is biased upward. If the top two still can't be told apart, both are re-run once more.
4. **Shown only if helpful:** a recommendation appears only if the low end of its 90% benefit interval is above zero.

### Plan what-ifs (`forecast/plan.py`)
The operator's full set of orders is simulated against doing nothing, with each unit acting from when it can actually get there. The result is acres saved, with a 90% interval from the paired differences, and a map of where the plan changes the outcome.

### Learned emulator (`emulator/`)
- **Architecture:** a U-Net (widths 32–128, dilated convolutions, GroupNorm) trained with MLX on the GPU.
- **Inputs:** 15 channels: burning, burned, burn time left, 8 directional spread-times-wind channels, and suppression at +0, 15, 30 and 60 min.
- **Output:** P(burn by T+30 / T+60).
- **Speed and accuracy:** 6 ms against about 0.6 s for 32 runs. On 342 held-out fires its Brier score against the hedged 64-run label is 0.0038, slightly better than the engine's own 32-run forecast (0.0039). It is well calibrated: in every probability bin the mean prediction is within 0.003 of the label. Its 50% outline overlaps the engine's forecast by 79%.

**Training labels include model error (#170).** Each training sample's 64-run label uses its own `C2` (0.22–0.4, the range the two real fires support) and a ×0.85–1.15 spread rate, and each run draws its own wind (±20% speed, ±15° direction). The inputs stay at the nominal constants, so the emulator learns a forecast that hedges over model error rather than copying one exact setting. The training data covers Paradise and Marshall.

**How to read it:** an emulator preview is a placeholder until the next Monte Carlo forecast lands, usually within a second. Because it hedges over model error, a preview is less sure than the forecast that replaces it: the low-probability fringe (P ≥ 0.1) covers about 27% more ground, and the confident core (P ≥ 0.9) about half as much. That's the hedging, not an error. Previews never feed routes, alerts, the clock, commander answers or the calibrators. While a preview is on screen the forecast's line is the plain 50% edge, not the calibrated outline: the calibration is learned on Monte Carlo forecasts only, so it doesn't apply to the emulator's probabilities. The calibrated line comes back when the Monte Carlo forecast lands.

### Incident commander (`commander/agent.py`, `commander/tools.py`, `commander/guard.py`)
**The model:**
- `COMMANDER_MODEL` (default `claude-haiku-5-5`), with low effort.
- Up to 3 tool rounds and a 10 s answer budget.
- The last 3 question–answer pairs are kept for follow-ups.
- The system prompt names the scenario's real setting (`game.json` `setting`).

**Its four tools:**

| Tool | What it returns |
|---|---|
| `get_situation` | Towns, threats, recommendations and the round. |
| `forecast_whatif` | A 16-run forecast under a different wind. |
| `evaluate_placement` | An 8-run paired what-if for a crew at a given spot. |
| `get_routes` | Routes and the evacuation clock. |

**Grounding guard:** every number in an answer must match a number from this question's tool results, or one the asker said. Rounding the way people speak ("about 230 acres") and turning counts into percentages are allowed. Answers are checked sentence by sentence as they stream. A failed answer gets one correction retry, then the template answer.

**Fallback:** with no API key, a refusal, a network error or a timeout, a rule-based answer is built from the same tools, so the commander never goes quiet.

### Briefings (`commander/briefings.py`)
No LLM is involved.
- **Threatened:** a town is announced as threatened when the low end of its 90% interval on "fire reaches it within 30 min" is at least 50%.
- **Safe again:** only after the interval's high end is below 50% on 2 forecasts in a row. That gap stops a town on the line from flip-flopping.
- **Forecast shift:** announced when the next-hour outline overlaps the previous one by less than 60% (IoU).
- **Pacing:** at most one briefing every 8 s, no repeats about the same town within 45 s, and stale news is dropped.

Every sentence is built from simulation numbers, so briefings are grounded by construction.

### Dispatch and alert drafts (`commander/drafts.py`)
Drafts are written when the operator sends a unit or orders a town out. The operator approves, edits or dismisses each one, and nothing is delivered outside the app.
- **Unit orders and crew briefings:** start as templates. Claude may rewrite them, but a rewrite is kept only if every number comes from the facts and it names no place the facts don't.
- **Evacuation alerts:** stay templated, in English and Spanish, within 360 characters (the Wireless Emergency Alert limit). Public wording and the translation must match exactly.

There is no voice: text-to-speech was removed in #140 and push-to-talk in #175. Questions are typed.

## Uncertainty: three layers, and how to read them

Each layer answers a different question. The console labels them consistently.

### 1. "How sure is this count?": sampling uncertainty (`uq/mc.py`)
Every probability is a count over a few simulations, and a count over 32 runs is itself noisy. The engine gives it a 90% range:
- **Probabilities ("in 24 of 32 simulations")** get a Wilson score interval, sent as `KofN {k, n, lo, hi}`. It stays inside 0–100% and behaves at 0 of 32 or 32 of 32.
  - *Read it as:* "if we ran infinitely many simulations of this same forecast, the share would likely be between lo and hi." For 24 of 32 that's about 61–85%.
- **Confidence words** come from the interval's width:
  - *high:* narrower than 20 points;
  - *moderate:* 20–40 points;
  - *low:* wider than 40 points.

  With 32 runs a mid-range count is usually *moderate*. With 8 runs it's *low*. The commander must say the range or hedge ("probably") unless confidence is high.
- **Benefits** (crew recommendations, plan acres saved) get a Student-t 90% interval on the paired per-run differences.
  - *high:* the low end is at least half the estimate.
  - *moderate:* the low end is above zero.
  - *low:* it isn't shown at all. This is abstention: the engine stays quiet rather than recommend something it can't tell apart from doing nothing.

**What this layer does not cover:** whether the forecast's assumptions hold. More runs only make the estimate of the same model with the same wind more precise.

### 2. "Has this held up so far?": conformal calibration (`uq/conformal.py`)
The raw forecast assumes the wind and the crews stay as they are. Players change both, so the raw outlines turn out overconfident. Two online calibrators check each forecast against what actually happened once its time comes, and adjust.

**The calibrated burn outline (`EnvelopeLedger`).**
- **The promise:** of the ground that newly burns in the next 30 or 60 min, at most 10% falls outside the outline, in the long run.
- **How it works:** each outline is scored when its horizon passes, as burned area outside divided by burned area. One knob per horizon moves by `0.1 × (miss − 0.10)`. The knob is a probability cutoff, and when the cutoff can't go any lower it becomes a margin of extra cells, up to 10. This is adaptive conformal inference (ACI; Gibbs & Candès 2021) applied to a bounded loss (online conformal risk control).
- **What kind of guarantee this is** (see "The guarantee, precisely" below): a finite-sample bound on the *average* miss over the forecasts scored so far, holding for any sequence of winds and player actions. It is not a promise about any single outline.
- **On screen:** the map's layers menu shows "Forecast outline: X% at 30 min, Y% at 60 min of new fire fell outside it lately (target 10%)", over the last 20 forecasts. It is highlighted when a recent miss rate is more than 5 points over target.
- **Reading the numbers:** a recent miss rate well above 10% usually means the wind just changed. Expect the outline to widen over the next few forecasts.
- **Measured** at `C2` 0.3 (`eval.run`, 4 episodes per wind schedule, 83–96 scored forecasts each; missed share over the whole run):

  | Wind | T+30 | T+60 |
  |---|---|---|
  | Steady | 10.9% | 11.0% |
  | Wind shift | 11.7% | 13.0% |
  | Gusty | 12.3% | 12.1% |

  All are inside the finite-sample bound below (about 10% + 3.7/T, so up to about 14% at these T). They sit 1–3 points over target because each run starts from the warm start and spends its first forecasts catching up.
- **Per scenario:** the knob is learned per scenario and restarts from `ENVELOPE_WARM` when the scenario changes.

**Town arrival ranges (`ArrivalCalibrator`).**
- **Raw range:** each threatened town gets the 5–95% range of fire arrival across the long forecast's runs.
- **Correction:** a learned correction Q per lead-time bucket (under 30 min, 30–120 min, over 120 min) widens or narrows it to `[lo − Q, hi + Q]`.
- **Calibration units:** towns burn too rarely to learn from, so Q is learned on town-sized disks (8-cell radius) dropped on unburned ground and scored like towns. The bound below applies to those disks; that towns behave like them is an assumption, which the measured town coverage checks.
- **On screen:** "fire likely arrives in 25–40 min (90%)". There is no range (null) when too few simulations reach the town to bound it. That means "probably not within the forecast", not "never".
- **Measured coverage** of real town arrivals (target 90%, `eval.arrival`, 40–55 town ranges per schedule) at `C2` 0.3: steady wind 98% (median width 38 min), gusty 72% (143 min), wind shift 70% (138 min).
- **Wind shifts:** treat ranges issued just before a shift as stale. They learn only after the shift, and the fix for that is a real wind forecast, not more statistics.

**The guarantee, precisely.** Split conformal prediction gives a finite-sample guarantee for each new prediction, P(covered) ≥ 90%, but only if the calibration data and the new case are exchangeable. A fire under shifting wind and player actions isn't, so the console uses the online (ACI) form instead. That trades the per-prediction guarantee for a deterministic one on the running average, with no assumption about the data at all:
- **Arrival ranges (`OnlineQuantile`, no clipping):** each update moves Q by `lr × (miss − 0.10)`, so the sum telescopes: after T scored disks in a bucket, |miss rate − 10%| = |Q_T − Q_0| / (lr × T). Q stays within about the largest score (the forecast horizon), so the gap shrinks like 1/T. It holds at every T, not just in the limit, but it is loose early on.
- **Burn outline (`OnlineEnvelope`, knob clipped to [1/32 − 0.2, 1]):** the same telescoping gives average miss ≤ 10% + (θ_0 − θ_min) / (0.1 × T). With the warm start at T+30 (0.2) that's 10% + 3.7/T: within 10 points after 37 scored forecasts, and within 1 point after 370. One condition: the widest outline (P ≥ 1/32 plus 10 cells) must itself miss at most 10%. When it misses more, for example an ember landing far ahead, the clip absorbs the excess and the bound loosens by that amount.
- **What it doesn't promise:**
  - any single outline or range;
  - coverage in a particular window, such as the 20 forecasts right after a wind shift (the "short catch-up");
  - town coverage directly, since the arrival bound is on the disks.

  Those are why the measured numbers above are reported next to the bound. Outline misses are also averaged per forecast, not weighted by area.

**Caveat on censoring:** a disk that never burns within the forecast counts as the smallest miss it could be. That can only make ranges too narrow, never too wide. It's counted and reported (`cells_censored` in `eval.arrival`).

### 3. "Is the simulator right about real fires?": model error
Layers 1 and 2 measure the simulator against itself plus changes in wind and crews. Whether the simulator matches real fire behaviour is checked separately:
- **Real-fire replays:** the Camp Fire and Marshall Fire replays score the model against real perimeters and timed observations. `C2` 0.3 gives Camp IoU 0.66 / 0.78 and Marshall 2.5 h IoU 0.45 at 1.0× the real area.
- **Emulator training:** the emulator's labels average over plausible model constants, so its previews hedge over this error.
- **Known gaps:**
  - no fuel moisture or humidity model;
  - suburbs burn like fuel, with no house-to-house spread, so Marshall overshoots past where the real fire stopped;
  - no wind forecast, so the wind is assumed to hold unless the operator asks a what-if.

## Cheat sheet for operators

| You see | It means |
|---|---|
| "in 24 of 32 simulations" | 24 of 32 simulated futures did this. The true chance is likely 61–85%. |
| confidence: moderate / low | The count is too small to be sharp. Read it as a range, not a number. |
| A forecast outline with a miss rate near 10% | The outline has been honest lately. |
| A miss rate well above 10% | Something changed, probably the wind. The outline is catching up. |
| "fire likely arrives in 25–40 min (90%)" | A range whose miss rate is held near 10% on average over the session. Measured on towns it holds about 9 times in 10 in steady wind, but it's weaker right after a wind shift. |
| No arrival range | Too few simulations reach the town to bound it. |
| A crew recommendation | Even its pessimistic estimate helps. Weaker spots are hidden. |
| A preview that snaps to a slightly different shape | The emulator's instant guess being replaced by the full forecast. |
| A commander answer | Every number in it came from a simulation run for that question. |

## Checking it yourself

```sh
cd engine
uv run python -m eval.run            # forecast skill, envelope miss rate, routing, recommendations (~75 s)
uv run python -m eval.arrival        # arrival-range coverage per wind schedule (~15 min)
uv run python -m eval.campfire       # the Camp Fire replay (~3 s)
uv run python -m eval.marshall --measured   # the Marshall Fire replay
uv run python -m eval.early_attack   # does crew dispatch contain fires at 3/8/13 m/s
uv run python -m eval.evac_clock     # order-by times against the Camp Fire's real arrivals
uv run --extra ml python -m emulator.evaluate   # emulator Brier, IoU, calibration, speed
uv run python -m commander.ask "What if the wind shifts west?"   # one commander answer, with tools and timing
```

The `model-eval`, `fire-emulator`, `tune-fire` and `commander` skills in `.claude/skills/` have the details.
