"""Fetch the wind-shift study's data (#231): archived HRRR forecasts and ASOS
observations at the study stations. Offline research only; resumable.

    cd engine && uv run --with numcodecs python -m weather.fetch            # everything (~30 GB downloaded, ~2 MB kept per run)
    cd engine && uv run --with numcodecs python -m weather.fetch --years 2021 --sites BJC

Saves to weather/data/ (gitignored): the HRRR grid, one small .npz per run
and station, and one .npy of observations per station and month.
"""

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

from weather import hrrr, obs

DATA = Path(__file__).resolve().parent / "data"
# The two regions the scenarios cover. ASOS airports, not fire-line sites: the
# nearest stations with long, quality-controlled wind records.
SITES = {
    "OVE": {"name": "Oroville (Butte County, Camp Fire region)", "lat": 39.4878, "lon": -121.6222, "one_minute": True},
    "BJC": {"name": "Broomfield (Boulder County, Marshall Fire region)", "lat": 39.9088, "lon": -105.1172, "one_minute": False},
}
MONTHS = (9, 10, 11, 12)  # the fire seasons both scenarios come from
YEARS = tuple(range(2018, 2025))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--sites", default=",".join(SITES))
    p.add_argument("--years", default=",".join(map(str, YEARS)))
    p.add_argument("--workers", type=int, default=16)
    p.add_argument("--skip-hrrr", action="store_true")
    args = p.parse_args()
    years = [int(y) for y in args.years.split(",")]
    DATA.mkdir(exist_ok=True)
    grid = DATA / "hrrr_grid.npz"
    if not grid.exists() and not args.skip_hrrr:
        hrrr.fetch_grid(grid)
    for code in args.sites.split(","):
        s = SITES[code]
        months = [(y, m) for y in years for m in MONTHS]
        a = obs.fetch_station(code, months, s["one_minute"], DATA / "obs")
        print(f"{code}: {len(a):,} observations", flush=True)
        if args.skip_hrrr:
            continue
        y, x, km = hrrr.grid_index(s["lat"], s["lon"], grid)
        print(f"{code}: HRRR cell ({y}, {x}), {km:.1f} km from the station", flush=True)
        for yr in years:
            # From 12 h before the season, so every issue time has a run up to 12 h old.
            start = datetime(yr, MONTHS[0], 1, tzinfo=timezone.utc) - timedelta(hours=12)
            end = datetime(yr, MONTHS[-1], 31, 23, tzinfo=timezone.utc) if MONTHS[-1] == 12 else \
                datetime(yr, MONTHS[-1] + 1, 1, tzinfo=timezone.utc)
            runs = hrrr.synoptic_runs(start, end)
            got = hrrr.fetch_runs(runs, y, x, DATA / "hrrr" / code, args.workers)
            print(f"{code} {yr}: {got}/{len(runs)} runs", flush=True)


if __name__ == "__main__":
    main()
