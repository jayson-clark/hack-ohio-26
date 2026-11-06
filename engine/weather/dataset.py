"""Forecast-time features and later wind behaviour, for the wind-shift study (#231).

One row per issue time t (every ISSUE_EVERY_MIN minutes). Every feature is
built from information available at t:

- on-board: the station's observations up to t (standing in for a drone's
  own anemometer);
- preloaded forecast: the newest 00/06/12/18 UTC HRRR run that was out by t
  (started at least RUN_LATENCY_H before t), read at the forecast hours that
  cover t and t + h. A forecast *about* t + h is allowed; anything observed
  after t is not.

Targets come from observations after t. Definitions, fixed before any model
was fit:
- wind at a moment tau: the vector mean of observations in (tau - window, tau]
  (10 min for 1-minute data, 20 min for 20-minute reports);
- shift_h: the direction at t + h differs from that at t by more than
  SHIFT_DEG, with both speeds >= MIN_SPEED (calm isn't a direction);
- reversal_h: the same with more than REVERSAL_DEG;
- surge_h: the speed rises by at least SURGE_MS, to at least SURGE_MIN.
"""

from dataclasses import dataclass

import numpy as np

from weather.obs import from_uv

HORIZONS_MIN = (30, 60)
ISSUE_EVERY_MIN = 30
RUN_LATENCY_H = 1.0  # an HRRR run is usable this long after it starts
MAX_RUN_AGE_H = 13.0  # older preloads are treated as missing
MIN_SPEED = 2.5  # m/s
SHIFT_DEG = 45.0
REVERSAL_DEG = 135.0
SURGE_MS = 4.0
SURGE_MIN = 6.0

ONBOARD = ["u", "v", "speed", "dchange30", "dchange60", "angle60", "steady60", "gusty30", "hour_sin", "hour_cos"]
FORECAST = ["f_dchange", "f_angle", "f_dspeed", "f_gust", "f_spread", "f_err_now", "f_age"]


@dataclass
class Series:
    """Observations at one station: unix time, u, v (sorted)."""

    t: np.ndarray
    u: np.ndarray
    v: np.ndarray
    window_s: float


def wind_at(s: Series, tau: np.ndarray, window_s: float | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Vector-mean (u, v) over (tau - window, tau], and the observation count.
    Uses nothing after tau."""
    w = s.window_s if window_s is None else window_s
    cu = np.concatenate([[0.0], np.cumsum(s.u)])
    cv = np.concatenate([[0.0], np.cumsum(s.v)])
    hi = np.searchsorted(s.t, tau, side="right")  # obs with t <= tau
    lo = np.searchsorted(s.t, tau - w, side="right")  # obs with t <= tau - w are excluded
    n = hi - lo
    with np.errstate(invalid="ignore", divide="ignore"):
        u = (cu[hi] - cu[lo]) / n
        v = (cv[hi] - cv[lo]) / n
    return np.where(n > 0, u, np.nan), np.where(n > 0, v, np.nan), n


def _scalar_mean_speed(s: Series, tau: np.ndarray, w: float) -> tuple[np.ndarray, np.ndarray]:
    sp = np.hypot(s.u, s.v)
    c = np.concatenate([[0.0], np.cumsum(sp)])
    hi = np.searchsorted(s.t, tau, side="right")
    lo = np.searchsorted(s.t, tau - w, side="right")
    n = hi - lo
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = (c[hi] - c[lo]) / n
    # Max over the window: a loop over issue times only (not grid cells), cheap.
    mx = np.array([sp[a:b].max() if b > a else np.nan for a, b in zip(lo, hi)])
    return np.where(n > 0, mean, np.nan), mx


def angle_between(u1, v1, u2, v2) -> np.ndarray:
    """Unsigned angle between two wind vectors, degrees in [0, 180]."""
    dot = u1 * u2 + v1 * v2
    cross = u1 * v2 - v1 * u2
    return np.abs(np.degrees(np.arctan2(cross, dot)))


def shift_targets(u0, v0, u1, v1) -> dict[str, np.ndarray]:
    s0, s1 = np.hypot(u0, v0), np.hypot(u1, v1)
    both = (s0 >= MIN_SPEED) & (s1 >= MIN_SPEED)
    ang = angle_between(u0, v0, u1, v1)
    return {
        "shift": both & (ang > SHIFT_DEG),
        "reversal": both & (ang > REVERSAL_DEG),
        "surge": (s1 - s0 >= SURGE_MS) & (s1 >= SURGE_MIN),
    }


def onboard_features(s: Series, t: np.ndarray, lon: float) -> dict[str, np.ndarray]:
    """What a drone measuring the wind itself would know at t."""
    u, v, n = wind_at(s, t)
    u30, v30, _ = wind_at(s, t - 1800)
    u60, v60, _ = wind_at(s, t - 3600)
    mean60, _ = _scalar_mean_speed(s, t, 3600)
    vu60, vv60, _ = wind_at(s, t, 3600)
    mean30, max30 = _scalar_mean_speed(s, t, 1800)
    speed = np.hypot(u, v)
    s60 = np.hypot(u60, v60)
    ok = (speed >= MIN_SPEED) & (s60 >= MIN_SPEED)
    solar_h = ((t / 3600.0) + lon / 15.0) % 24.0  # local solar time
    with np.errstate(invalid="ignore", divide="ignore"):
        return {
            "u": u, "v": v, "speed": speed,
            "dchange30": np.hypot(u - u30, v - v30),  # how much the wind vector moved in 30 min
            "dchange60": np.hypot(u - u60, v - v60),
            "angle60": np.where(ok, angle_between(u60, v60, u, v), 0.0),
            "steady60": np.where(mean60 > 0, np.hypot(vu60, vv60) / mean60, 1.0),  # 1 = steady direction
            "gusty30": np.where(mean30 > 0.5, max30 / np.maximum(mean30, 0.5), 1.0),
            "hour_sin": np.sin(2 * np.pi * solar_h / 24.0),
            "hour_cos": np.cos(2 * np.pi * solar_h / 24.0),
            "_n": n.astype(float),
        }


def preloaded_run(inits: np.ndarray, t: float, latency_h: float = RUN_LATENCY_H) -> int | None:
    """Index of the newest run started at least latency_h before t (inits sorted), or None."""
    i = int(np.searchsorted(inits, t - latency_h * 3600, side="right")) - 1
    return i if i >= 0 else None


def forecast_at(run: dict, tau: float, key: str) -> float:
    """A run's forecast of `key` at time tau, linear between forecast hours.
    Slot k is forecast hour k + 1, so tau must be at least 1 h after the run."""
    lead = (tau - float(run["init"])) / 3600.0
    a = run[key]
    if lead < 1.0 or lead > len(a):
        return np.nan
    k = lead - 1.0
    i = int(np.floor(k))
    j = min(i + 1, len(a) - 1)
    f = k - i
    return float((1 - f) * a[i] + f * a[j])


def forecast_features(runs: dict[float, dict], t: np.ndarray, h_min: int, u_now: np.ndarray, v_now: np.ndarray,
                      latency_h: float = RUN_LATENCY_H, max_age_h: float = MAX_RUN_AGE_H) -> dict[str, np.ndarray]:
    """Preloaded-forecast features for horizon h. NaN where no usable run."""
    inits = np.array(sorted(runs))
    keys = FORECAST
    out = {k: np.full(len(t), np.nan) for k in keys}
    out["f_u_h"] = np.full(len(t), np.nan)
    out["f_v_h"] = np.full(len(t), np.nan)
    out["f_init"] = np.full(len(t), np.nan)
    for n, ti in enumerate(t):
        i = preloaded_run(inits, ti, latency_h)
        if i is None:
            continue
        run = runs[inits[i]]
        age = (ti - inits[i]) / 3600.0
        if age > max_age_h:
            continue
        th = ti + h_min * 60
        fu0, fv0 = forecast_at(run, ti, "u"), forecast_at(run, ti, "v")
        fu1, fv1 = forecast_at(run, th, "u"), forecast_at(run, th, "v")
        if not np.isfinite([fu0, fv0, fu1, fv1]).all():
            continue
        s0, s1 = np.hypot(fu0, fv0), np.hypot(fu1, fv1)
        g = [forecast_at(run, ti + k * 900, "gust") for k in range(h_min // 15 + 1)]
        sd = [forecast_at(run, th, "u_sd"), forecast_at(run, th, "v_sd")]
        out["f_dchange"][n] = np.hypot(fu1 - fu0, fv1 - fv0)
        out["f_angle"][n] = angle_between(fu0, fv0, fu1, fv1) if min(s0, s1) >= MIN_SPEED else 0.0
        out["f_dspeed"][n] = s1 - s0
        out["f_gust"][n] = np.nanmax(g)
        out["f_spread"][n] = float(np.hypot(*sd))
        out["f_err_now"][n] = np.hypot(u_now[n] - fu0, v_now[n] - fv0) if np.isfinite(u_now[n]) else np.nan
        out["f_age"][n] = age
        out["f_u_h"][n], out["f_v_h"][n] = fu1, fv1
        out["f_init"][n] = inits[i]
    return out


def build(s: Series, runs: dict[float, dict], start: float, end: float, lon: float,
          months: tuple[int, ...] | None = None, latency_h: float = RUN_LATENCY_H,
          max_age_h: float = MAX_RUN_AGE_H) -> dict[str, np.ndarray]:
    """All rows for one station between start and end (unix seconds).
    latency_h / max_age_h set how old the preloaded forecast is (a longer
    latency = a forecast loaded longer before t)."""
    from datetime import datetime, timezone

    t = np.arange(np.ceil(start / 1800) * 1800, end, ISSUE_EVERY_MIN * 60, dtype=np.float64)
    if months:
        m = np.array([datetime.fromtimestamp(x, timezone.utc).month for x in t])
        t = t[np.isin(m, months)]
    on = onboard_features(s, t, lon)
    rows = {"t": t, **{k: on[k] for k in ONBOARD}}
    for h in HORIZONS_MIN:
        uh, vh, nh = wind_at(s, t + h * 60)
        for k, val in shift_targets(on["u"], on["v"], uh, vh).items():
            rows[f"{k}_{h}"] = val.astype(float)
        rows[f"obs_u_{h}"], rows[f"obs_v_{h}"] = uh, vh
        rows[f"valid_{h}"] = ((on["_n"] > 0) & (nh > 0)).astype(float)
        for k, val in forecast_features(runs, t, h, on["u"], on["v"], latency_h, max_age_h).items():
            rows[f"{k}_{h}"] = val
    return rows
