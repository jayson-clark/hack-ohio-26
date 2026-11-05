# Burn envelope: fixed-rate ACI vs DtACI-inspired (#227)

8 episodes per schedule, seeds 0-7, 300 min of forecasts every 5 min, 32 rollouts, margin cap 10 cells, target miss 10%.

## T+30

| schedule | controller | miss | worst 30 min | windows > 15% | area km² | vs oracle | at widest | infeasible | recovery (shown) | recovery (scored) | post-shift miss | post-shift vs oracle |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| steady | static | 10.9% | 28.2% | 19.2% | 7.68 | 1.02× | 0.0% | 0.0% | – | – | – | – |
| steady | aci | 9.3% | 23.4% | 11.8% | 7.80 | 1.03× | 0.0% | 0.0% | – | – | – | – |
| steady | dtaci | 9.4% | 22.7% | 12.7% | 7.57 | 1.00× | 0.0% | 0.0% | – | – | – | – |
| reversal | static | 12.0% | 37.5% | 33.5% | 9.47 | 0.96× | 0.0% | 0.0% | 26 | 56 | 16.6% | 0.93× |
| reversal | aci | 9.8% | 32.5% | 29.2% | 10.00 | 1.02× | 0.0% | 0.0% | 24 | 51 | 5.9% | 1.04× |
| reversal | dtaci | 10.6% | 34.4% | 29.4% | 9.51 | 0.97× | 0.0% | 0.0% | 24 | 51 | 12.3% | 0.96× |
| surge | static | 13.3% | 40.9% | 44.0% | 22.32 | 0.96× | 0.0% | 2.6% | 46 | 76 | 11.8% | 0.97× |
| surge | aci | 10.4% | 40.1% | 39.3% | 33.51 | 1.44× | 0.0% | 2.6% | 28 | 58 | 5.4% | 1.64× |
| surge | dtaci | 11.1% | 40.7% | 39.5% | 29.00 | 1.25× | 0.0% | 2.6% | 28 | 58 | 6.5% | 1.38× |
| flipflop | static | 29.0% | 49.3% | 84.7% | 4.80 | 0.30× | 0.0% | 1.7% | – | – | – | – |
| flipflop | aci | 14.8% | 46.4% | 43.0% | 17.58 | 1.10× | 1.4% | 1.7% | – | – | – | – |
| flipflop | dtaci | 18.9% | 46.3% | 61.4% | 12.05 | 0.76× | 0.0% | 1.7% | – | – | – | – |
| gusty | static | 24.6% | 44.9% | 86.3% | 8.77 | 0.46× | 0.0% | 0.7% | – | – | – | – |
| gusty | aci | 13.7% | 39.7% | 40.5% | 23.34 | 1.22× | 0.2% | 0.7% | – | – | – | – |
| gusty | dtaci | 16.1% | 39.8% | 48.9% | 18.08 | 0.95× | 0.0% | 0.7% | – | – | – | – |

## T+60

| schedule | controller | miss | worst 30 min | windows > 15% | area km² | vs oracle | at widest | infeasible | recovery (shown) | recovery (scored) | post-shift miss | post-shift vs oracle |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| steady | static | 7.6% | 19.3% | 13.2% | 17.40 | 1.11× | 0.0% | 0.0% | – | – | – | – |
| steady | aci | 8.2% | 24.0% | 16.3% | 18.18 | 1.16× | 0.8% | 0.0% | – | – | – | – |
| steady | dtaci | 8.2% | 23.3% | 14.3% | 17.04 | 1.09× | 0.0% | 0.0% | – | – | – | – |
| reversal | static | 11.6% | 51.9% | 32.5% | 22.04 | 0.93× | 0.0% | 3.1% | 38 | 98 | 12.4% | 0.99× |
| reversal | aci | 10.5% | 51.6% | 29.2% | 30.15 | 1.27× | 1.2% | 3.1% | 24 | 80 | 5.8% | 1.72× |
| reversal | dtaci | 10.8% | 51.9% | 29.5% | 25.80 | 1.08× | 0.0% | 3.1% | 24 | 80 | 4.9% | 1.41× |
| surge | static | 12.7% | 53.7% | 33.5% | 49.56 | 1.11× | 0.0% | 11.5% | 28 | 88 | 5.9% | 1.22× |
| surge | aci | 11.8% | 54.9% | 34.6% | 98.46 | 2.21× | 10.2% | 11.5% | 29 | 89 | 4.5% | 2.40× |
| surge | dtaci | 12.4% | 55.2% | 34.4% | 68.27 | 1.54× | 0.0% | 11.5% | 28 | 88 | 4.6% | 1.83× |
| flipflop | static | 38.7% | 68.0% | 86.2% | 13.09 | 0.30× | 0.0% | 3.5% | – | – | – | – |
| flipflop | aci | 20.2% | 64.4% | 51.2% | 41.12 | 0.93× | 18.6% | 3.5% | – | – | – | – |
| flipflop | dtaci | 24.0% | 65.3% | 61.5% | 31.89 | 0.72× | 0.0% | 3.5% | – | – | – | – |
| gusty | static | 25.8% | 49.0% | 80.2% | 23.11 | 0.50× | 0.0% | 9.5% | – | – | – | – |
| gusty | aci | 15.5% | 40.6% | 46.2% | 59.64 | 1.29× | 8.6% | 9.5% | – | – | – | – |
| gusty | dtaci | 18.1% | 42.5% | 53.5% | 45.78 | 0.99× | 0.0% | 9.5% | – | – | – | – |

## Where the misses come from (single-shift schedules, no controller)

| horizon | schedule | forecasts | window | miss at warm start | widest miss cap 10 | cap 20 | cap 40 | infeasible cap 10 | cap 20 | cap 40 |
|---|---|---|---|---|---|---|---|---|---|---|
| T+30 | reversal | 40 | stale | 25.8% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% |
| T+30 | reversal | 79 | fresh | 13.6% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% |
| T+30 | reversal | 421 | all | 12.0% | 0.1% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% |
| T+30 | surge | 30 | stale | 40.2% | 4.6% | 1.5% | 0.0% | 13.3% | 0.0% | 0.0% |
| T+30 | surge | 72 | fresh | 17.0% | 1.6% | 0.6% | 0.0% | 8.3% | 1.4% | 0.0% |
| T+30 | surge | 382 | all | 13.3% | 0.7% | 0.2% | 0.0% | 2.6% | 0.3% | 0.0% |
| T+60 | reversal | 88 | stale | 26.7% | 2.1% | 0.1% | 0.0% | 9.1% | 0.0% | 0.0% |
| T+60 | reversal | 79 | fresh | 10.8% | 1.7% | 0.1% | 0.0% | 6.3% | 0.0% | 0.0% |
| T+60 | reversal | 421 | all | 11.6% | 0.8% | 0.0% | 0.0% | 3.1% | 0.0% | 0.0% |
| T+60 | surge | 66 | stale | 45.1% | 15.9% | 7.8% | 1.2% | 57.6% | 28.8% | 0.0% |
| T+60 | surge | 72 | fresh | 9.4% | 3.6% | 2.4% | 0.9% | 8.3% | 8.3% | 5.6% |
| T+60 | surge | 382 | all | 12.7% | 3.4% | 1.8% | 0.4% | 11.5% | 6.5% | 1.0% |

## Sensitivity (all schedules pooled: miss, worst 30 min, vs oracle)

| horizon | variant | miss | worst 30 min | vs oracle | at widest |
|---|---|---|---|---|---|
| T+30 | static | 17.8% | 40.2% | 0.70× | 0.0% |
| T+30 | aci lr 0.05 | 13.3% | 37.7% | 1.00× | 0.0% |
| T+30 | aci lr 0.1 (baseline) | 11.6% | 36.4% | 1.21× | 0.3% |
| T+30 | aci lr 0.2 | 10.9% | 35.0% | 1.55× | 4.3% |
| T+30 | dtaci I 10 | 13.1% | 36.8% | 1.00× | 0.0% |
| T+30 | dtaci I 20 (default) | 13.1% | 36.8% | 1.00× | 0.0% |
| T+30 | dtaci I 50 | 13.1% | 36.8% | 1.00× | 0.0% |
| T+30 | dtaci paper settings (I 500) | 13.0% | 36.7% | 1.01× | 0.0% |
| T+30 | aci lr 0.1, cap 20 | 11.6% | 36.4% | 1.20× | 0.0% |
| T+30 | dtaci I 20, cap 20 | 12.3% | 36.7% | 1.12× | 0.0% |
| T+60 | static | 19.1% | 48.4% | 0.71× | 0.0% |
| T+60 | aci lr 0.05 | 14.0% | 47.1% | 1.21× | 3.9% |
| T+60 | aci lr 0.1 (baseline) | 13.1% | 47.1% | 1.40× | 7.6% |
| T+60 | aci lr 0.2 | 14.1% | 48.6% | 1.34× | 11.8% |
| T+60 | dtaci I 10 | 14.6% | 47.6% | 1.07× | 0.0% |
| T+60 | dtaci I 20 (default) | 14.6% | 47.6% | 1.07× | 0.0% |
| T+60 | dtaci I 50 | 14.5% | 47.6% | 1.08× | 0.0% |
| T+60 | dtaci paper settings (I 500) | 14.6% | 47.7% | 1.05× | 0.0% |
| T+60 | aci lr 0.1, cap 20 | 12.5% | 47.1% | 1.65× | 2.2% |
| T+60 | dtaci I 20, cap 20 | 13.2% | 47.2% | 1.23× | 0.0% |

## DtACI weight step (selection seeds 0-3: miss, vs oracle)

eta x1 is the worst-case Hedge step. Per-forecast loss gaps between experts are ~100x smaller than that worst case, so larger multiples were tried.

| variant | T+30 miss | T+30 vs oracle | T+60 miss | T+60 vs oracle |
|---|---|---|---|---|
| aci lr 0.1 (baseline) | 11.7% | 1.18× | 13.3% | 1.38× |
| dtaci eta x1 | 13.3% | 0.97× | 14.7% | 1.06× |
| dtaci eta x3 | 13.1% | 1.00× | 14.8% | 1.02× |
| dtaci eta x10 | 12.7% | 1.02× | 15.6% | 0.95× |
| dtaci eta x30 | 12.2% | 1.05× | 16.6% | 0.90× |
| dtaci eta x100 | 12.1% | 1.06× | 16.6% | 0.95× |
| dtaci eta x300 | 12.5% | 1.05× | 16.6% | 1.01× |
