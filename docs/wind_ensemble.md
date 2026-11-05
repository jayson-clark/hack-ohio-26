# Wind-scenario ensemble vs constant wind (#228), phase final

Seeds 4-11, schedules steady, veer, reversal, surge, flipflop, gusty; 32 rollouts, a forecast every 5 min for 300 min, target miss 10%. Pre-shift = issued in the h minutes before an abrupt shift (reversal, surge, flipflop).

## Equal risk, no controller: area needed for a pooled 10% miss

| forecaster | horizon | cutoff θ | pooled miss | area km² | pre-shift miss | pre-shift area km² | steady miss | veer miss | reversal miss | surge miss | flipflop miss | gusty miss |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| constant | T+30 | 0.093 | 9.7% | 12.81 | 20.5% | 6.93 | 4.0% | 4.6% | 5.9% | 8.3% | 20.6% | 16.9% |
| constant | T+60 | 0.031 | 7.7% | 44.92 | 24.2% | 27.53 | 1.0% | 2.1% | 4.8% | 7.2% | 21.2% | 12.3% |
| ensemble | T+30 | 0.125 | 10.0% | 13.29 | 20.3% | 7.03 | 4.4% | 5.0% | 6.1% | 8.7% | 20.4% | 17.1% |
| ensemble | T+60 | 0.062 | 8.7% | 45.37 | 25.3% | 23.26 | 2.1% | 2.9% | 5.7% | 9.3% | 20.9% | 13.8% |
| ensemble 1/h (exploratory) | T+30 | 0.125 | 9.3% | 14.52 | 17.5% | 7.63 | 4.4% | 5.0% | 5.7% | 8.9% | 17.9% | 15.2% |
| ensemble 1/h (exploratory) | T+60 | 0.093 | 8.9% | 51.59 | 20.7% | 24.46 | 3.9% | 4.7% | 6.3% | 11.6% | 14.9% | 13.3% |
| U-Net original | T+30 | 0.160 | 9.9% | 12.53 | 19.2% | 7.40 | 4.4% | 4.7% | 6.1% | 11.3% | 19.6% | 15.3% |
| U-Net original | T+60 | 0.089 | 9.9% | 32.08 | 27.2% | 20.30 | 2.7% | 3.6% | 6.4% | 12.3% | 24.2% | 12.7% |
| U-Net wind-aware | T+30 | 0.125 | 9.9% | 13.49 | 20.1% | 7.58 | 4.2% | 4.6% | 6.3% | 10.1% | 20.1% | 16.1% |
| U-Net wind-aware | T+60 | 0.082 | 9.8% | 36.43 | 27.1% | 20.20 | 2.7% | 3.2% | 6.6% | 11.6% | 23.5% | 13.6% |
| U-Net wind-aware 1/h (exploratory) | T+30 | 0.132 | 9.9% | 13.24 | 18.9% | 7.49 | 4.2% | 5.0% | 6.1% | 11.3% | 18.7% | 16.0% |
| U-Net wind-aware 1/h (exploratory) | T+60 | 0.097 | 9.8% | 36.46 | 24.7% | 19.99 | 3.3% | 3.8% | 6.8% | 13.5% | 19.6% | 13.8% |

## Under the static controller

| forecaster | horizon | schedule | miss | worst 30 min | area km² | vs oracle | pre-shift miss | pre-shift area km² | recovery (shown) | post-shift miss | at widest | infeasible |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| constant | T+30 | all | 15.5% | 33.7% | 10.28 | 0.75× | 26.2% | 5.62 | 41 | 12.6% | 0.0% | 1.1% |
| ensemble | T+30 | all | 14.3% | 32.8% | 11.09 | 0.81× | 24.8% | 5.91 | 38 | 12.8% | 0.0% | 1.0% |
| ensemble 1/h (exploratory) | T+30 | all | 14.6% | 33.3% | 11.35 | 0.81× | 23.6% | 5.95 | 38 | 13.1% | 0.0% | 0.8% |
| U-Net original | T+30 | all | 11.9% | 28.9% | 11.57 | 0.85× | 21.2% | 6.71 | 55 | 15.9% | 0.0% | 2.0% |
| U-Net wind-aware | T+30 | all | 14.4% | 33.7% | 11.56 | 0.84× | 25.3% | 6.27 | 47 | 14.7% | 0.0% | 1.9% |
| U-Net wind-aware 1/h (exploratory) | T+30 | all | 14.4% | 33.2% | 11.42 | 0.84× | 23.8% | 6.23 | 49 | 15.0% | 0.0% | 1.9% |
| constant | T+30 | steady | 9.1% | 20.8% | 8.10 | 1.02× | – | – | – | – | 0.0% | 0.0% |
| ensemble | T+30 | steady | 8.1% | 20.1% | 8.46 | 1.04× | – | – | – | – | 0.0% | 0.0% |
| ensemble 1/h (exploratory) | T+30 | steady | 8.9% | 21.7% | 8.52 | 0.98× | – | – | – | – | 0.0% | 0.2% |
| U-Net original | T+30 | steady | 6.0% | 15.9% | 9.46 | 1.12× | – | – | – | – | 0.0% | 0.7% |
| U-Net wind-aware | T+30 | steady | 8.0% | 20.1% | 8.93 | 1.06× | – | – | – | – | 0.0% | 0.7% |
| U-Net wind-aware 1/h (exploratory) | T+30 | steady | 8.1% | 19.9% | 8.94 | 1.06× | – | – | – | – | 0.0% | 0.7% |
| constant | T+30 | veer | 9.8% | 20.4% | 8.20 | 0.99× | – | – | – | – | 0.0% | 0.7% |
| ensemble | T+30 | veer | 8.9% | 19.9% | 8.54 | 1.02× | – | – | – | – | 0.0% | 0.7% |
| ensemble 1/h (exploratory) | T+30 | veer | 9.6% | 21.3% | 8.56 | 0.99× | – | – | – | – | 0.0% | 0.4% |
| U-Net original | T+30 | veer | 6.3% | 16.4% | 9.69 | 1.11× | – | – | – | – | 0.0% | 0.9% |
| U-Net wind-aware | T+30 | veer | 8.7% | 22.5% | 9.12 | 1.06× | – | – | – | – | 0.0% | 0.7% |
| U-Net wind-aware 1/h (exploratory) | T+30 | veer | 9.2% | 22.4% | 9.02 | 1.03× | – | – | – | – | 0.0% | 0.7% |
| constant | T+30 | reversal | 10.4% | 29.6% | 9.42 | 0.94× | 20.1% | 6.16 | 31 | 12.5% | 0.0% | 1.2% |
| ensemble | T+30 | reversal | 9.8% | 29.0% | 9.86 | 0.96× | 18.8% | 6.45 | 30 | 15.2% | 0.0% | 0.2% |
| ensemble 1/h (exploratory) | T+30 | reversal | 10.4% | 29.2% | 9.90 | 0.92× | 17.3% | 6.51 | 31 | 15.6% | 0.0% | 0.7% |
| U-Net original | T+30 | reversal | 7.6% | 24.8% | 11.25 | 1.12× | 14.4% | 7.28 | 30 | 14.2% | 0.0% | 1.2% |
| U-Net wind-aware | T+30 | reversal | 10.0% | 27.6% | 10.56 | 1.03× | 18.6% | 6.87 | 31 | 15.4% | 0.0% | 1.2% |
| U-Net wind-aware 1/h (exploratory) | T+30 | reversal | 9.8% | 27.9% | 10.57 | 1.04× | 17.4% | 6.86 | 33 | 15.0% | 0.0% | 1.2% |
| constant | T+30 | surge | 15.2% | 46.2% | 21.29 | 0.91× | 44.9% | 4.00 | 52 | 12.7% | 0.0% | 2.3% |
| ensemble | T+30 | surge | 13.3% | 43.5% | 24.16 | 1.00× | 43.6% | 4.09 | 45 | 10.5% | 0.0% | 2.3% |
| ensemble 1/h (exploratory) | T+30 | surge | 13.9% | 45.4% | 25.40 | 0.98× | 45.9% | 4.07 | 46 | 10.7% | 0.0% | 2.1% |
| U-Net original | T+30 | surge | 13.8% | 38.3% | 21.85 | 0.81× | 37.4% | 4.59 | 81 | 17.6% | 0.0% | 5.8% |
| U-Net wind-aware | T+30 | surge | 14.6% | 43.2% | 24.21 | 0.91× | 44.5% | 4.04 | 64 | 13.9% | 0.0% | 5.3% |
| U-Net wind-aware 1/h (exploratory) | T+30 | surge | 15.9% | 44.8% | 23.75 | 0.88× | 46.6% | 3.96 | 66 | 14.9% | 0.0% | 5.3% |
| constant | T+30 | flipflop | 26.0% | 41.2% | 5.06 | 0.32× | 24.3% | 5.79 | – | – | 0.0% | 1.6% |
| ensemble | T+30 | flipflop | 24.7% | 39.8% | 5.33 | 0.34× | 22.8% | 6.11 | – | – | 0.0% | 1.3% |
| ensemble 1/h (exploratory) | T+30 | flipflop | 24.0% | 39.5% | 5.39 | 0.37× | 21.2% | 6.16 | – | – | 0.0% | 0.5% |
| U-Net original | T+30 | flipflop | 21.6% | 39.8% | 6.04 | 0.45× | 19.7% | 6.95 | – | – | 0.0% | 1.3% |
| U-Net wind-aware | T+30 | flipflop | 25.1% | 44.1% | 5.65 | 0.41× | 23.4% | 6.53 | – | – | 0.0% | 1.3% |
| U-Net wind-aware 1/h (exploratory) | T+30 | flipflop | 23.5% | 41.3% | 5.62 | 0.43× | 21.3% | 6.48 | – | – | 0.0% | 1.3% |
| constant | T+30 | gusty | 24.4% | 44.1% | 8.89 | 0.51× | – | – | – | – | 0.0% | 1.0% |
| ensemble | T+30 | gusty | 23.2% | 44.2% | 9.36 | 0.57× | – | – | – | – | 0.0% | 1.2% |
| ensemble 1/h (exploratory) | T+30 | gusty | 22.5% | 42.7% | 9.44 | 0.59× | – | – | – | – | 0.0% | 0.5% |
| U-Net original | T+30 | gusty | 17.8% | 38.5% | 10.37 | 0.72× | – | – | – | – | 0.0% | 2.2% |
| U-Net wind-aware | T+30 | gusty | 21.8% | 44.3% | 10.06 | 0.68× | – | – | – | – | 0.0% | 2.0% |
| U-Net wind-aware 1/h (exploratory) | T+30 | gusty | 21.5% | 42.8% | 9.81 | 0.68× | – | – | – | – | 0.0% | 2.0% |
| constant | T+60 | all | 16.7% | 41.1% | 23.89 | 0.76× | 38.0% | 13.24 | 40 | 9.5% | 0.0% | 5.0% |
| ensemble | T+60 | all | 14.4% | 38.9% | 28.59 | 0.80× | 35.0% | 15.09 | 36 | 7.5% | 0.0% | 3.3% |
| ensemble 1/h (exploratory) | T+60 | all | 13.5% | 37.6% | 33.85 | 0.83× | 28.8% | 16.95 | 39 | 8.3% | 0.0% | 2.2% |
| U-Net original | T+60 | all | 12.4% | 34.5% | 27.71 | 0.89× | 30.5% | 17.21 | 48 | 14.8% | 0.0% | 6.4% |
| U-Net wind-aware | T+60 | all | 13.9% | 37.1% | 29.05 | 0.91× | 32.9% | 15.75 | 44 | 13.3% | 0.0% | 5.4% |
| U-Net wind-aware 1/h (exploratory) | T+60 | all | 14.3% | 37.5% | 29.13 | 0.90× | 30.9% | 15.44 | 51 | 13.6% | 0.0% | 4.5% |
| constant | T+60 | steady | 6.8% | 16.3% | 18.42 | 1.06× | – | – | – | – | 0.0% | 0.0% |
| ensemble | T+60 | steady | 5.2% | 13.9% | 20.79 | 1.10× | – | – | – | – | 0.0% | 0.0% |
| ensemble 1/h (exploratory) | T+60 | steady | 6.8% | 17.9% | 22.98 | 0.93× | – | – | – | – | 0.0% | 0.0% |
| U-Net original | T+60 | steady | 4.1% | 13.7% | 22.60 | 1.16× | – | – | – | – | 0.0% | 2.5% |
| U-Net wind-aware | T+60 | steady | 5.3% | 14.8% | 22.13 | 1.15× | – | – | – | – | 0.0% | 1.6% |
| U-Net wind-aware 1/h (exploratory) | T+60 | steady | 6.5% | 15.9% | 21.65 | 1.09× | – | – | – | – | 0.0% | 0.9% |
| constant | T+60 | veer | 10.2% | 23.6% | 18.62 | 0.96× | – | – | – | – | 0.0% | 1.3% |
| ensemble | T+60 | veer | 7.6% | 20.4% | 20.95 | 1.02× | – | – | – | – | 0.0% | 0.9% |
| ensemble 1/h (exploratory) | T+60 | veer | 8.4% | 20.6% | 22.95 | 0.89× | – | – | – | – | 0.0% | 0.4% |
| U-Net original | T+60 | veer | 5.9% | 14.8% | 22.32 | 1.12× | – | – | – | – | 0.0% | 1.3% |
| U-Net wind-aware | T+60 | veer | 6.9% | 17.5% | 22.21 | 1.14× | – | – | – | – | 0.0% | 1.3% |
| U-Net wind-aware 1/h (exploratory) | T+60 | veer | 8.2% | 19.3% | 22.15 | 1.09× | – | – | – | – | 0.0% | 1.3% |
| constant | T+60 | reversal | 10.6% | 43.2% | 21.91 | 0.91× | 21.7% | 12.40 | 45 | 11.0% | 0.0% | 4.1% |
| ensemble | T+60 | reversal | 9.1% | 42.1% | 24.92 | 0.88× | 20.1% | 13.93 | 44 | 9.7% | 0.0% | 1.9% |
| ensemble 1/h (exploratory) | T+60 | reversal | 9.4% | 39.4% | 27.05 | 0.78× | 16.8% | 15.49 | 45 | 10.2% | 0.0% | 0.7% |
| U-Net original | T+60 | reversal | 7.6% | 39.7% | 28.58 | 1.19× | 17.2% | 15.23 | 30 | 11.8% | 0.0% | 5.3% |
| U-Net wind-aware | T+60 | reversal | 9.4% | 41.6% | 27.08 | 1.09× | 18.6% | 14.49 | 31 | 14.1% | 0.0% | 3.6% |
| U-Net wind-aware 1/h (exploratory) | T+60 | reversal | 10.0% | 39.9% | 27.07 | 1.06× | 17.4% | 14.31 | 45 | 14.5% | 0.0% | 1.7% |
| constant | T+60 | surge | 15.5% | 62.5% | 46.90 | 1.07× | 50.3% | 8.42 | 34 | 8.0% | 0.0% | 10.1% |
| ensemble | T+60 | surge | 13.4% | 60.7% | 61.92 | 1.30× | 49.3% | 8.94 | 29 | 5.4% | 0.0% | 9.4% |
| ensemble 1/h (exploratory) | T+60 | surge | 14.8% | 62.6% | 82.22 | 1.39× | 52.0% | 9.85 | 33 | 6.4% | 0.0% | 8.3% |
| U-Net original | T+60 | surge | 15.3% | 54.0% | 47.76 | 0.91× | 41.3% | 10.65 | 66 | 17.9% | 0.0% | 17.5% |
| U-Net wind-aware | T+60 | surge | 15.6% | 56.9% | 58.07 | 0.99× | 47.7% | 9.32 | 56 | 12.5% | 0.0% | 17.3% |
| U-Net wind-aware 1/h (exploratory) | T+60 | surge | 17.4% | 59.9% | 59.76 | 0.90× | 53.0% | 8.77 | 57 | 12.8% | 0.0% | 17.3% |
| constant | T+60 | flipflop | 34.5% | 52.7% | 13.40 | 0.31× | 39.2% | 14.65 | – | – | 0.0% | 3.5% |
| ensemble | T+60 | flipflop | 31.0% | 50.3% | 15.48 | 0.28× | 35.4% | 16.90 | – | – | 0.0% | 1.3% |
| ensemble 1/h (exploratory) | T+60 | flipflop | 23.6% | 42.7% | 17.58 | 0.32× | 26.2% | 19.07 | – | – | 0.0% | 0.3% |
| U-Net original | T+60 | flipflop | 27.5% | 48.0% | 17.73 | 0.47× | 31.4% | 19.34 | – | – | 0.0% | 3.2% |
| U-Net wind-aware | T+60 | flipflop | 29.3% | 50.3% | 16.18 | 0.45× | 33.0% | 17.66 | – | – | 0.0% | 1.3% |
| U-Net wind-aware 1/h (exploratory) | T+60 | flipflop | 26.1% | 46.5% | 15.93 | 0.54× | 29.1% | 17.38 | – | – | 0.0% | 0.8% |
| constant | T+60 | gusty | 25.7% | 48.4% | 22.73 | 0.53× | – | – | – | – | 0.0% | 11.3% |
| ensemble | T+60 | gusty | 22.9% | 45.9% | 25.70 | 0.55× | – | – | – | – | 0.0% | 5.9% |
| ensemble 1/h (exploratory) | T+60 | gusty | 19.9% | 42.7% | 27.89 | 0.59× | – | – | – | – | 0.0% | 3.2% |
| U-Net original | T+60 | gusty | 16.4% | 36.8% | 26.10 | 0.75× | – | – | – | – | 0.0% | 8.6% |
| U-Net wind-aware | T+60 | gusty | 19.3% | 41.5% | 26.97 | 0.78× | – | – | – | – | 0.0% | 6.9% |
| U-Net wind-aware 1/h (exploratory) | T+60 | gusty | 19.6% | 43.6% | 26.46 | 0.80× | – | – | – | – | 0.0% | 4.7% |

## Under the aci controller

| forecaster | horizon | schedule | miss | worst 30 min | area km² | vs oracle | pre-shift miss | pre-shift area km² | recovery (shown) | post-shift miss | at widest | infeasible |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| constant | T+30 | all | 10.8% | 32.0% | 16.57 | 1.21× | 15.0% | 17.26 | 26 | 6.6% | 0.0% | 1.1% |
| ensemble | T+30 | all | 10.4% | 31.2% | 17.73 | 1.29× | 14.7% | 16.47 | 26 | 6.2% | 0.0% | 1.0% |
| ensemble 1/h (exploratory) | T+30 | all | 10.3% | 31.5% | 21.89 | 1.55× | 13.8% | 15.58 | 28 | 6.0% | 0.0% | 0.8% |
| U-Net original | T+30 | all | 10.0% | 29.0% | 15.99 | 1.17× | 15.3% | 14.31 | 40 | 12.0% | 0.2% | 2.0% |
| U-Net wind-aware | T+30 | all | 10.6% | 31.7% | 17.40 | 1.27× | 15.3% | 15.58 | 35 | 9.7% | 0.1% | 1.9% |
| U-Net wind-aware 1/h (exploratory) | T+30 | all | 10.6% | 31.1% | 17.56 | 1.29× | 14.8% | 14.41 | 36 | 9.5% | 0.0% | 1.9% |
| constant | T+30 | steady | 8.9% | 22.2% | 8.08 | 1.02× | – | – | – | – | 0.0% | 0.0% |
| ensemble | T+30 | steady | 8.6% | 21.6% | 8.24 | 1.01× | – | – | – | – | 0.0% | 0.0% |
| ensemble 1/h (exploratory) | T+30 | steady | 8.8% | 22.6% | 8.66 | 0.99× | – | – | – | – | 0.0% | 0.2% |
| U-Net original | T+30 | steady | 7.9% | 18.5% | 8.56 | 1.02× | – | – | – | – | 0.0% | 0.7% |
| U-Net wind-aware | T+30 | steady | 8.6% | 22.4% | 8.61 | 1.03× | – | – | – | – | 0.0% | 0.7% |
| U-Net wind-aware 1/h (exploratory) | T+30 | steady | 8.8% | 21.6% | 8.53 | 1.01× | – | – | – | – | 0.0% | 0.7% |
| constant | T+30 | veer | 9.1% | 21.2% | 8.31 | 1.01× | – | – | – | – | 0.0% | 0.7% |
| ensemble | T+30 | veer | 8.7% | 20.7% | 8.46 | 1.01× | – | – | – | – | 0.0% | 0.7% |
| ensemble 1/h (exploratory) | T+30 | veer | 8.9% | 22.3% | 8.99 | 1.03× | – | – | – | – | 0.0% | 0.4% |
| U-Net original | T+30 | veer | 7.7% | 18.5% | 9.02 | 1.04× | – | – | – | – | 0.0% | 0.9% |
| U-Net wind-aware | T+30 | veer | 8.6% | 22.8% | 8.98 | 1.04× | – | – | – | – | 0.0% | 0.7% |
| U-Net wind-aware 1/h (exploratory) | T+30 | veer | 8.9% | 21.9% | 8.94 | 1.02× | – | – | – | – | 0.0% | 0.7% |
| constant | T+30 | reversal | 9.3% | 30.2% | 11.52 | 1.15× | 17.4% | 7.60 | 28 | 7.6% | 0.0% | 1.2% |
| ensemble | T+30 | reversal | 9.0% | 30.3% | 12.17 | 1.19× | 16.8% | 8.05 | 29 | 7.5% | 0.0% | 0.2% |
| ensemble 1/h (exploratory) | T+30 | reversal | 9.1% | 29.6% | 13.42 | 1.25× | 14.8% | 9.23 | 29 | 7.5% | 0.0% | 0.7% |
| U-Net original | T+30 | reversal | 8.2% | 26.8% | 11.46 | 1.14× | 14.7% | 7.22 | 30 | 13.9% | 0.0% | 1.2% |
| U-Net wind-aware | T+30 | reversal | 9.2% | 29.5% | 12.01 | 1.17× | 16.5% | 7.74 | 29 | 11.7% | 0.0% | 1.2% |
| U-Net wind-aware 1/h (exploratory) | T+30 | reversal | 9.0% | 29.2% | 11.68 | 1.15× | 15.6% | 7.65 | 32 | 11.5% | 0.0% | 1.2% |
| constant | T+30 | surge | 9.9% | 39.4% | 32.45 | 1.39× | 31.2% | 5.32 | 24 | 5.6% | 0.0% | 2.3% |
| ensemble | T+30 | surge | 9.0% | 36.5% | 37.94 | 1.57× | 30.8% | 5.10 | 24 | 4.9% | 0.0% | 2.3% |
| ensemble 1/h (exploratory) | T+30 | surge | 9.1% | 38.6% | 61.46 | 2.36× | 33.3% | 4.99 | 27 | 4.5% | 0.0% | 2.1% |
| U-Net original | T+30 | surge | 10.3% | 37.6% | 36.32 | 1.34× | 36.8% | 4.36 | 49 | 10.0% | 0.7% | 5.8% |
| U-Net wind-aware | T+30 | surge | 10.0% | 37.6% | 41.58 | 1.55× | 34.1% | 4.81 | 41 | 7.6% | 0.0% | 5.3% |
| U-Net wind-aware 1/h (exploratory) | T+30 | surge | 10.1% | 37.9% | 44.64 | 1.65× | 34.1% | 4.95 | 40 | 7.5% | 0.0% | 5.3% |
| constant | T+30 | flipflop | 14.5% | 39.1% | 16.74 | 1.05× | 12.1% | 20.60 | – | – | 0.3% | 1.6% |
| ensemble | T+30 | flipflop | 14.2% | 37.5% | 16.18 | 1.03× | 11.8% | 19.53 | – | – | 0.3% | 1.3% |
| ensemble 1/h (exploratory) | T+30 | flipflop | 13.6% | 35.9% | 15.43 | 1.06× | 10.6% | 18.21 | – | – | 0.0% | 0.5% |
| U-Net original | T+30 | flipflop | 14.1% | 36.7% | 13.95 | 1.04× | 12.0% | 16.95 | – | – | 0.3% | 1.3% |
| U-Net wind-aware | T+30 | flipflop | 14.6% | 39.3% | 15.01 | 1.09× | 12.2% | 18.46 | – | – | 0.5% | 1.3% |
| U-Net wind-aware 1/h (exploratory) | T+30 | flipflop | 14.2% | 36.6% | 13.89 | 1.07× | 11.6% | 16.92 | – | – | 0.3% | 1.3% |
| constant | T+30 | gusty | 13.7% | 39.6% | 22.93 | 1.30× | – | – | – | – | 0.0% | 1.0% |
| ensemble | T+30 | gusty | 13.6% | 40.6% | 23.76 | 1.44× | – | – | – | – | 0.0% | 1.2% |
| ensemble 1/h (exploratory) | T+30 | gusty | 13.1% | 40.2% | 22.78 | 1.42× | – | – | – | – | 0.0% | 0.5% |
| U-Net original | T+30 | gusty | 12.5% | 35.7% | 16.49 | 1.14× | – | – | – | – | 0.0% | 2.2% |
| U-Net wind-aware | T+30 | gusty | 13.2% | 38.7% | 18.06 | 1.21× | – | – | – | – | 0.0% | 2.0% |
| U-Net wind-aware 1/h (exploratory) | T+30 | gusty | 13.1% | 39.5% | 17.29 | 1.21× | – | – | – | – | 0.0% | 2.0% |
| constant | T+60 | all | 11.9% | 39.6% | 45.13 | 1.44× | 24.9% | 33.98 | 29 | 5.4% | 6.9% | 5.0% |
| ensemble | T+60 | all | 10.8% | 38.9% | 89.73 | 2.51× | 22.6% | 57.60 | 29 | 5.1% | 5.5% | 3.3% |
| ensemble 1/h (exploratory) | T+60 | all | 10.7% | 38.0% | 138.41 | 3.41× | 19.6% | 83.01 | 31 | 5.7% | 4.9% | 2.2% |
| U-Net original | T+60 | all | 10.7% | 36.4% | 43.98 | 1.41× | 22.2% | 33.36 | 45 | 14.4% | 6.3% | 6.4% |
| U-Net wind-aware | T+60 | all | 11.1% | 37.8% | 57.76 | 1.81× | 22.4% | 35.05 | 42 | 11.5% | 7.0% | 5.4% |
| U-Net wind-aware 1/h (exploratory) | T+60 | all | 11.1% | 37.8% | 70.34 | 2.16× | 19.9% | 39.78 | 43 | 11.8% | 6.9% | 4.5% |
| constant | T+60 | steady | 7.7% | 19.1% | 17.73 | 1.02× | – | – | – | – | 0.0% | 0.0% |
| ensemble | T+60 | steady | 7.2% | 18.8% | 19.56 | 1.04× | – | – | – | – | 0.0% | 0.0% |
| ensemble 1/h (exploratory) | T+60 | steady | 8.1% | 22.1% | 30.37 | 1.23× | – | – | – | – | 1.8% | 0.0% |
| U-Net original | T+60 | steady | 6.5% | 17.3% | 19.21 | 0.98× | – | – | – | – | 0.0% | 2.5% |
| U-Net wind-aware | T+60 | steady | 7.4% | 17.6% | 19.33 | 1.01× | – | – | – | – | 0.0% | 1.6% |
| U-Net wind-aware 1/h (exploratory) | T+60 | steady | 8.7% | 19.6% | 19.57 | 0.98× | – | – | – | – | 0.0% | 0.9% |
| constant | T+60 | veer | 9.1% | 23.6% | 24.73 | 1.28× | – | – | – | – | 2.0% | 1.3% |
| ensemble | T+60 | veer | 8.4% | 23.0% | 29.96 | 1.46× | – | – | – | – | 1.3% | 0.9% |
| ensemble 1/h (exploratory) | T+60 | veer | 8.9% | 23.4% | 37.56 | 1.45× | – | – | – | – | 2.0% | 0.4% |
| U-Net original | T+60 | veer | 7.5% | 19.3% | 22.94 | 1.15× | – | – | – | – | 0.0% | 1.3% |
| U-Net wind-aware | T+60 | veer | 7.9% | 20.2% | 24.85 | 1.27× | – | – | – | – | 0.0% | 1.3% |
| U-Net wind-aware 1/h (exploratory) | T+60 | veer | 8.5% | 22.4% | 30.10 | 1.48× | – | – | – | – | 1.8% | 1.3% |
| constant | T+60 | reversal | 9.7% | 43.7% | 34.00 | 1.41× | 21.7% | 12.15 | 29 | 6.8% | 3.4% | 4.1% |
| ensemble | T+60 | reversal | 8.9% | 43.3% | 45.15 | 1.60× | 20.8% | 13.87 | 29 | 6.6% | 2.7% | 1.9% |
| ensemble 1/h (exploratory) | T+60 | reversal | 9.4% | 41.8% | 61.81 | 1.79× | 17.7% | 17.84 | 34 | 7.5% | 3.4% | 0.7% |
| U-Net original | T+60 | reversal | 7.9% | 41.6% | 36.28 | 1.51× | 17.9% | 14.54 | 32 | 13.3% | 2.7% | 5.3% |
| U-Net wind-aware | T+60 | reversal | 9.2% | 41.9% | 42.38 | 1.71× | 18.9% | 14.27 | 34 | 13.1% | 3.2% | 3.6% |
| U-Net wind-aware 1/h (exploratory) | T+60 | reversal | 9.7% | 41.3% | 56.80 | 2.22× | 17.3% | 14.40 | 39 | 14.3% | 3.4% | 1.7% |
| constant | T+60 | surge | 12.7% | 60.2% | 96.64 | 2.20× | 46.8% | 8.89 | 28 | 4.0% | 12.9% | 10.1% |
| ensemble | T+60 | surge | 12.3% | 60.0% | 282.35 | 5.91× | 48.1% | 8.96 | 28 | 3.7% | 10.6% | 9.4% |
| ensemble 1/h (exploratory) | T+60 | surge | 12.9% | 60.1% | 476.66 | 8.04× | 47.9% | 10.68 | 28 | 3.9% | 13.1% | 8.3% |
| U-Net original | T+60 | surge | 14.6% | 57.0% | 101.28 | 1.92× | 44.8% | 9.59 | 59 | 15.6% | 18.0% | 17.5% |
| U-Net wind-aware | T+60 | surge | 14.5% | 57.8% | 164.50 | 2.80× | 49.1% | 8.90 | 49 | 10.0% | 19.8% | 17.3% |
| U-Net wind-aware 1/h (exploratory) | T+60 | surge | 15.0% | 57.4% | 206.23 | 3.11× | 49.4% | 9.47 | 46 | 9.3% | 21.0% | 17.3% |
| constant | T+60 | flipflop | 18.5% | 50.2% | 40.07 | 0.92× | 20.4% | 45.87 | – | – | 16.8% | 3.5% |
| ensemble | T+60 | flipflop | 15.1% | 47.6% | 70.13 | 1.25× | 16.8% | 81.02 | – | – | 13.4% | 1.3% |
| ensemble 1/h (exploratory) | T+60 | flipflop | 12.4% | 40.2% | 101.95 | 1.86× | 13.1% | 117.88 | – | – | 3.7% | 0.3% |
| U-Net original | T+60 | flipflop | 15.9% | 46.2% | 39.09 | 1.03× | 17.9% | 44.13 | – | – | 12.6% | 3.2% |
| U-Net wind-aware | T+60 | flipflop | 15.3% | 47.4% | 41.35 | 1.16× | 16.7% | 46.93 | – | – | 12.8% | 1.3% |
| U-Net wind-aware 1/h (exploratory) | T+60 | flipflop | 12.7% | 43.3% | 47.25 | 1.59× | 13.4% | 53.88 | – | – | 7.5% | 0.8% |
| constant | T+60 | gusty | 15.1% | 41.0% | 58.39 | 1.36× | – | – | – | – | 7.6% | 11.3% |
| ensemble | T+60 | gusty | 13.5% | 40.5% | 89.55 | 1.91× | – | – | – | – | 6.4% | 5.9% |
| ensemble 1/h (exploratory) | T+60 | gusty | 12.5% | 40.2% | 117.17 | 2.48× | – | – | – | – | 5.2% | 3.2% |
| U-Net original | T+60 | gusty | 12.6% | 37.2% | 45.24 | 1.30× | – | – | – | – | 5.4% | 8.6% |
| U-Net wind-aware | T+60 | gusty | 13.0% | 42.1% | 52.56 | 1.53× | – | – | – | – | 7.4% | 6.9% |
| U-Net wind-aware 1/h (exploratory) | T+60 | gusty | 12.6% | 42.9% | 59.88 | 1.81× | – | – | – | – | 8.1% | 4.7% |

## Runtime (wall time per forecast in one worker; Monte Carlo on the CPU with the other workers busy, emulators in the main process on the GPU, so compare across machines with care)

| forecaster | forecasts | mean ms | p90 ms |
|---|---|---|---|
| constant | 2532 | 1535 | 3506 |
| ensemble | 2532 | 3451 | 8127 |
| ensemble 1/h (exploratory) | 2532 | 2579 | 6115 |
| U-Net original | 2532 | 38 | 43 |
| U-Net wind-aware | 2532 | 38 | 44 |
| U-Net wind-aware 1/h (exploratory) | 2532 | 38 | 44 |

## Selection score (equal-risk area vs constant, averaged over horizons; mean pre-shift miss)

- constant: area 1.00×, pre-shift miss 22.3%
- ensemble: area 1.02×, pre-shift miss 22.8%
- ensemble 1/h (exploratory): area 1.14×, pre-shift miss 19.1%
- U-Net original: area 0.85×, pre-shift miss 23.2%
- U-Net wind-aware: area 0.93×, pre-shift miss 23.6%
- U-Net wind-aware 1/h (exploratory): area 0.92×, pre-shift miss 21.8%

