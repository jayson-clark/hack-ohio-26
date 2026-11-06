"""Station wind observations, for offline research only (#231).

They stand in for what a drone's own anemometer would measure, and they are
the ground truth the shift models are scored against. Source: the Iowa
Environmental Mesonet's ASOS archive (https://mesonet.agron.iastate.edu),
public, no key:

- 1-minute ASOS data (two-minute average wind each minute) where the station
  has it, e.g. Oroville (OVE);
- otherwise routine and special reports (every 20 min at Broomfield, BJC).

Directions are converted to vector components at once: u east, v north,
the direction the wind blows towards, in m/s. Calm (0 kt) is u = v = 0.
"""

import csv
import io
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

KT = 0.514444  # m/s per knot
IEM = "https://mesonet.agron.iastate.edu/cgi-bin/request"


def to_uv(speed_ms, from_deg):
    """Meteorological (speed, direction it blows FROM) -> (u east, v north)."""
    r = np.radians(np.asarray(from_deg, np.float64))
    s = np.asarray(speed_ms, np.float64)
    return -s * np.sin(r), -s * np.cos(r)


def from_uv(u, v):
    """(u, v) -> (speed, direction it blows FROM, degrees in [0, 360))."""
    u, v = np.asarray(u, np.float64), np.asarray(v, np.float64)
    return np.hypot(u, v), np.degrees(np.arctan2(-u, -v)) % 360.0


def _fetch(url: str) -> str:
    for k in range(5):
        try:
            return urllib.request.urlopen(url, timeout=180).read().decode()
        except Exception:
            time.sleep(5 * 2 ** k)
    raise RuntimeError(f"could not fetch {url}")


def fetch_month(station: str, year: int, month: int, one_minute: bool) -> np.ndarray:
    """One month of observations: float64 (n, 3) of (unix time, u, v), sorted."""
    t0 = datetime(year, month, 1, tzinfo=timezone.utc)
    t1 = (t0 + timedelta(days=32)).replace(day=1)
    if one_minute:
        url = (f"{IEM}/asos1min.py?station={station}&vars=sknt&vars=drct&sts={t0:%Y-%m-%dT%H:%MZ}"
               f"&ets={t1:%Y-%m-%dT%H:%MZ}&sample=1min&what=download&delim=comma&tz=UTC")
        tcol, scol, dcol = "valid(UTC)", "sknt", "drct"
    else:
        url = (f"{IEM}/asos.py?station={station}&data=drct&data=sknt&year1={t0.year}&month1={t0.month}&day1=1"
               f"&year2={t1.year}&month2={t1.month}&day2=1&tz=Etc/UTC&format=onlycomma&latlon=no&missing=M"
               f"&report_type=3&report_type=4")
        tcol, scol, dcol = "valid", "sknt", "drct"
    rows = []
    for r in csv.DictReader(io.StringIO(_fetch(url))):
        s, d = r.get(scol, "M"), r.get(dcol, "M")
        if s in ("M", "", None) or d in ("M", "", None):
            continue
        t = datetime.strptime(r[tcol], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc).timestamp()
        u, v = to_uv(float(s) * KT, float(d))
        rows.append((t, float(u), float(v)))
    a = np.array(rows, np.float64).reshape(-1, 3)
    return a[np.argsort(a[:, 0], kind="stable")]


def fetch_station(station: str, months: list[tuple[int, int]], one_minute: bool, cache: Path) -> np.ndarray:
    """Every month's observations, cached per month (resumable)."""
    cache.mkdir(parents=True, exist_ok=True)
    parts = []
    for y, m in months:
        p = cache / f"{station}-{y}-{m:02d}.npy"
        if not p.exists():
            np.save(p, fetch_month(station, y, m, one_minute))
        parts.append(np.load(p))
    a = np.concatenate(parts) if parts else np.zeros((0, 3))
    _, keep = np.unique(a[:, 0], return_index=True)
    return a[keep]
