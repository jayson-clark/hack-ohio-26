# Wind-shift predictability (#231)

81,984 issue times (every 30 min, Sep-Dec 2018-2024, Oroville OVE and Broomfield BJC).

## chronological (train 2018-22, test 2023-24)

| event | n test (events) | base rate | model | Brier | BSS vs constant (90% CI) | AUC (90% CI) | hit / false-alarm @0.2 | warned @0.2 | hit / false-alarm @0.5 |
|---|---|---|---|---|---|---|---|---|---|
| shift 30 min | 9740 (120) | 1.2% | persistence | 0.0123 | -0.024 | 0.500 | 0.0% / – | 0.0% | 0.0% / – |
| shift 30 min | 9740 (120) | 1.2% | constant | 0.0120 | 0.000 [0.000, 0.000] | 0.728 [0.685, 0.765] | 0.0% / – | 0.0% | 0.0% / – |
| shift 30 min | 9740 (120) | 1.2% | onboard | 0.0119 | 0.015 [-0.008, 0.037] | 0.848 [0.816, 0.876] | 5.0% / 77.8% | 0.3% | 0.8% / 83.3% |
| shift 30 min | 9740 (120) | 1.2% | onboard+forecast | 0.0119 | 0.014 [-0.012, 0.038] | 0.864 [0.835, 0.889] | 5.8% / 78.8% | 0.3% | 0.8% / 80.0% |
| shift 30 min | | | AUC gain from the forecast | | | 90% CI [0.004, 0.027] | | | |
| reversal 30 min | 9740 (6) | | too few events to score (35 train, 6 test) | | | | | | |
| surge 30 min | 9740 (35) | 0.4% | persistence | 0.0036 | -0.007 | 0.500 | 0.0% / – | 0.0% | 0.0% / – |
| surge 30 min | 9740 (35) | 0.4% | constant | 0.0036 | 0.000 [0.000, 0.000] | 0.820 [0.788, 0.850] | 0.0% / – | 0.0% | 0.0% / – |
| surge 30 min | 9740 (35) | 0.4% | onboard | 0.0037 | -0.029 [-0.066, 0.006] | 0.837 [0.786, 0.889] | 2.9% / 91.7% | 0.1% | 0.0% / 100.0% |
| surge 30 min | 9740 (35) | 0.4% | onboard+forecast | 0.0036 | -0.022 [-0.066, 0.013] | 0.884 [0.839, 0.925] | 0.0% / 100.0% | 0.1% | 0.0% / 100.0% |
| surge 30 min | | | AUC gain from the forecast | | | 90% CI [0.017, 0.069] | | | |
| shift 60 min | 9676 (237) | 2.4% | persistence | 0.0245 | -0.038 | 0.500 | 0.0% / – | 0.0% | 0.0% / – |
| shift 60 min | 9676 (237) | 2.4% | constant | 0.0236 | 0.000 [0.000, 0.000] | 0.674 [0.625, 0.721] | 0.0% / – | 0.0% | 0.0% / – |
| shift 60 min | 9676 (237) | 2.4% | onboard | 0.0228 | 0.031 [0.009, 0.053] | 0.855 [0.833, 0.877] | 9.3% / 72.5% | 0.8% | 2.1% / 72.2% |
| shift 60 min | 9676 (237) | 2.4% | onboard+forecast | 0.0228 | 0.035 [0.014, 0.057] | 0.869 [0.848, 0.891] | 11.8% / 71.7% | 1.0% | 3.4% / 63.6% |
| shift 60 min | | | AUC gain from the forecast | | | 90% CI [0.005, 0.026] | | | |
| reversal 60 min | 9676 (29) | 0.3% | persistence | 0.0030 | -0.005 | 0.500 | 0.0% / – | 0.0% | 0.0% / – |
| reversal 60 min | 9676 (29) | 0.3% | constant | 0.0030 | 0.000 [0.000, 0.000] | 0.712 [0.618, 0.795] | 0.0% / – | 0.0% | 0.0% / – |
| reversal 60 min | 9676 (29) | 0.3% | onboard | 0.0030 | -0.007 [-0.024, 0.006] | 0.790 [0.695, 0.874] | 0.0% / 100.0% | 0.0% | 0.0% / – |
| reversal 60 min | 9676 (29) | 0.3% | onboard+forecast | 0.0030 | -0.017 [-0.038, -0.001] | 0.876 [0.819, 0.921] | 0.0% / 100.0% | 0.1% | 0.0% / – |
| reversal 60 min | | | AUC gain from the forecast | | | 90% CI [0.019, 0.159] | | | |
| surge 60 min | 9676 (73) | 0.8% | persistence | 0.0075 | -0.021 | 0.500 | 0.0% / – | 0.0% | 0.0% / – |
| surge 60 min | 9676 (73) | 0.8% | constant | 0.0074 | 0.000 [0.000, 0.000] | 0.814 [0.785, 0.835] | 0.0% / – | 0.0% | 0.0% / – |
| surge 60 min | 9676 (73) | 0.8% | onboard | 0.0075 | -0.021 [-0.038, -0.004] | 0.854 [0.816, 0.889] | 0.0% / 100.0% | 0.1% | 0.0% / 100.0% |
| surge 60 min | 9676 (73) | 0.8% | onboard+forecast | 0.0075 | -0.012 [-0.038, 0.014] | 0.898 [0.871, 0.924] | 0.0% / 100.0% | 0.2% | 0.0% / – |
| surge 60 min | | | AUC gain from the forecast | | | 90% CI [0.023, 0.066] | | | |

Of the shifts that were also reversals (> 135°) or surges, the share each model warned of at P ≥ 0.2:

- shift 30 min, reversals (6): persistence 0.0%, constant 0.0%, onboard 0.0%, onboard+forecast 0.0%
- shift 30 min, surges (35): persistence 0.0%, constant 0.0%, onboard 2.9%, onboard+forecast 5.7%
- shift 60 min, reversals (29): persistence 0.0%, constant 0.0%, onboard 10.3%, onboard+forecast 13.8%
- shift 60 min, surges (73): persistence 0.0%, constant 0.0%, onboard 6.8%, onboard+forecast 8.2%

Wind at t + h (test rows):

| horizon | predictor | vector RMSE m/s | speed MAE m/s | direction MAE ° |
|---|---|---|---|---|
| 30 min | persistence | 1.80 | 0.83 | 14.1 |
| 30 min | hrrr | 2.67 | 1.20 | 28.9 |
| 30 min | blend | 1.68 | 0.81 | 12.6 |
| 60 min | persistence | 2.53 | 1.12 | 21.8 |
| 60 min | hrrr | 2.99 | 1.30 | 31.9 |
| 60 min | blend | 2.23 | 1.07 | 17.9 |

**Follow-up (defined after the first results): only times with wind >= 2.5 m/s at issue**, models refit on those. Concentration = share of the test events in the riskiest 10% / 20% of times (no skill: 10% / 20%).

| event | n test (events) | base rate | model | AUC | BSS vs constant | top 10% holds | top 20% holds | risk in top 10% |
|---|---|---|---|---|---|---|---|---|
| shift 30 min | 3679 (120) | 3.3% | constant | 0.707 | 0.000 | 78.3% | 78.3% | 6.7% |
| shift 30 min | 3679 (120) | 3.3% | onboard | 0.792 | 0.025 | 39.2% | 60.0% | 12.8% |
| shift 30 min | 3679 (120) | 3.3% | onboard+forecast | 0.830 | 0.041 | 44.2% | 66.7% | 14.4% |
| reversal 30 min | | | too few events | | | | | |
| surge 30 min | 3679 (20) | 0.5% | constant | 0.785 | 0.000 | 95.0% | 95.0% | 1.4% |
| surge 30 min | 3679 (20) | 0.5% | onboard | 0.833 | -0.009 | 50.0% | 65.0% | 2.7% |
| surge 30 min | 3679 (20) | 0.5% | onboard+forecast | 0.890 | 0.009 | 60.0% | 75.0% | 3.3% |
| shift 60 min | 3702 (237) | 6.4% | constant | 0.651 | 0.000 | 67.5% | 67.5% | 11.0% |
| shift 60 min | 3702 (237) | 6.4% | onboard | 0.743 | 0.025 | 33.3% | 49.4% | 21.3% |
| shift 60 min | 3702 (237) | 6.4% | onboard+forecast | 0.795 | 0.025 | 36.3% | 58.2% | 23.2% |
| reversal 60 min | 3702 (29) | 0.8% | constant | 0.684 | 0.000 | 75.9% | 75.9% | 1.5% |
| reversal 60 min | 3702 (29) | 0.8% | onboard | 0.662 | -0.007 | 34.5% | 48.3% | 2.7% |
| reversal 60 min | 3702 (29) | 0.8% | onboard+forecast | 0.803 | -0.032 | 48.3% | 69.0% | 3.8% |
| surge 60 min | 3702 (37) | 1.0% | constant | 0.793 | 0.000 | 97.3% | 97.3% | 2.5% |
| surge 60 min | 3702 (37) | 1.0% | onboard | 0.848 | -0.025 | 43.2% | 73.0% | 4.3% |
| surge 60 min | 3702 (37) | 1.0% | onboard+forecast | 0.874 | -0.007 | 56.8% | 81.1% | 5.7% |

Within each station (the constant rate's concentration above is only the windier station's share; this removes station identity): share of events in a station's riskiest 20%, and AUC.

- shift 30 min, onboard: BJC 40% of 94 (AUC 0.67); OVE 54% of 26 (AUC 0.74)
- shift 30 min, onboard+forecast: BJC 46% of 94 (AUC 0.72); OVE 69% of 26 (AUC 0.82)
- surge 30 min, onboard: BJC 42% of 19 (AUC 0.67)
- surge 30 min, onboard+forecast: BJC 58% of 19 (AUC 0.79)
- shift 60 min, onboard: BJC 41% of 160 (AUC 0.67); OVE 47% of 77 (AUC 0.75)
- shift 60 min, onboard+forecast: BJC 42% of 160 (AUC 0.71); OVE 62% of 77 (AUC 0.82)
- reversal 60 min, onboard: BJC 36% of 22 (AUC 0.63)
- reversal 60 min, onboard+forecast: BJC 50% of 22 (AUC 0.71)
- surge 60 min, onboard: BJC 39% of 36 (AUC 0.68)
- surge 60 min, onboard+forecast: BJC 50% of 36 (AUC 0.74)

## across stations (train OVE, test BJC)

| event | n test (events) | base rate | model | Brier | BSS vs constant (90% CI) | AUC (90% CI) | hit / false-alarm @0.2 | warned @0.2 | hit / false-alarm @0.5 |
|---|---|---|---|---|---|---|---|---|---|
| shift 30 min | 11383 (319) | 2.8% | persistence | 0.0280 | -0.007 | 0.500 | 0.0% / – | 0.0% | 0.0% / – |
| shift 30 min | 11383 (319) | 2.8% | constant | 0.0278 | 0.000 [0.000, 0.000] | 0.500 [0.500, 0.500] | 0.0% / – | 0.0% | 0.0% / – |
| shift 30 min | 11383 (319) | 2.8% | onboard | 0.0299 | -0.074 [-0.112, -0.039] | 0.749 [0.721, 0.771] | 9.4% / 85.8% | 1.9% | 4.4% / 84.8% |
| shift 30 min | 11383 (319) | 2.8% | onboard+forecast | 0.0297 | -0.065 [-0.110, -0.027] | 0.748 [0.723, 0.771] | 10.7% / 85.0% | 2.0% | 4.7% / 83.3% |
| shift 30 min | | | AUC gain from the forecast | | | 90% CI [-0.013, 0.012] | | | |
| reversal 30 min | 11383 (37) | | too few events to score (4 train, 37 test) | | | | | | |
| surge 30 min | 11383 (164) | | too few events to score (10 train, 164 test) | | | | | | |
| shift 60 min | 11522 (577) | 5.0% | persistence | 0.0501 | -0.019 | 0.500 | 0.0% / – | 0.0% | 0.0% / – |
| shift 60 min | 11522 (577) | 5.0% | constant | 0.0491 | 0.000 [0.000, 0.000] | 0.500 [0.500, 0.500] | 0.0% / – | 0.0% | 0.0% / – |
| shift 60 min | 11522 (577) | 5.0% | onboard | 0.0497 | -0.012 [-0.047, 0.023] | 0.765 [0.748, 0.781] | 23.2% / 74.6% | 4.6% | 11.6% / 70.5% |
| shift 60 min | 11522 (577) | 5.0% | onboard+forecast | 0.0512 | -0.041 [-0.084, -0.001] | 0.773 [0.758, 0.789] | 25.5% / 77.6% | 5.7% | 13.3% / 72.0% |
| shift 60 min | | | AUC gain from the forecast | | | 90% CI [-0.001, 0.019] | | | |
| reversal 60 min | 11522 (71) | | too few events to score (23 train, 71 test) | | | | | | |
| surge 60 min | 11522 (276) | | too few events to score (21 train, 276 test) | | | | | | |

Of the shifts that were also reversals (> 135°) or surges, the share each model warned of at P ≥ 0.2:

- shift 30 min, reversals (37): persistence 0.0%, constant 0.0%, onboard 5.4%, onboard+forecast 8.1%
- shift 30 min, surges (164): persistence 0.0%, constant 0.0%, onboard 9.1%, onboard+forecast 13.4%
- shift 60 min, reversals (71): persistence 0.0%, constant 0.0%, onboard 21.1%, onboard+forecast 26.8%
- shift 60 min, surges (276): persistence 0.0%, constant 0.0%, onboard 12.7%, onboard+forecast 20.3%

Wind at t + h (test rows):

| horizon | predictor | vector RMSE m/s | speed MAE m/s | direction MAE ° |
|---|---|---|---|---|
| 30 min | persistence | 2.52 | 1.27 | 19.8 |
| 30 min | hrrr | 3.64 | 1.81 | 39.3 |
| 30 min | blend | 2.39 | 1.26 | 18.7 |
| 60 min | persistence | 3.26 | 1.57 | 27.2 |
| 60 min | hrrr | 3.86 | 1.81 | 40.8 |
| 60 min | blend | 2.97 | 1.55 | 24.1 |

**Follow-up (defined after the first results): only times with wind >= 2.5 m/s at issue**, models refit on those. Concentration = share of the test events in the riskiest 10% / 20% of times (no skill: 10% / 20%).

| event | n test (events) | base rate | model | AUC | BSS vs constant | top 10% holds | top 20% holds | risk in top 10% |
|---|---|---|---|---|---|---|---|---|
| shift 30 min | 5211 (319) | 6.1% | constant | 0.500 | 0.000 | 100.0% | 100.0% | 6.1% |
| shift 30 min | 5211 (319) | 6.1% | onboard | 0.653 | 0.029 | 25.4% | 39.8% | 15.5% |
| shift 30 min | 5211 (319) | 6.1% | onboard+forecast | 0.685 | 0.031 | 28.2% | 40.8% | 17.2% |
| reversal 30 min | | | too few events | | | | | |
| surge 30 min | | | too few events | | | | | |
| shift 60 min | 5430 (577) | 10.6% | constant | 0.500 | 0.000 | 100.0% | 100.0% | 10.6% |
| shift 60 min | 5430 (577) | 10.6% | onboard | 0.641 | 0.071 | 25.8% | 37.6% | 27.4% |
| shift 60 min | 5430 (577) | 10.6% | onboard+forecast | 0.689 | 0.065 | 26.2% | 41.1% | 27.8% |
| reversal 60 min | | | too few events | | | | | |
| surge 60 min | | | too few events | | | | | |

Within each station (the constant rate's concentration above is only the windier station's share; this removes station identity): share of events in a station's riskiest 20%, and AUC.

- shift 30 min, onboard: BJC 40% of 319 (AUC 0.65)
- shift 30 min, onboard+forecast: BJC 41% of 319 (AUC 0.68)
- shift 60 min, onboard: BJC 38% of 577 (AUC 0.64)
- shift 60 min, onboard+forecast: BJC 41% of 577 (AUC 0.69)

## across stations (train BJC, test OVE)

| event | n test (events) | base rate | model | Brier | BSS vs constant (90% CI) | AUC (90% CI) | hit / false-alarm @0.2 | warned @0.2 | hit / false-alarm @0.5 |
|---|---|---|---|---|---|---|---|---|---|
| shift 30 min | 27384 (100) | 0.4% | persistence | 0.0037 | 0.137 | 0.500 | 0.0% / – | 0.0% | 0.0% / – |
| shift 30 min | 27384 (100) | 0.4% | constant | 0.0042 | 0.000 [0.000, 0.000] | 0.500 [0.500, 0.500] | 0.0% / – | 0.0% | 0.0% / – |
| shift 30 min | 27384 (100) | 0.4% | onboard | 0.0046 | -0.079 [-0.126, -0.044] | 0.808 [0.778, 0.836] | 1.0% / 98.7% | 0.3% | 0.0% / 100.0% |
| shift 30 min | 27384 (100) | 0.4% | onboard+forecast | 0.0042 | 0.001 [-0.025, 0.024] | 0.798 [0.766, 0.831] | 3.0% / 92.9% | 0.2% | 0.0% / 100.0% |
| shift 30 min | | | AUC gain from the forecast | | | 90% CI [-0.028, 0.008] | | | |
| reversal 30 min | 27384 (4) | | too few events to score (37 train, 4 test) | | | | | | |
| surge 30 min | 27384 (10) | | too few events to score (164 train, 10 test) | | | | | | |
| shift 60 min | 27046 (284) | 1.1% | persistence | 0.0105 | 0.122 | 0.500 | 0.0% / – | 0.0% | 0.0% / – |
| shift 60 min | 27046 (284) | 1.1% | constant | 0.0120 | 0.000 [0.000, 0.000] | 0.500 [0.500, 0.500] | 0.0% / – | 0.0% | 0.0% / – |
| shift 60 min | 27046 (284) | 1.1% | onboard | 0.0155 | -0.298 [-0.402, -0.210] | 0.790 [0.767, 0.810] | 8.8% / 97.6% | 3.8% | 0.7% / 97.7% |
| shift 60 min | 27046 (284) | 1.1% | onboard+forecast | 0.0134 | -0.118 [-0.178, -0.064] | 0.800 [0.777, 0.821] | 7.7% / 96.5% | 2.3% | 0.7% / 95.0% |
| shift 60 min | | | AUC gain from the forecast | | | 90% CI [0.003, 0.017] | | | |
| reversal 60 min | 27046 (23) | 0.1% | persistence | 0.0009 | 0.031 | 0.500 | 0.0% / – | 0.0% | 0.0% / – |
| reversal 60 min | 27046 (23) | 0.1% | constant | 0.0009 | 0.000 [0.000, 0.000] | 0.500 [0.500, 0.500] | 0.0% / – | 0.0% | 0.0% / – |
| reversal 60 min | 27046 (23) | 0.1% | onboard | 0.0010 | -0.153 [-0.285, -0.089] | 0.547 [0.436, 0.641] | 0.0% / 100.0% | 0.0% | 0.0% / – |
| reversal 60 min | 27046 (23) | 0.1% | onboard+forecast | 0.0009 | -0.061 [-0.120, -0.029] | 0.648 [0.513, 0.751] | 0.0% / 100.0% | 0.0% | 0.0% / – |
| reversal 60 min | | | AUC gain from the forecast | | | 90% CI [0.022, 0.169] | | | |
| surge 60 min | 27046 (21) | 0.1% | persistence | 0.0008 | 0.409 | 0.500 | 0.0% / – | 0.0% | 0.0% / – |
| surge 60 min | 27046 (21) | 0.1% | constant | 0.0013 | 0.000 [0.000, 0.000] | 0.500 [0.500, 0.500] | 0.0% / – | 0.0% | 0.0% / – |
| surge 60 min | 27046 (21) | 0.1% | onboard | 0.0014 | -0.047 [-0.072, -0.028] | 0.499 [0.374, 0.623] | 0.0% / 100.0% | 0.0% | 0.0% / – |
| surge 60 min | 27046 (21) | 0.1% | onboard+forecast | 0.0011 | 0.197 [0.157, 0.255] | 0.662 [0.548, 0.755] | 0.0% / 100.0% | 0.0% | 0.0% / – |
| surge 60 min | | | AUC gain from the forecast | | | 90% CI [0.105, 0.217] | | | |

Of the shifts that were also reversals (> 135°) or surges, the share each model warned of at P ≥ 0.2:

- shift 30 min, reversals (4): persistence 0.0%, constant 0.0%, onboard 0.0%, onboard+forecast 25.0%
- shift 30 min, surges (10): persistence 0.0%, constant 0.0%, onboard 10.0%, onboard+forecast 10.0%
- shift 60 min, reversals (23): persistence 0.0%, constant 0.0%, onboard 13.0%, onboard+forecast 8.7%
- shift 60 min, surges (21): persistence 0.0%, constant 0.0%, onboard 9.5%, onboard+forecast 9.5%

Wind at t + h (test rows):

| horizon | predictor | vector RMSE m/s | speed MAE m/s | direction MAE ° |
|---|---|---|---|---|
| 30 min | persistence | 1.24 | 0.57 | 9.4 |
| 30 min | hrrr | 2.24 | 0.98 | 24.4 |
| 30 min | blend | 1.32 | 0.72 | 8.8 |
| 60 min | persistence | 1.63 | 0.72 | 13.1 |
| 60 min | hrrr | 2.25 | 0.98 | 24.5 |
| 60 min | blend | 1.63 | 0.87 | 10.9 |

**Follow-up (defined after the first results): only times with wind >= 2.5 m/s at issue**, models refit on those. Concentration = share of the test events in the riskiest 10% / 20% of times (no skill: 10% / 20%).

| event | n test (events) | base rate | model | AUC | BSS vs constant | top 10% holds | top 20% holds | risk in top 10% |
|---|---|---|---|---|---|---|---|---|
| shift 30 min | 9385 (100) | 1.1% | constant | 0.500 | 0.000 | 100.0% | 100.0% | 1.1% |
| shift 30 min | 9385 (100) | 1.1% | onboard | 0.664 | -0.052 | 32.0% | 41.0% | 3.4% |
| shift 30 min | 9385 (100) | 1.1% | onboard+forecast | 0.704 | 0.055 | 33.0% | 44.0% | 3.5% |
| reversal 30 min | | | too few events | | | | | |
| surge 30 min | | | too few events | | | | | |
| shift 60 min | 9268 (284) | 3.1% | constant | 0.500 | 0.000 | 100.0% | 100.0% | 3.1% |
| shift 60 min | 9268 (284) | 3.1% | onboard | 0.572 | -0.156 | 18.0% | 25.4% | 5.5% |
| shift 60 min | 9268 (284) | 3.1% | onboard+forecast | 0.654 | 0.037 | 26.1% | 39.8% | 8.0% |
| reversal 60 min | 9268 (23) | 0.2% | constant | 0.500 | 0.000 | 100.0% | 100.0% | 0.2% |
| reversal 60 min | 9268 (23) | 0.2% | onboard | 0.314 | -0.094 | 8.7% | 8.7% | 0.2% |
| reversal 60 min | 9268 (23) | 0.2% | onboard+forecast | 0.498 | -0.009 | 21.7% | 26.1% | 0.5% |
| surge 60 min | | | too few events | | | | | |

Within each station (the constant rate's concentration above is only the windier station's share; this removes station identity): share of events in a station's riskiest 20%, and AUC.

- shift 30 min, onboard: OVE 41% of 100 (AUC 0.66)
- shift 30 min, onboard+forecast: OVE 44% of 100 (AUC 0.70)
- shift 60 min, onboard: OVE 25% of 284 (AUC 0.57)
- shift 60 min, onboard+forecast: OVE 40% of 284 (AUC 0.65)
- reversal 60 min, onboard: OVE 9% of 23 (AUC 0.31)
- reversal 60 min, onboard+forecast: OVE 26% of 23 (AUC 0.50)
