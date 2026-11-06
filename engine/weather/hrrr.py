"""Archived NOAA HRRR forecasts at a point, for offline research only (#231).

Nothing on the drone or in the engine calls this: it builds the dataset that
tests whether a forecast loaded before flight helps predict wind shifts.

Source: the University of Utah's HRRR Zarr archive on AWS
(https://hrrrzarr.s3.amazonaws.com, public, no account). Each run's 10 m
wind (UGRD, VGRD) and surface gust (GUST) are stored as float16 tiles of
150 x 150 grid cells (3 km; float16, float32 in some later runs), compressed with blosc, one tile per variable and
run holding every forecast hour. Decoding needs the `numcodecs` package,
which is not an engine dependency: run with `uv run --with numcodecs`.

Forecast hours: slot i of a `_fcst.zarr` array is forecast hour i + 1 (the
analysis, hour 0, is a separate store). The 00/06/12/18 UTC runs go out 48 h,
the others 18 h. HRRR runs take about 50-60 min to finish, so a run started
at T can only be used from T + RUN_LATENCY (see weather.dataset).
"""

import json
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

BASE = "https://hrrrzarr.s3.amazonaws.com"
TILE = 150
VARS = {"u": "10m_above_ground/UGRD", "v": "10m_above_ground/VGRD", "gust": "surface/GUST"}
HALF = 2  # neighbourhood half-width in cells: a 5 x 5 box (~15 km) for the forecast's spatial spread


def _get(url: str, tries: int = 4) -> bytes | None:
    for k in range(tries):
        try:
            return urllib.request.urlopen(url, timeout=60).read()
        except urllib.error.HTTPError as e:
            if e.code in (403, 404):
                return None  # a missing run or variable
            time.sleep(2 ** k)
        except Exception:
            time.sleep(2 ** k)
    return None


def _codec(meta: dict):
    import numcodecs

    return numcodecs.get_codec(meta["compressor"])


def grid_index(lat: float, lon: float, grid: Path) -> tuple[int, int, float]:
    """Nearest HRRR grid cell (y, x) to a point, and its distance in km.
    `grid` is an .npz of the archive's latitude/longitude arrays (fetch_grid)."""
    g = np.load(grid)
    d = (g["lat"] - lat) ** 2 + ((g["lon"] - lon) * np.cos(np.radians(lat))) ** 2
    y, x = np.unravel_index(np.argmin(d), d.shape)
    return int(y), int(x), float(np.sqrt(d[y, x]) * 111.2)


def fetch_grid(out: Path) -> Path:
    """The archive's latitude/longitude of every grid cell, saved to `out`."""
    store = f"{BASE}/grid/HRRR_chunk_index.zarr"
    arrays = {}
    for name, key in (("lat", "latitude"), ("lon", "longitude")):
        meta = json.loads(_get(f"{store}/{key}/.zarray"))
        codec, (h, w), (ch, cw) = _codec(meta), meta["shape"], meta["chunks"]
        a = np.empty((h, w), meta["dtype"])
        for i in range(0, h, ch):
            for j in range(0, w, cw):
                b = np.frombuffer(codec.decode(_get(f"{store}/{key}/{i // ch}.{j // cw}")), meta["dtype"]).reshape(ch, cw)
                a[i : i + ch, j : j + cw] = b[: min(ch, h - i), : min(cw, w - j)]
        arrays[name] = a
    np.savez_compressed(out, **arrays)
    return out


def run_point(init: datetime, y: int, x: int) -> dict | None:
    """One run's forecast at grid cell (y, x): per forecast hour 1..N, the
    point's u, v, gust (m/s) and the standard deviation of u and v over the
    5 x 5 cells around it. None if the run is missing from the archive."""
    day, hh = init.strftime("%Y%m%d"), init.strftime("%H")
    ty, tx = y // TILE, x // TILE
    py, px = y % TILE, x % TILE
    out = {}
    for name, path in VARS.items():
        root = f"{BASE}/sfc/{day}/{day}_{hh}z_fcst.zarr/{path}/{path.split('/')[0]}/{path.split('/')[1]}"
        meta = _get(f"{root}/.zarray")
        raw = _get(f"{root}/0.{ty}.{tx}") if meta else None
        if raw is None:
            return None
        meta = json.loads(meta)
        # float16 in most of the archive, float32 in some later runs: trust each array's metadata.
        tile = np.frombuffer(_codec(meta).decode(raw), meta["dtype"]).reshape(meta["chunks"][0], TILE, TILE).astype(np.float32)
        tile[tile == meta["fill_value"]] = np.nan
        out[name] = tile[:, py, px]
        if name in ("u", "v"):
            box = tile[:, max(py - HALF, 0) : py + HALF + 1, max(px - HALF, 0) : px + HALF + 1]
            out[f"{name}_sd"] = box.reshape(len(box), -1).std(axis=1)
    out["init"] = np.array(init.timestamp(), np.float64)
    return out


def synoptic_runs(start: datetime, end: datetime) -> list[datetime]:
    """00/06/12/18 UTC runs (the 48 h ones) from start up to end."""
    t = start.replace(hour=start.hour - start.hour % 6, minute=0, second=0, microsecond=0, tzinfo=timezone.utc)
    out = []
    while t <= end:
        if t >= start:
            out.append(t)
        t += timedelta(hours=6)
    return out


def fetch_runs(inits: list[datetime], y: int, x: int, cache: Path, workers: int = 16) -> int:
    """Fetch every run's point forecast into `cache` (one small .npz per run,
    so an interrupted fetch resumes). Returns how many runs are present."""
    cache.mkdir(parents=True, exist_ok=True)

    def one(init):
        path = cache / f"{init:%Y%m%d%H}.npz"
        if path.exists():
            return True
        r = run_point(init, y, x)
        if r is None:
            path.with_suffix(".missing").touch()
            return False
        np.savez(path, **r)
        return True

    todo = [i for i in inits if not (cache / f"{i:%Y%m%d%H}.missing").exists()]
    with ThreadPoolExecutor(workers) as pool:
        return sum(pool.map(one, todo))


def load_runs(cache: Path) -> dict[float, dict]:
    """{init timestamp: run dict} from a fetch_runs cache."""
    out = {}
    for p in sorted(cache.glob("*.npz")):
        z = dict(np.load(p))
        out[float(z["init"])] = z
    return out
