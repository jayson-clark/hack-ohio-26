# Wind-shift predictability (#231) — stale forecast (7-13 h old)

81,984 issue times (every 30 min, Sep-Dec 2018-2024, Oroville OVE and Broomfield BJC).

## chronological (train 2018-22, test 2023-24)

| event | n test (events) | base rate | model | Brier | BSS vs constant (90% CI) | AUC (90% CI) | hit / false-alarm @0.2 | warned @0.2 | hit / false-alarm @0.5 |
|---|---|---|---|---|---|---|---|---|---|
| shift 30 min | 9740 (120) | 1.2% | persistence | 0.0123 | -0.024 | 0.500 | 0.0% / – | 0.0% | 0.0% / – |
| shift 30 min | 9740 (120) | 1.2% | constant | 0.0120 | 0.000 [0.000, 0.000] | 0.728 [0.685, 0.765] | 0.0% / – | 0.0% | 0.0% / – |
| shift 30 min | 9740 (120) | 1.2% | onboard | 0.0119 | 0.015 [-0.008, 0.037] | 0.848 [0.816, 0.875] | 5.0% / 77.8% | 0.3% | 0.8% / 83.3% |
| shift 30 min | 9740 (120) | 1.2% | onboard+forecast | 0.0118 | 0.021 [-0.004, 0.048] | 0.861 [0.828, 0.888] | 5.8% / 80.0% | 0.4% | 1.7% / 66.7% |
| shift 30 min | | | AUC gain from the forecast | | | 90% CI [-0.000, 0.025] | | | |
| reversal 30 min | 9740 (6) | | too few events to score (35 train, 6 test) | | | | | | |
| surge 30 min | 9740 (35) | 0.4% | persistence | 0.0036 | -0.007 | 0.500 | 0.0% / – | 0.0% | 0.0% / – |
| surge 30 min | 9740 (35) | 0.4% | constant | 0.0036 | 0.000 [0.000, 0.000] | 0.820 [0.788, 0.850] | 0.0% / – | 0.0% | 0.0% / – |
| surge 30 min | 9740 (35) | 0.4% | onboard | 0.0037 | -0.029 [-0.066, 0.006] | 0.837 [0.786, 0.889] | 2.9% / 91.7% | 0.1% | 0.0% / 100.0% |
| surge 30 min | 9740 (35) | 0.4% | onboard+forecast | 0.0037 | -0.032 [-0.078, 0.008] | 0.885 [0.845, 0.923] | 2.9% / 92.3% | 0.1% | 0.0% / 100.0% |
| surge 30 min | | | AUC gain from the forecast | | | 90% CI [0.024, 0.071] | | | |
| shift 60 min | 9676 (237) | 2.4% | persistence | 0.0245 | -0.038 | 0.500 | 0.0% / – | 0.0% | 0.0% / – |
| shift 60 min | 9676 (237) | 2.4% | constant | 0.0236 | 0.000 [0.000, 0.000] | 0.674 [0.625, 0.721] | 0.0% / – | 0.0% | 0.0% / – |
| shift 60 min | 9676 (237) | 2.4% | onboard | 0.0228 | 0.031 [0.009, 0.053] | 0.855 [0.833, 0.877] | 9.3% / 72.5% | 0.8% | 2.1% / 72.2% |
| shift 60 min | 9676 (237) | 2.4% | onboard+forecast | 0.0227 | 0.036 [0.010, 0.061] | 0.864 [0.841, 0.886] | 11.4% / 73.5% | 1.1% | 2.5% / 73.9% |
| shift 60 min | | | AUC gain from the forecast | | | 90% CI [-0.002, 0.020] | | | |
| reversal 60 min | 9676 (29) | 0.3% | persistence | 0.0030 | -0.005 | 0.500 | 0.0% / – | 0.0% | 0.0% / – |
| reversal 60 min | 9676 (29) | 0.3% | constant | 0.0030 | 0.000 [0.000, 0.000] | 0.712 [0.618, 0.795] | 0.0% / – | 0.0% | 0.0% / – |
| reversal 60 min | 9676 (29) | 0.3% | onboard | 0.0030 | -0.007 [-0.024, 0.006] | 0.790 [0.695, 0.874] | 0.0% / 100.0% | 0.0% | 0.0% / – |
| reversal 60 min | 9676 (29) | 0.3% | onboard+forecast | 0.0031 | -0.025 [-0.053, -0.004] | 0.822 [0.755, 0.882] | 0.0% / 100.0% | 0.1% | 0.0% / 100.0% |
| reversal 60 min | | | AUC gain from the forecast | | | 90% CI [-0.026, 0.095] | | | |
| surge 60 min | 9676 (73) | 0.8% | persistence | 0.0075 | -0.021 | 0.500 | 0.0% / – | 0.0% | 0.0% / – |
| surge 60 min | 9676 (73) | 0.8% | constant | 0.0074 | 0.000 [0.000, 0.000] | 0.814 [0.785, 0.835] | 0.0% / – | 0.0% | 0.0% / – |
| surge 60 min | 9676 (73) | 0.8% | onboard | 0.0075 | -0.021 [-0.038, -0.004] | 0.854 [0.816, 0.889] | 0.0% / 100.0% | 0.1% | 0.0% / 100.0% |
| surge 60 min | 9676 (73) | 0.8% | onboard+forecast | 0.0075 | -0.008 [-0.033, 0.015] | 0.880 [0.850, 0.911] | 1.4% / 95.0% | 0.2% | 0.0% / 100.0% |
| surge 60 min | | | AUC gain from the forecast | | | 90% CI [0.001, 0.052] | | | |

Of the shifts that were also reversals (> 135°) or surges, the share each model warned of at P ≥ 0.2:

- shift 30 min, reversals (6): persistence 0.0%, constant 0.0%, onboard 0.0%, onboard+forecast 0.0%
- shift 30 min, surges (35): persistence 0.0%, constant 0.0%, onboard 2.9%, onboard+forecast 8.6%
- shift 60 min, reversals (29): persistence 0.0%, constant 0.0%, onboard 10.3%, onboard+forecast 20.7%
- shift 60 min, surges (73): persistence 0.0%, constant 0.0%, onboard 6.8%, onboard+forecast 6.8%

Wind at t + h (test rows):

| horizon | predictor | vector RMSE m/s | speed MAE m/s | direction MAE ° |
|---|---|---|---|---|
| 30 min | persistence | 1.80 | 0.83 | 14.1 |
| 30 min | hrrr | 2.82 | 1.29 | 31.4 |
| 30 min | blend | 1.68 | 0.81 | 12.8 |
| 60 min | persistence | 2.53 | 1.12 | 21.8 |
| 60 min | hrrr | 3.13 | 1.38 | 34.2 |
| 60 min | blend | 2.25 | 1.08 | 18.2 |

**Follow-up (defined after the first results): only times with wind >= 2.5 m/s at issue**, models refit on those. Concentration = share of the test events in the riskiest 10% / 20% of times (no skill: 10% / 20%).

| event | n test (events) | base rate | model | AUC | BSS vs constant | top 10% holds | top 20% holds | risk in top 10% |
|---|---|---|---|---|---|---|---|---|
| shift 30 min | 3679 (120) | 3.3% | constant | 0.707 | 0.000 | 78.3% | 78.3% | 6.7% |
| shift 30 min | 3679 (120) | 3.3% | onboard | 0.792 | 0.025 | 39.2% | 60.0% | 12.8% |
| shift 30 min | 3679 (120) | 3.3% | onboard+forecast | 0.818 | 0.036 | 44.2% | 63.3% | 14.4% |
| reversal 30 min | | | too few events | | | | | |
| surge 30 min | 3679 (20) | 0.5% | constant | 0.785 | 0.000 | 95.0% | 95.0% | 1.4% |
| surge 30 min | 3679 (20) | 0.5% | onboard | 0.833 | -0.009 | 50.0% | 65.0% | 2.7% |
| surge 30 min | 3679 (20) | 0.5% | onboard+forecast | 0.880 | -0.008 | 55.0% | 80.0% | 3.0% |
| shift 60 min | 3702 (237) | 6.4% | constant | 0.651 | 0.000 | 67.5% | 67.5% | 11.0% |
| shift 60 min | 3702 (237) | 6.4% | onboard | 0.743 | 0.025 | 33.3% | 49.4% | 21.3% |
| shift 60 min | 3702 (237) | 6.4% | onboard+forecast | 0.796 | 0.030 | 34.2% | 58.2% | 21.8% |
| reversal 60 min | 3702 (29) | 0.8% | constant | 0.684 | 0.000 | 75.9% | 75.9% | 1.5% |
| reversal 60 min | 3702 (29) | 0.8% | onboard | 0.662 | -0.007 | 34.5% | 48.3% | 2.7% |
| reversal 60 min | 3702 (29) | 0.8% | onboard+forecast | 0.772 | -0.035 | 27.6% | 51.7% | 2.2% |
| surge 60 min | 3702 (37) | 1.0% | constant | 0.793 | 0.000 | 97.3% | 97.3% | 2.5% |
| surge 60 min | 3702 (37) | 1.0% | onboard | 0.848 | -0.025 | 43.2% | 73.0% | 4.3% |
| surge 60 min | 3702 (37) | 1.0% | onboard+forecast | 0.841 | -0.017 | 43.2% | 64.9% | 4.3% |

Within each station (the constant rate's concentration above is only the windier station's share; this removes station identity): share of events in a station's riskiest 20%, and AUC.

- shift 30 min, onboard: BJC 40% of 94 (AUC 0.67); OVE 54% of 26 (AUC 0.74)
- shift 30 min, onboard+forecast: BJC 45% of 94 (AUC 0.71); OVE 62% of 26 (AUC 0.79)
- surge 30 min, onboard: BJC 42% of 19 (AUC 0.67)
- surge 30 min, onboard+forecast: BJC 47% of 19 (AUC 0.77)
- shift 60 min, onboard: BJC 41% of 160 (AUC 0.67); OVE 47% of 77 (AUC 0.75)
- shift 60 min, onboard+forecast: BJC 41% of 160 (AUC 0.72); OVE 64% of 77 (AUC 0.80)
- reversal 60 min, onboard: BJC 36% of 22 (AUC 0.63)
- reversal 60 min, onboard+forecast: BJC 32% of 22 (AUC 0.68)
- surge 60 min, onboard: BJC 39% of 36 (AUC 0.68)
- surge 60 min, onboard+forecast: BJC 42% of 36 (AUC 0.67)

## across stations (train OVE, test BJC)

| event | n test (events) | base rate | model | Brier | BSS vs constant (90% CI) | AUC (90% CI) | hit / false-alarm @0.2 | warned @0.2 | hit / false-alarm @0.5 |
|---|---|---|---|---|---|---|---|---|---|
| shift 30 min | 11379 (319) | 2.8% | persistence | 0.0280 | -0.007 | 0.500 | 0.0% / – | 0.0% | 0.0% / – |
| shift 30 min | 11379 (319) | 2.8% | constant | 0.0278 | 0.000 [0.000, 0.000] | 0.500 [0.500, 0.500] | 0.0% / – | 0.0% | 0.0% / – |
| shift 30 min | 11379 (319) | 2.8% | onboard | 0.0299 | -0.074 [-0.112, -0.039] | 0.748 [0.721, 0.771] | 9.4% / 85.8% | 1.9% | 4.4% / 84.6% |
| shift 30 min | 11379 (319) | 2.8% | onboard+forecast | 0.0301 | -0.082 [-0.127, -0.043] | 0.741 [0.714, 0.766] | 10.7% / 86.0% | 2.1% | 5.0% / 82.6% |
| shift 30 min | | | AUC gain from the forecast | | | 90% CI [-0.019, 0.005] | | | |
| reversal 30 min | 11379 (37) | | too few events to score (4 train, 37 test) | | | | | | |
| surge 30 min | 11379 (164) | | too few events to score (10 train, 164 test) | | | | | | |
| shift 60 min | 11518 (577) | 5.0% | persistence | 0.0501 | -0.019 | 0.500 | 0.0% / – | 0.0% | 0.0% / – |
| shift 60 min | 11518 (577) | 5.0% | constant | 0.0492 | 0.000 [0.000, 0.000] | 0.500 [0.500, 0.500] | 0.0% / – | 0.0% | 0.0% / – |
| shift 60 min | 11518 (577) | 5.0% | onboard | 0.0496 | -0.009 [-0.044, 0.025] | 0.765 [0.748, 0.781] | 23.2% / 74.3% | 4.5% | 11.6% / 70.4% |
| shift 60 min | 11518 (577) | 5.0% | onboard+forecast | 0.0519 | -0.057 [-0.098, -0.014] | 0.769 [0.752, 0.786] | 25.6% / 78.1% | 5.9% | 14.6% / 71.9% |
| shift 60 min | | | AUC gain from the forecast | | | 90% CI [-0.005, 0.014] | | | |
| reversal 60 min | 11518 (71) | | too few events to score (23 train, 71 test) | | | | | | |
| surge 60 min | 11518 (276) | | too few events to score (21 train, 276 test) | | | | | | |

Of the shifts that were also reversals (> 135°) or surges, the share each model warned of at P ≥ 0.2:

- shift 30 min, reversals (37): persistence 0.0%, constant 0.0%, onboard 5.4%, onboard+forecast 10.8%
- shift 30 min, surges (164): persistence 0.0%, constant 0.0%, onboard 9.1%, onboard+forecast 12.2%
- shift 60 min, reversals (71): persistence 0.0%, constant 0.0%, onboard 21.1%, onboard+forecast 26.8%
- shift 60 min, surges (276): persistence 0.0%, constant 0.0%, onboard 12.7%, onboard+forecast 17.0%

Wind at t + h (test rows):

| horizon | predictor | vector RMSE m/s | speed MAE m/s | direction MAE ° |
|---|---|---|---|---|
| 30 min | persistence | 2.52 | 1.27 | 19.8 |
| 30 min | hrrr | 3.77 | 1.88 | 43.3 |
| 30 min | blend | 2.39 | 1.26 | 19.0 |
| 60 min | persistence | 3.26 | 1.57 | 27.2 |
| 60 min | hrrr | 4.03 | 1.89 | 44.4 |
| 60 min | blend | 2.98 | 1.55 | 24.5 |

**Follow-up (defined after the first results): only times with wind >= 2.5 m/s at issue**, models refit on those. Concentration = share of the test events in the riskiest 10% / 20% of times (no skill: 10% / 20%).

| event | n test (events) | base rate | model | AUC | BSS vs constant | top 10% holds | top 20% holds | risk in top 10% |
|---|---|---|---|---|---|---|---|---|
| shift 30 min | 5207 (319) | 6.1% | constant | 0.500 | 0.000 | 100.0% | 100.0% | 6.1% |
| shift 30 min | 5207 (319) | 6.1% | onboard | 0.653 | 0.029 | 25.4% | 39.8% | 15.5% |
| shift 30 min | 5207 (319) | 6.1% | onboard+forecast | 0.692 | 0.033 | 28.5% | 42.6% | 17.5% |
| reversal 30 min | | | too few events | | | | | |
| surge 30 min | | | too few events | | | | | |
| shift 60 min | 5426 (577) | 10.6% | constant | 0.500 | 0.000 | 100.0% | 100.0% | 10.6% |
| shift 60 min | 5426 (577) | 10.6% | onboard | 0.640 | 0.070 | 25.8% | 37.6% | 27.4% |
| shift 60 min | 5426 (577) | 10.6% | onboard+forecast | 0.686 | 0.061 | 26.2% | 40.4% | 27.8% |
| reversal 60 min | | | too few events | | | | | |
| surge 60 min | | | too few events | | | | | |

Within each station (the constant rate's concentration above is only the windier station's share; this removes station identity): share of events in a station's riskiest 20%, and AUC.

- shift 30 min, onboard: BJC 40% of 319 (AUC 0.65)
- shift 30 min, onboard+forecast: BJC 43% of 319 (AUC 0.69)
- shift 60 min, onboard: BJC 38% of 577 (AUC 0.64)
- shift 60 min, onboard+forecast: BJC 40% of 577 (AUC 0.69)

## across stations (train BJC, test OVE)

| event | n test (events) | base rate | model | Brier | BSS vs constant (90% CI) | AUC (90% CI) | hit / false-alarm @0.2 | warned @0.2 | hit / false-alarm @0.5 |
|---|---|---|---|---|---|---|---|---|---|
| shift 30 min | 27384 (100) | 0.4% | persistence | 0.0037 | 0.137 | 0.500 | 0.0% / – | 0.0% | 0.0% / – |
| shift 30 min | 27384 (100) | 0.4% | constant | 0.0042 | 0.000 [0.000, 0.000] | 0.500 [0.500, 0.500] | 0.0% / – | 0.0% | 0.0% / – |
| shift 30 min | 27384 (100) | 0.4% | onboard | 0.0046 | -0.079 [-0.126, -0.044] | 0.808 [0.778, 0.836] | 1.0% / 98.7% | 0.3% | 0.0% / 100.0% |
| shift 30 min | 27384 (100) | 0.4% | onboard+forecast | 0.0046 | -0.084 [-0.117, -0.054] | 0.759 [0.721, 0.793] | 1.0% / 98.6% | 0.3% | 0.0% / 100.0% |
| shift 30 min | | | AUC gain from the forecast | | | 90% CI [-0.072, -0.030] | | | |
| reversal 30 min | 27384 (4) | | too few events to score (37 train, 4 test) | | | | | | |
| surge 30 min | 27384 (10) | | too few events to score (164 train, 10 test) | | | | | | |
| shift 60 min | 27046 (283) | 1.0% | persistence | 0.0105 | 0.123 | 0.500 | 0.0% / – | 0.0% | 0.0% / – |
| shift 60 min | 27046 (283) | 1.0% | constant | 0.0119 | 0.000 [0.000, 0.000] | 0.500 [0.500, 0.500] | 0.0% / – | 0.0% | 0.0% / – |
| shift 60 min | 27046 (283) | 1.0% | onboard | 0.0155 | -0.299 [-0.403, -0.210] | 0.790 [0.767, 0.811] | 8.8% / 97.6% | 3.8% | 0.7% / 97.7% |
| shift 60 min | 27046 (283) | 1.0% | onboard+forecast | 0.0133 | -0.115 [-0.173, -0.062] | 0.787 [0.762, 0.810] | 8.1% / 96.3% | 2.3% | 0.7% / 93.5% |
| shift 60 min | | | AUC gain from the forecast | | | 90% CI [-0.013, 0.006] | | | |
| reversal 60 min | 27046 (23) | 0.1% | persistence | 0.0009 | 0.031 | 0.500 | 0.0% / – | 0.0% | 0.0% / – |
| reversal 60 min | 27046 (23) | 0.1% | constant | 0.0009 | 0.000 [0.000, 0.000] | 0.500 [0.500, 0.500] | 0.0% / – | 0.0% | 0.0% / – |
| reversal 60 min | 27046 (23) | 0.1% | onboard | 0.0010 | -0.153 [-0.285, -0.089] | 0.547 [0.436, 0.641] | 0.0% / 100.0% | 0.0% | 0.0% / – |
| reversal 60 min | 27046 (23) | 0.1% | onboard+forecast | 0.0009 | -0.066 [-0.117, -0.032] | 0.629 [0.498, 0.727] | 0.0% / 100.0% | 0.0% | 0.0% / 100.0% |
| reversal 60 min | | | AUC gain from the forecast | | | 90% CI [0.009, 0.139] | | | |
| surge 60 min | 27046 (21) | 0.1% | persistence | 0.0008 | 0.409 | 0.500 | 0.0% / – | 0.0% | 0.0% / – |
| surge 60 min | 27046 (21) | 0.1% | constant | 0.0013 | 0.000 [0.000, 0.000] | 0.500 [0.500, 0.500] | 0.0% / – | 0.0% | 0.0% / – |
| surge 60 min | 27046 (21) | 0.1% | onboard | 0.0014 | -0.048 [-0.072, -0.028] | 0.499 [0.374, 0.622] | 0.0% / 100.0% | 0.0% | 0.0% / – |
| surge 60 min | 27046 (21) | 0.1% | onboard+forecast | 0.0011 | 0.162 [0.130, 0.211] | 0.677 [0.549, 0.776] | 0.0% / 100.0% | 0.0% | 0.0% / – |
| surge 60 min | | | AUC gain from the forecast | | | 90% CI [0.107, 0.243] | | | |

Of the shifts that were also reversals (> 135°) or surges, the share each model warned of at P ≥ 0.2:

- shift 30 min, reversals (4): persistence 0.0%, constant 0.0%, onboard 0.0%, onboard+forecast 0.0%
- shift 30 min, surges (10): persistence 0.0%, constant 0.0%, onboard 10.0%, onboard+forecast 10.0%
- shift 60 min, reversals (23): persistence 0.0%, constant 0.0%, onboard 13.0%, onboard+forecast 13.0%
- shift 60 min, surges (21): persistence 0.0%, constant 0.0%, onboard 9.5%, onboard+forecast 9.5%

Wind at t + h (test rows):

| horizon | predictor | vector RMSE m/s | speed MAE m/s | direction MAE ° |
|---|---|---|---|---|
| 30 min | persistence | 1.24 | 0.57 | 9.3 |
| 30 min | hrrr | 2.40 | 1.04 | 26.0 |
| 30 min | blend | 1.32 | 0.72 | 8.7 |
| 60 min | persistence | 1.63 | 0.71 | 13.1 |
| 60 min | hrrr | 2.42 | 1.05 | 26.0 |
| 60 min | blend | 1.65 | 0.89 | 10.9 |

**Follow-up (defined after the first results): only times with wind >= 2.5 m/s at issue**, models refit on those. Concentration = share of the test events in the riskiest 10% / 20% of times (no skill: 10% / 20%).

| event | n test (events) | base rate | model | AUC | BSS vs constant | top 10% holds | top 20% holds | risk in top 10% |
|---|---|---|---|---|---|---|---|---|
| shift 30 min | 9380 (100) | 1.1% | constant | 0.500 | 0.000 | 100.0% | 100.0% | 1.1% |
| shift 30 min | 9380 (100) | 1.1% | onboard | 0.663 | -0.053 | 32.0% | 42.0% | 3.4% |
| shift 30 min | 9380 (100) | 1.1% | onboard+forecast | 0.685 | -0.033 | 32.0% | 42.0% | 3.4% |
| reversal 30 min | | | too few events | | | | | |
| surge 30 min | | | too few events | | | | | |
| shift 60 min | 9263 (283) | 3.1% | constant | 0.500 | 0.000 | 100.0% | 100.0% | 3.1% |
| shift 60 min | 9263 (283) | 3.1% | onboard | 0.573 | -0.156 | 18.0% | 25.4% | 5.5% |
| shift 60 min | 9263 (283) | 3.1% | onboard+forecast | 0.662 | 0.035 | 27.6% | 40.6% | 8.4% |
| reversal 60 min | 9263 (23) | 0.2% | constant | 0.500 | 0.000 | 100.0% | 100.0% | 0.2% |
| reversal 60 min | 9263 (23) | 0.2% | onboard | 0.314 | -0.094 | 8.7% | 8.7% | 0.2% |
| reversal 60 min | 9263 (23) | 0.2% | onboard+forecast | 0.538 | -0.015 | 21.7% | 34.8% | 0.5% |
| surge 60 min | | | too few events | | | | | |

Within each station (the constant rate's concentration above is only the windier station's share; this removes station identity): share of events in a station's riskiest 20%, and AUC.

- shift 30 min, onboard: OVE 42% of 100 (AUC 0.66)
- shift 30 min, onboard+forecast: OVE 42% of 100 (AUC 0.68)
- shift 60 min, onboard: OVE 25% of 283 (AUC 0.57)
- shift 60 min, onboard+forecast: OVE 41% of 283 (AUC 0.66)
- reversal 60 min, onboard: OVE 9% of 23 (AUC 0.31)
- reversal 60 min, onboard+forecast: OVE 35% of 23 (AUC 0.54)
