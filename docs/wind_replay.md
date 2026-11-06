# Forecast-conditioned wind uncertainty on real-wind fires (#231, stage 2)

60 fires (30 per station) driven by observed 2023-24 winds; 32 rollouts, a forecast every 5 min for 300 min; target miss 10%. Pre-shift = the forecast's window held an observed shift (> 45°) or surge. The oracle is a diagnostic upper bound fed the future wind: never deployable.

## Equal risk, no controller (the decision rule's view)

| forecaster | horizon | cutoff θ | pooled miss | area km² | pre-shift miss | pre-shift area km² |
|---|---|---|---|---|---|---|
| constant | T+30 | 0.218 | 9.3% | 7.44 | 15.7% | 5.10 |
| constant | T+60 | 0.187 | 8.9% | 15.25 | 19.4% | 12.01 |
| ensemble 0.25/h | T+30 | 0.218 | 9.1% | 7.46 | 15.0% | 5.14 |
| ensemble 0.25/h | T+60 | 0.218 | 9.5% | 14.92 | 19.5% | 11.80 |
| ensemble 1/h | T+30 | 0.218 | 9.1% | 7.47 | 14.3% | 5.16 |
| ensemble 1/h | T+60 | 0.218 | 9.4% | 15.14 | 18.1% | 11.99 |
| conditional onboard | T+30 | 0.218 | 9.2% | 7.46 | 15.0% | 5.15 |
| conditional onboard | T+60 | 0.218 | 9.7% | 14.88 | 19.7% | 11.81 |
| conditional onboard+forecast | T+30 | 0.218 | 9.2% | 7.46 | 15.1% | 5.15 |
| conditional onboard+forecast | T+60 | 0.218 | 9.7% | 14.88 | 19.6% | 11.79 |
| conditional budget-matched | T+30 | 0.218 | 9.4% | 7.50 | 14.5% | 5.24 |
| conditional budget-matched | T+60 | 0.218 | 10.0% | 15.24 | 18.1% | 12.34 |
| oracle (diagnostic) | T+30 | 0.250 | 9.2% | 7.12 | 10.6% | 4.66 |
| oracle (diagnostic) | T+60 | 0.281 | 9.0% | 13.78 | 10.6% | 10.33 |

**Decision rule** (fixed in advance): conditional onboard+forecast must lower the pre-shift miss vs constant wind (90% CI over episodes excluding 0) and need less area than the 1/h ensemble (ratio < 1).

| horizon | pre-shift miss, conditional − constant (90% CI) | area, conditional / 1/h (90% CI) | draws |
|---|---|---|---|
| T+30 | [-1.2%, 0.1%] | [0.99, 1.00] | 1000 |
| T+60 | [-1.8%, 0.5%] | [0.97, 1.02] | 1000 |

Secondary (added after the smoke test; see the docstring): budget-matched conditional vs the 1/h ensemble it is budget-matched to, at equal risk.

| horizon | pre-shift miss, budget-matched − 1/h (90% CI) | area, budget-matched / 1/h (90% CI) |
|---|---|---|
| T+30 | [-1.5%, 1.0%] | [1.00, 1.05] |
| T+60 | [-3.2%, 0.6%] | [1.00, 1.07] |

## Under the engine's controller (fixed-rate ACI, own state per forecaster)

| forecaster | horizon | station | miss | worst 30 min | area km² | vs oracle | pre-shift miss | at widest |
|---|---|---|---|---|---|---|---|---|
| constant | T+30 | all | 9.6% | 24.0% | 7.48 | 1.04× | 14.3% | 0.0% |
| ensemble 0.25/h | T+30 | all | 9.6% | 24.2% | 7.46 | 1.04× | 14.0% | 0.0% |
| ensemble 1/h | T+30 | all | 9.6% | 23.5% | 7.55 | 1.05× | 13.4% | 0.0% |
| conditional onboard | T+30 | all | 9.6% | 24.2% | 7.48 | 1.04× | 13.9% | 0.0% |
| conditional onboard+forecast | T+30 | all | 9.6% | 24.1% | 7.47 | 1.04× | 14.0% | 0.0% |
| conditional budget-matched | T+30 | all | 9.6% | 23.3% | 7.65 | 1.05× | 13.2% | 0.0% |
| oracle (diagnostic) | T+30 | all | 9.1% | 21.4% | 7.17 | 1.05× | 10.3% | 0.0% |
| constant | T+30 | OVE | 9.4% | 22.9% | 7.54 | 1.07× | 13.2% | 0.0% |
| ensemble 0.25/h | T+30 | OVE | 9.4% | 23.4% | 7.47 | 1.05× | 12.7% | 0.0% |
| ensemble 1/h | T+30 | OVE | 9.4% | 23.0% | 7.58 | 1.05× | 11.5% | 0.0% |
| conditional onboard | T+30 | OVE | 9.4% | 23.1% | 7.49 | 1.06× | 12.5% | 0.0% |
| conditional onboard+forecast | T+30 | OVE | 9.4% | 23.2% | 7.48 | 1.05× | 12.7% | 0.0% |
| conditional budget-matched | T+30 | OVE | 9.5% | 23.2% | 7.61 | 1.05× | 10.1% | 0.0% |
| oracle (diagnostic) | T+30 | OVE | 9.2% | 22.7% | 7.37 | 1.06× | 10.1% | 0.0% |
| constant | T+30 | BJC | 9.8% | 25.0% | 7.43 | 1.02× | 14.8% | 0.0% |
| ensemble 0.25/h | T+30 | BJC | 9.7% | 24.9% | 7.46 | 1.03× | 14.6% | 0.0% |
| ensemble 1/h | T+30 | BJC | 9.7% | 24.0% | 7.52 | 1.04× | 14.1% | 0.0% |
| conditional onboard | T+30 | BJC | 9.7% | 25.2% | 7.47 | 1.03× | 14.5% | 0.0% |
| conditional onboard+forecast | T+30 | BJC | 9.8% | 25.1% | 7.46 | 1.03× | 14.5% | 0.0% |
| conditional budget-matched | T+30 | BJC | 9.7% | 23.4% | 7.68 | 1.04× | 14.5% | 0.0% |
| oracle (diagnostic) | T+30 | BJC | 9.0% | 20.0% | 6.98 | 1.03× | 10.4% | 0.0% |
| constant | T+60 | all | 8.9% | 28.1% | 16.59 | 1.13× | 17.4% | 0.9% |
| ensemble 0.25/h | T+60 | all | 8.8% | 28.1% | 16.96 | 1.17× | 16.5% | 0.9% |
| ensemble 1/h | T+60 | all | 8.9% | 27.2% | 18.16 | 1.23× | 14.7% | 0.7% |
| conditional onboard | T+60 | all | 8.8% | 27.9% | 16.70 | 1.14× | 16.7% | 0.8% |
| conditional onboard+forecast | T+60 | all | 8.8% | 27.9% | 16.65 | 1.14× | 16.6% | 0.8% |
| conditional budget-matched | T+60 | all | 8.8% | 26.1% | 18.79 | 1.23× | 14.1% | 0.4% |
| oracle (diagnostic) | T+60 | all | 7.6% | 20.6% | 14.65 | 1.12× | 8.9% | 0.5% |
| constant | T+60 | OVE | 8.5% | 24.8% | 16.15 | 1.12× | 13.6% | 0.5% |
| ensemble 0.25/h | T+60 | OVE | 8.5% | 25.6% | 16.67 | 1.15× | 12.3% | 0.5% |
| ensemble 1/h | T+60 | OVE | 8.9% | 26.2% | 18.44 | 1.24× | 9.8% | 0.5% |
| conditional onboard | T+60 | OVE | 8.5% | 25.2% | 16.19 | 1.12× | 12.9% | 0.5% |
| conditional onboard+forecast | T+60 | OVE | 8.5% | 25.1% | 16.21 | 1.12× | 12.8% | 0.5% |
| conditional budget-matched | T+60 | OVE | 8.9% | 25.1% | 18.46 | 1.21× | 9.8% | 0.5% |
| oracle (diagnostic) | T+60 | OVE | 7.7% | 21.7% | 15.40 | 1.14× | 6.7% | 0.5% |
| constant | T+60 | BJC | 9.3% | 31.4% | 17.01 | 1.14× | 19.8% | 1.2% |
| ensemble 0.25/h | T+60 | BJC | 9.1% | 30.7% | 17.24 | 1.18× | 19.1% | 1.2% |
| ensemble 1/h | T+60 | BJC | 8.8% | 28.2% | 17.89 | 1.23× | 17.8% | 0.9% |
| conditional onboard | T+60 | BJC | 9.2% | 30.6% | 17.17 | 1.16× | 19.0% | 1.1% |
| conditional onboard+forecast | T+60 | BJC | 9.2% | 30.7% | 17.07 | 1.15× | 19.0% | 1.1% |
| conditional budget-matched | T+60 | BJC | 8.8% | 27.0% | 19.10 | 1.24× | 16.9% | 0.2% |
| oracle (diagnostic) | T+60 | BJC | 7.5% | 19.6% | 13.94 | 1.09× | 10.4% | 0.6% |

## Conditional shift rates and cost

| forecaster | mean rate /h | share of forecasts > 0.5/h | share > 1/h | mean forecast ms | p90 ms |
|---|---|---|---|---|---|
| constant | – | – | – | 244 | 436 |
| ensemble 0.25/h | – | – | – | 350 | 617 |
| ensemble 1/h | – | – | – | 411 | 726 |
| conditional onboard | 0.04 | 0.6% | 0.2% | 352 | 614 |
| conditional onboard+forecast | 0.04 | 0.8% | 0.3% | 353 | 618 |
| conditional budget-matched | 1.24 | 83.2% | 43.8% | 475 | 854 |
| oracle (diagnostic) | – | – | – | 301 | 541 |

Preloads missing (onboard+forecast fell back to onboard): 54 forecasts.
