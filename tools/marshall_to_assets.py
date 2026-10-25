"""Turn real Marshall Fire (Dec 30 2021) data into map-aligned assets for
checking the fire model on a second real fire (#107).

Inputs: the raw downloads, cached in tools/.cache/marshall/ (gitignored):
  feds_F2391_perimeters.geojson
      NASA FEDS 12-hourly VIIRS perimeters, fire F2391 (NASA open data), from
      https://openveda.cloud/api/features/collections/public.eis_fire_lf_perimeter_archive
      with bbox -105.30,39.90,-105.07,40.01 and Dec 29 2021 - Jan 2 2022.
  wfigs_marshall_final.geojson
      The WFIGS Interagency final perimeter for 2021-COBLX-000995 (public
      domain), from the NIFC WFIGS_Interagency_Perimeters feature service.

Outputs, in assets/scenarios/marshall/real/ (committed):
  marshall_observations.json
      Only the origin (t 0). There's no published per-house timeline like
      NIST TN 2135 for the Camp Fire, so the replay scores perimeters alone.
  marshall_perimeters.npz
      Burned-area masks on the marshall grid, bool (K, H, W), with each one's
      minutes since ignition and source.

Times are local (MST). Ignition, T0, is about 11:00, from public reports; it's
uncertain by about half an hour, which shifts the first perimeter's time by the
same. FEDS "T12" is the ~13:30 local VIIRS overpass and "T00" the ~01:30 one.
FEDS saw no new fire pixels between 01:30 and 13:30 on Dec 31, so the run was
over by 01:30, and the mapped WFIGS outline stands for that time. It replaces
the coarser FEDS outline from the same pass.

The origin is the westernmost point of the final perimeter: the fire started
in the foothills near Marshall and ran east on the downslope wind.

    engine/.venv/bin/python -I tools/marshall_to_assets.py
"""

import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from campfire_to_assets import project, rasterize, rings_of  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "tools" / ".cache" / "marshall"
SCEN = ROOT / "assets" / "scenarios" / "marshall"
OUT = SCEN / "real"
T0 = datetime(2021, 12, 30, 11, 0)  # local MST, approximate
FINAL_AT = datetime(2021, 12, 31, 1, 30)  # the FEDS pass after which nothing grew


def perimeters(bounds, w, h):
    masks, times, sources = [], [], []
    for f in json.loads((RAW / "feds_F2391_perimeters.geojson").read_text())["features"]:
        p = f["properties"]
        t = datetime.fromisoformat(p["t"])
        when = t.replace(hour=13 if t.hour == 12 else 1, minute=30)
        if when >= FINAL_AT:
            continue  # the WFIGS outline below covers these
        masks.append(rasterize(rings_of(f["geometry"], bounds, w, h), w, h))
        times.append((when - T0).total_seconds() / 60)
        sources.append(f"NASA FEDS VIIRS {when:%b %d %H:%M} ({p['farea']:.1f} km2)")
    (f,) = json.loads((RAW / "wfigs_marshall_final.geojson").read_text())["features"]
    masks.append(rasterize(rings_of(f["geometry"], bounds, w, h), w, h))
    times.append((FINAL_AT - T0).total_seconds() / 60)
    sources.append(f"WFIGS final perimeter ({f['properties']['poly_GISAcres']:.0f} ac)")
    order = np.argsort(times)
    return np.stack(masks)[order], np.asarray(times)[order], [sources[i] for i in order]


def origin(bounds, w, h) -> tuple[float, float]:
    (f,) = json.loads((RAW / "wfigs_marshall_final.geojson").read_text())["features"]
    pts = np.concatenate([np.asarray(r, float) for poly in f["geometry"]["coordinates"] for r in poly])
    lon, lat = pts[np.argmin(pts[:, 0])]
    x, y = project(lon, lat, bounds, w, h)
    # One cell in, so the ignition sits on the burned side of the outline.
    return float(x) + 1.0, float(y)


def main() -> None:
    bounds = json.loads((SCEN / "terrain.json").read_text())["bounds"]
    h, w = np.load(SCEN / "heightmap.npy").shape
    OUT.mkdir(parents=True, exist_ok=True)
    ox, oy = origin(bounds, w, h)
    (OUT / "marshall_observations.json").write_text(json.dumps({
        "source": "Origin only: the westernmost point of the WFIGS final perimeter",
        "t0_local": T0.isoformat(),
        "observations": [{"t_min": 0.0, "x": round(ox, 2), "y": round(oy, 2), "type": "V",
                          "residual": False, "source": "origin"}]}, indent=1))
    masks, times, sources = perimeters(bounds, w, h)
    np.savez_compressed(OUT / "marshall_perimeters.npz", masks=masks, t_min=times, source=np.array(sources))
    print(f"origin at ({ox:.1f}, {oy:.1f})")
    for m, t, s in zip(masks, times, sources):
        print(f"  {t / 60:5.1f} h  {m.sum():6d} cells on the map  {s}")


if __name__ == "__main__":
    sys.exit(main())
