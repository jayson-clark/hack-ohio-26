"""Turn real Camp Fire (2018) data into map-aligned assets for calibrating the
fire model (#15).

Inputs: the raw downloads, cached in tools/.cache/campfire/ (gitignored):
  nist_tn2135_appendix_f.xlsx
      NIST TN 2135 Appendix F, about 2,200 timestamped fire observations
      (data.nist.gov mds2-2954, NIST open license).
  nifc_geomac_2018_camp_early.geojson
      NIFC Historic GeoMAC 2018 perimeters for 2018-CABTU-016737 before Nov 10
      (public domain).
  feds_F17028_perimeters.geojson
      NASA FEDS 12-hourly VIIRS perimeters, fire F17028 (NASA open data). The
      ID also covers an unrelated 2019 fire in Washington, so only Nov 2018
      records are kept.

Outputs, in assets/scenarios/paradise/real/ (committed):
  campfire_observations.json
      One entry per NIST observation inside the map: map x/y, minutes since
      ignition, and type (V vegetation, S spot, R residence, O other).
  campfire_perimeters.npz
      Burned-area masks on the paradise grid, bool (K, H, W), with each one's
      minutes since ignition and source.

Times are local (PST). Ignition, T0, is NIST's first report from the origin
near Pulga at 06:25. NIFC stores local clock times as if they were UTC. FEDS
"T12" is the ~13:30 local VIIRS overpass and "T00" the ~01:30 one.

    engine/.venv/bin/python -I tools/campfire_to_assets.py
"""

import json
import re
import sys
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "tools" / ".cache" / "campfire"
OUT = ROOT / "assets" / "scenarios" / "paradise" / "real"
T0 = datetime(2018, 11, 8, 6, 25)  # local PST
NIST_DAY0 = 44508  # the Excel serial NIST's sheet uses for Nov 8
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def project(lon, lat, bounds, w, h):
    lon, lat = np.asarray(lon, float), np.asarray(lat, float)
    x = (lon - bounds["west"]) / (bounds["east"] - bounds["west"]) * w
    y = (bounds["north"] - lat) / (bounds["north"] - bounds["south"]) * h
    return x, y


def xlsx_rows(path: Path):
    """Every row of every sheet as {column letter: value}, stdlib only."""
    z = zipfile.ZipFile(path)
    shared = [
        "".join(t.text or "" for t in si.iter(f"{NS}t"))
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall(f"{NS}si")
    ]
    for name in sorted(n for n in z.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml$", n)):
        for r in ET.fromstring(z.read(name)).iter(f"{NS}row"):
            row = {}
            for c in r.findall(f"{NS}c"):
                v = c.find(f"{NS}v")
                val = None if v is None else v.text
                if c.get("t") == "s" and val is not None:
                    val = shared[int(val)]
                row[re.match(r"[A-Z]+", c.get("r")).group()] = val
            yield row


def observations(bounds, w, h) -> list[dict]:
    seen, out = set(), []
    for r in xlsx_rows(RAW / "nist_tn2135_appendix_f.xlsx"):
        sid = r.get("A")
        try:
            # The sheet's dates say Nov 2021 (Excel day 44508); only the day
            # offset from Nov 8 and the time of day are used.
            when = datetime(2018, 11, 8) + timedelta(days=float(r["B"]) - NIST_DAY0 + float(r["C"]))
            lat, lon = float(r["F"]), float(r["G"])
        except (KeyError, TypeError, ValueError):
            continue  # the header, or a row without a time or place
        key = (sid, round(lat, 5), round(lon, 5), r.get("C"))
        if key in seen:
            continue  # the sheets overlap
        seen.add(key)
        x, y = project(lon, lat, bounds, w, h)
        if not (0 <= x < w and 0 <= y < h):
            continue
        out.append({
            "t_min": round((when - T0).total_seconds() / 60, 1),
            "x": round(float(x), 2), "y": round(float(y), 2),
            "type": (r.get("K") or "").strip()[:1] or "?",
            "residual": bool(r.get("L")),
            "source": sid,
        })
    return sorted(out, key=lambda o: o["t_min"])


def rasterize(rings: list[np.ndarray], w: int, h: int) -> np.ndarray:
    """Even-odd fill of polygon rings (each (n, 2) map coords) at cell
    centres, by scanline: holes and multipolygons come out right."""
    edges = np.concatenate([np.stack([r, np.roll(r, -1, axis=0)], axis=1) for r in rings])  # (E, 2, 2)
    (x1, y1), (x2, y2) = edges[:, 0].T, edges[:, 1].T
    mask = np.zeros((h, w), bool)
    xc = np.arange(w) + 0.5
    for row in range(h):
        yc = row + 0.5
        hit = (y1 <= yc) != (y2 <= yc)
        if not hit.any():
            continue
        xs = np.sort(x1[hit] + (yc - y1[hit]) * (x2[hit] - x1[hit]) / (y2[hit] - y1[hit]))
        inside = np.searchsorted(xs, xc) % 2 == 1
        mask[row] = inside
    return mask


def rings_of(geometry, bounds, w, h) -> list[np.ndarray]:
    polys = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
    out = []
    for poly in polys:
        for ring in poly:
            a = np.asarray(ring, float)
            x, y = project(a[:, 0], a[:, 1], bounds, w, h)
            out.append(np.stack([x, y], axis=1))
    return out


def perimeters(bounds, w, h):
    masks, times, sources = [], [], []
    for f in json.loads((RAW / "nifc_geomac_2018_camp_early.geojson").read_text())["features"]:
        p = f["properties"]
        # Local clock time stored as if UTC.
        when = datetime.fromtimestamp(p["perimeterdatetime"] / 1000, tz=timezone.utc).replace(tzinfo=None)
        masks.append(rasterize(rings_of(f["geometry"], bounds, w, h), w, h))
        times.append((when - T0).total_seconds() / 60)
        sources.append(f"NIFC {p['mapmethod']} {when:%b %d %H:%M} ({p['gisacres']:.0f} ac)")
    for f in json.loads((RAW / "feds_F17028_perimeters.geojson").read_text())["features"]:
        p = f["properties"]
        t = datetime.fromisoformat(p["t"])
        if t.year != 2018 or t > datetime(2018, 11, 10, 12):
            continue  # another fire under the same ID, or past the first two days
        when = t.replace(hour=13 if t.hour == 12 else 1, minute=30)
        masks.append(rasterize(rings_of(f["geometry"], bounds, w, h), w, h))
        times.append((when - T0).total_seconds() / 60)
        sources.append(f"NASA FEDS VIIRS {when:%b %d %H:%M} ({p['farea']:.0f} km2)")
    order = np.argsort(times)
    return np.stack(masks)[order], np.asarray(times)[order], [sources[i] for i in order]


def main() -> None:
    terrain = json.loads((ROOT / "assets" / "scenarios" / "paradise" / "terrain.json").read_text())
    bounds = terrain["bounds"]
    h, w = np.load(ROOT / "assets" / "scenarios" / "paradise" / "heightmap.npy").shape
    OUT.mkdir(parents=True, exist_ok=True)
    obs = observations(bounds, w, h)
    (OUT / "campfire_observations.json").write_text(json.dumps({
        "source": "NIST TN 2135 Appendix F (data.nist.gov mds2-2954), NIST open license",
        "t0_local": T0.isoformat(), "observations": obs}, indent=1))
    masks, times, sources = perimeters(bounds, w, h)
    np.savez_compressed(OUT / "campfire_perimeters.npz", masks=masks, t_min=times, source=np.array(sources))
    print(f"{len(obs)} observations in the map, {obs[0]['t_min']}-{obs[-1]['t_min']} min after T0")
    for m, t, s in zip(masks, times, sources):
        print(f"  {t / 60:5.1f} h  {m.sum():6d} cells on the map  {s}")


if __name__ == "__main__":
    sys.exit(main())
