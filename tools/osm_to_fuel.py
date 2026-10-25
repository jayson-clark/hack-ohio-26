# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "numpy>=2.0",
#     "pillow>=10.0",
# ]
# ///
"""OpenStreetMap land cover -> the sim's fuel layer: fuel.png.

The fire model (engine/sim/fire.py, load_fuel) reads it as a fuel multiplier
per cell: grayscale, black is unburnable and white is 1.5x fuel. Without it
the fire treats forest, grassland, town and river the same. It's scenario
data like roads.json: commit it, and regenerate rather than edit by hand.

    uv run tools/osm_to_fuel.py paradise
    uv run tools/osm_to_fuel.py paradise --preview /tmp/fuel.png   # colour preview by class
    uv run tools/osm_to_fuel.py paradise --refresh                 # re-download instead of the cache

Land cover comes from the Overpass API (no key) for the bounds in
terrain.json, cached in tools/.cache/overpass/, and is projected with the same
equirectangular mapping as tools/osm_to_layers.py, so fuel lines up with the
roads and the print. Areas are filled at SUPERSAMPLE x the grid resolution and
averaged down, so a cell that's half river gets half fuel.

Simplifications, fine at 94 m cells: multipolygon holes are ignored (a
clearing inside a forest stays forest), and land OSM doesn't map stays at the
background fuel, which suits the Sierra foothills' forest and brush.
"""

import argparse
import hashlib
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
from osm_to_layers import CACHE, OVERPASS, REPO, USER_AGENT, Projector  # noqa: E402

SUPERSAMPLE = 4
# Rivers are lines in OSM. The Feather River forks are roughly 40 m across.
RIVER_WIDTH_M = 40.0

# Fuel classes, painted in this order (a later class wins where areas
# overlap), with the fuel multiplier each one gets. Unmapped land is
# "background". The weights are relative to forest = 1.0, which is what the
# whole map used to be, so the fire's tuning (sim/fire.py) still holds:
# chaparral and dry grass carry fire fastest, irrigated farmland and town
# cores slowest, water and rock not at all.
CLASSES = [
    ("background", 1.0, None),
    ("farmland", 0.6, {"landuse": ["farmland", "orchard", "vineyard"]}),
    ("parkland", 0.7, {"landuse": ["cemetery", "recreation_ground"]}),
    ("grass", 1.2, {"natural": ["grassland"], "landuse": ["meadow", "grass"]}),
    ("scrub", 1.3, {"natural": ["scrub", "heath"]}),
    ("forest", 1.0, {"natural": ["wood"], "landuse": ["forest"]}),
    ("residential", 0.9, {"landuse": ["residential"]}),
    ("commercial", 0.6, {"landuse": ["commercial", "retail", "industrial"]}),
    ("wetland", 0.5, {"natural": ["wetland"]}),
    ("rock", 0.0, {"natural": ["bare_rock", "scree"], "landuse": ["quarry"]}),
    ("water", 0.0, {"natural": ["water"], "landuse": ["reservoir", "basin"], "waterway": ["riverbank"]}),
    ("river", 0.0, {"waterway": ["river"]}),  # lines, drawn RIVER_WIDTH_M wide
]
# Per-scenario weights that replace CLASSES' own, where the same OSM class
# burns differently. Paradise's residential areas are pine-needle forest lots
# that the Camp Fire burned through (its replay needs residential at 0.6 or
# more). Superior and Louisville are irrigated lawns, streets and parking that
# stopped the Marshall Fire: at 0.9 the replay burned 2.7x the real area, at
# these weights 1.5x, with outline IoU from 0.19 to 0.27 (#144). The valley
# floor around Chico and Oroville is irrigated orchard and rice, harvested and
# wet by November, which the Camp Fire never crossed: at farmland 0.6 the
# replay on the extended map ran 37 km west across it and burned 4.2x the real
# area; at 0.05 it's 2.4x (IoU 0.21 -> 0.35 at 7.1 h). What's left is the dry
# foothill grass above the valley (#197).
SCENARIO_WEIGHTS = {
    "paradise": {"farmland": 0.05},
    "marshall": {"residential": 0.25, "commercial": 0.3},
}
# Unmapped land below this elevation (m) is farmland, not background. OSM
# maps few of the Sacramento Valley's orchards and rice fields around Chico
# and Oroville, and without this the valley floor would burn like foothill
# brush. The print's terrain is all above it, so the Camp Fire replay's fuel
# doesn't change.
LOWLAND_FARMLAND_M = {"paradise": 100.0}
# The PNG stores fuel / MAX_FUEL (sim/fire.py's white = 1.5x).
MAX_FUEL = 1.5

PREVIEW_COLOURS = {
    "background": (120, 140, 90), "farmland": (220, 210, 140), "parkland": (170, 200, 140),
    "grass": (200, 220, 110), "scrub": (150, 120, 60), "forest": (40, 100, 50),
    "residential": (210, 120, 120), "commercial": (170, 90, 160), "wetland": (90, 170, 170),
    "rock": (150, 150, 150), "water": (40, 90, 200), "river": (40, 90, 200),
}


def query(bounds: dict) -> str:
    bbox = f"{bounds['south']},{bounds['west']},{bounds['north']},{bounds['east']}"
    keys: dict[str, set[str]] = {}
    for _, _, tags in CLASSES:
        for k, vs in (tags or {}).items():
            keys.setdefault(k, set()).update(vs)
    parts = []
    for k, vs in sorted(keys.items()):
        sel = f'["{k}"~"^({"|".join(sorted(vs))})$"]'
        parts += [f"way{sel}({bbox});", f"relation{sel}({bbox});"]
    return f"[out:json][timeout:180];({''.join(parts)});out geom;"


def fetch(q: str, refresh: bool) -> list[dict]:
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{hashlib.sha1(q.encode()).hexdigest()[:16]}.json"
    if path.exists() and not refresh:
        print(f"Using cached {path.relative_to(REPO)}")
        return json.loads(path.read_text())["elements"]
    body = urllib.parse.urlencode({"data": q}).encode()
    last = None
    # Same mirrors and backoff as osm_to_layers.py: the public servers 502/504 under load.
    for attempt, url in enumerate(OVERPASS * 3):
        if attempt >= len(OVERPASS):
            time.sleep(10 * (attempt // len(OVERPASS)))
        try:
            print(f"Fetching land cover from {url}")
            req = urllib.request.Request(url, data=body, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=240) as r:
                raw = r.read()
            path.write_bytes(raw)
            return json.loads(raw)["elements"]
        except Exception as e:  # try the next mirror
            last = e
            print(f"  failed: {e}", file=sys.stderr)
    sys.exit(f"Overpass unreachable ({last}).")


def classify(tags: dict) -> int | None:
    """Index into CLASSES for an element's tags; the last match wins, like painting."""
    found = None
    for i, (_, _, want) in enumerate(CLASSES):
        if want and any(tags.get(k) in vs for k, vs in want.items()):
            found = i
    return found


def join_rings(lines: list[list[tuple[float, float]]]) -> list[list[tuple[float, float]]]:
    """Stitch a multipolygon's outer ways end to end into closed rings. OSM
    splits big outlines (a forest, a lake shore) across many ways."""
    rings, open_ = [], [list(l) for l in lines if len(l) >= 2]
    while open_:
        ring = open_.pop()
        while ring[0] != ring[-1]:
            for i, l in enumerate(open_):
                if l[0] == ring[-1]:
                    ring += l[1:]
                elif l[-1] == ring[-1]:
                    ring += l[-2::-1]
                elif l[-1] == ring[0]:
                    ring = l[:-1] + ring
                elif l[0] == ring[0]:
                    ring = l[:0:-1] + ring
                else:
                    continue
                open_.pop(i)
                break
            else:
                break  # can't close it (clipped at the query bbox): fill what's there
        if len(ring) >= 3:
            rings.append(ring)
    return rings


def shapes(el: dict) -> tuple[list[list], list[list]]:
    """(polygons, lines) for one element, as lat/lon point lists."""
    def pts(geom):
        return [(g["lat"], g["lon"]) for g in geom]

    if el["type"] == "way":
        p = pts(el.get("geometry", []))
        closed = len(p) >= 4 and p[0] == p[-1]
        return ([p], []) if closed else ([], [p])
    outers = [pts(m["geometry"]) for m in el.get("members", []) if m.get("role") == "outer" and "geometry" in m]
    return join_rings(outers), []


def rasterize(elements: list[dict], proj: Projector, ss: int) -> np.ndarray:
    """Class index per supersampled pixel, uint8 (H*ss, W*ss)."""
    img = Image.new("L", (proj.w * ss, proj.h * ss), 0)
    draw = ImageDraw.Draw(img)
    by_class: dict[int, list[dict]] = {}
    for el in elements:
        c = classify(el.get("tags", {}))
        if c is not None:
            by_class.setdefault(c, []).append(el)
    river_px = max(1, round(RIVER_WIDTH_M / proj.cell_m * ss))
    for c in sorted(by_class):
        for el in by_class[c]:
            polys, lines = shapes(el)
            for p in polys:
                draw.polygon([tuple(v * ss for v in proj(lat, lon)) for lat, lon in p], fill=c)
            for l in lines:
                if CLASSES[c][0] == "river":
                    draw.line([tuple(v * ss for v in proj(lat, lon)) for lat, lon in l], fill=c, width=river_px)
    return np.asarray(img)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scenario", help="scenario name under assets/scenarios/")
    ap.add_argument("--refresh", action="store_true", help="ignore the Overpass cache")
    ap.add_argument("--preview", type=Path, help="also write a colour-by-class preview PNG here")
    args = ap.parse_args()

    d = REPO / "assets" / "scenarios" / args.scenario
    terrain = json.loads((d / "terrain.json").read_text())
    proj = Projector(terrain)
    elements = fetch(query(terrain["bounds"]), args.refresh)
    print(f"{len(elements)} land-cover elements")

    ss = SUPERSAMPLE
    classes = rasterize(elements, proj, ss).copy()
    if args.scenario in LOWLAND_FARMLAND_M:
        names = [name for name, _, _ in CLASSES]
        heights = np.load(d / terrain["heightmap"]["file"]).repeat(ss, axis=0).repeat(ss, axis=1)
        low = (classes == names.index("background")) & (heights < LOWLAND_FARMLAND_M[args.scenario])
        classes[low] = names.index("farmland")
    over = SCENARIO_WEIGHTS.get(args.scenario, {})
    weights = [over.get(name, f) for name, f, _ in CLASSES]
    lut = np.array(weights, np.float32)
    fine = lut[classes]
    fuel = fine.reshape(proj.h, ss, proj.w, ss).mean(axis=(1, 3))

    out = d / "fuel.png"
    Image.fromarray(np.round(fuel / MAX_FUEL * 255).astype(np.uint8), "L").save(out)
    print(f"Wrote {out.relative_to(REPO)} ({proj.w}x{proj.h}), mean fuel {fuel.mean():.2f}, "
          f"unburnable cells {(fuel == 0).sum()}")
    counts = np.bincount(classes.ravel(), minlength=len(CLASSES)) / classes.size
    for (name, _, _), f, share in zip(CLASSES, weights, counts):
        if share:
            print(f"  {name:12s} fuel {f:.1f}  {share:6.1%} of the map")

    if args.preview:
        pal = np.array([PREVIEW_COLOURS[n] for n, _, _ in CLASSES], np.uint8)
        Image.fromarray(pal[classes]).resize((proj.w * 3, proj.h * 3), Image.NEAREST).save(args.preview)
        print(f"Wrote preview {args.preview}")


if __name__ == "__main__":
    main()
