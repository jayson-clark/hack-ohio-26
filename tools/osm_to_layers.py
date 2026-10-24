# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""OpenStreetMap -> scenario road and town layers: roads.json, towns.json.

Evacuation routing (engine/routing/) reads these. They're scenario data like
terrain.json: commit them, and regenerate rather than edit by hand.

    uv run tools/osm_to_layers.py paradise
    uv run tools/osm_to_layers.py paradise --classes motorway,trunk,primary,secondary,tertiary
    uv run tools/osm_to_layers.py paradise --refresh     # re-download instead of using the cache
    uv run tools/osm_to_layers.py paradise --stations-only   # just stations.json (fire dispatch, #104)

Roads come from the Overpass API (no key) for the bounds in terrain.json and
are cached in tools/.cache/overpass/. Town populations and structure counts
are typed in below (TOWNS); they're approximate 2018 figures, good enough for
scoring, not for anything real.

Projection: terrain.json's bounds are the board corners, and the board is a
local equirectangular projection (dem_to_assets.py), so map coords are linear
in lon and lat:  x = (lon - west) / (east - west) * W,
                 y = (north - lat) / (north - south) * H.
`places` in terrain.json were projected the same way through mm, which is
what tests/test_routing.py checks against.

Output (map coords, cell units, origin north-west):
  roads.json  {"nodes": [[x, y], ...], "edges": [[i, j, length_m, class], ...]}
  towns.json  {"towns": [{name, x, y, radius, population, structures}],
               "safe_zones": [{name, x, y, road}], "note": ...}
  stations.json {"stations": [{name, x, y, kind, units: {token_type: count}}]}
               OSM fire stations on the map (crews and dozers, by road) plus the
               air attack bases in AIR_BASES (tankers, by air; may be off the map).
"""

import argparse
import hashlib
import json
import math
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CACHE = REPO / "tools" / ".cache" / "overpass"
OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]
# overpass-api.de answers 406 to urllib's default User-Agent.
USER_AGENT = "firewatch-hackathon/0.1 (tools/osm_to_layers.py)"
EARTH_R = 6371008.8

# Drivable classes, most important first. Residential is included because
# that's where people are, but dead-end residential stubs are pruned (they
# can't be part of any through route) to keep the graph a few thousand edges.
DEFAULT_CLASSES = "motorway,trunk,primary,secondary,tertiary,unclassified,residential"
RANK = {c: i for i, c in enumerate(["motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential"])}
PRUNE_CLASSES = {"residential", "unclassified"}
# Douglas-Peucker tolerance when merging degree-2 nodes. Half a cell keeps
# road shapes at the sim's resolution, so per-edge burn sampling stays honest.
SIMPLIFY_CELLS = 0.5

# Approximate 2018 figures (US Census 2010/ACS for the CDPs, CAL FIRE damage
# inspection counts for structures). radius_km is a rough footprint.
TOWNS = {
    "paradise": [
        {"name": "Paradise", "lat": 39.7596, "lon": -121.6219, "radius_km": 3.2, "population": 26800, "structures": 12000},
        {"name": "Magalia", "lat": 39.8121, "lon": -121.5783, "radius_km": 2.0, "population": 11300, "structures": 5200},
        {"name": "Concow", "lat": 39.7760, "lon": -121.5130, "radius_km": 1.6, "population": 700, "structures": 450},
        {"name": "Butte Creek Canyon", "lat": 39.7877, "lon": -121.6553, "radius_km": 1.2, "population": 1100, "structures": 500},
        {"name": "Yankee Hill", "lat": 39.7035, "lon": -121.5222, "radius_km": 0.8, "population": 330, "structures": 200},
        {"name": "Pulga", "lat": 39.8007, "lon": -121.4486, "radius_km": 0.4, "population": 50, "structures": 30},
    ],
}

# Exits: where an evacuation route leaves the map toward safety. Each is the
# in-graph node of the named road closest to the given map edge.
SAFE_ZONES = {
    "paradise": [
        {"name": "Chico (Skyway)", "road": ["Skyway", "Skyway Road"], "edge": "west"},
        {"name": "Oroville (Clark Rd)", "road": ["Clark Road"], "edge": "south"},
        {"name": "Oroville (Hwy 70)", "road": ["CA 70"], "edge": "south"},
    ],
}


# Air attack bases that serve the scenario: tankers fly from here, so they
# can be off the map. Positions are approximate.
AIR_BASES = {
    "paradise": [{"name": "Chico Air Attack Base", "lat": 39.7954, "lon": -121.8584}],
}
# What each kind of station can send, per station (the round's limits still cap the totals).
GROUND_UNITS = {"crew": 1, "firebreak": 1}  # an engine crew and a dozer
AIR_UNITS = {"water": 2}  # two tankers


def fetch_ways(bounds: dict, classes: list[str], refresh: bool) -> list[dict]:
    bbox = f"{bounds['south']},{bounds['west']},{bounds['north']},{bounds['east']}"
    query = f'[out:json][timeout:120];way["highway"~"^({"|".join(classes)})$"]({bbox});out geom;'
    return fetch(query, refresh, "roads")


def fetch_stations(bounds: dict, refresh: bool) -> list[dict]:
    bbox = f"{bounds['south']},{bounds['west']},{bounds['north']},{bounds['east']}"
    return fetch(f'[out:json][timeout:60];nwr["amenity"="fire_station"]({bbox});out center tags;', refresh, "fire stations")


def write_stations(d: Path, terrain: dict, proj: "Projector", scenario: str, refresh: bool) -> None:
    stations = []
    for el in fetch_stations(terrain["bounds"], refresh):
        lat, lon = (el["lat"], el["lon"]) if "lat" in el else (el["center"]["lat"], el["center"]["lon"])
        x, y = proj(lat, lon)
        if not proj.inside(x, y):
            continue
        tags = el.get("tags", {})
        name = tags.get("name") or (f"Station {tags['ref']}" if tags.get("ref") else f"Fire station {el['id']}")
        stations.append({"name": name, "x": round(x, 2), "y": round(y, 2), "kind": "ground", "units": GROUND_UNITS})
    stations.sort(key=lambda s: s["name"])
    for b in AIR_BASES.get(scenario, []):
        x, y = proj(b["lat"], b["lon"])
        stations.append({"name": b["name"], "x": round(x, 2), "y": round(y, 2), "kind": "air", "units": AIR_UNITS})
    out = {
        "generated_by": "tools/osm_to_layers.py --stations-only",
        "source": "OpenStreetMap contributors (ODbL), via the Overpass API; air bases typed in (approximate)",
        "stations": stations,
    }
    (d / "stations.json").write_text(json.dumps(out, indent=2) + "\n")
    print(f"Wrote {(d / 'stations.json').relative_to(REPO)}: {len(stations)} stations")
    for st in stations:
        print(f"  {st['kind']:6} {st['name']} at ({st['x']:.1f}, {st['y']:.1f})")


def fetch(query: str, refresh: bool, what: str) -> list[dict]:
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{hashlib.sha1(query.encode()).hexdigest()[:16]}.json"
    if path.exists() and not refresh:
        print(f"Using cached {path.relative_to(REPO)}")
        return json.loads(path.read_text())["elements"]
    body = urllib.parse.urlencode({"data": query}).encode()
    last = None
    # The public servers 502/504 under load; a short backoff usually clears it.
    for attempt, url in enumerate(OVERPASS * 3):
        if attempt >= len(OVERPASS):
            time.sleep(10 * (attempt // len(OVERPASS)))
        try:
            print(f"Fetching {what} from {url}")
            req = urllib.request.Request(url, data=body, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=180) as r:
                raw = r.read()
            path.write_bytes(raw)
            return json.loads(raw)["elements"]
        except Exception as e:  # try the next mirror
            last = e
            print(f"  failed: {e}", file=sys.stderr)
    sys.exit(f"Overpass unreachable ({last}); see the osm-layers skill for the fallback.")


class Projector:
    def __init__(self, terrain: dict):
        b, g = terrain["bounds"], terrain["grid"]
        self.b, self.w, self.h = b, g["width"], g["height"]
        self.cell_m = g["cell_size_m"]

    def __call__(self, lat: float, lon: float) -> tuple[float, float]:
        b = self.b
        return ((lon - b["west"]) / (b["east"] - b["west"]) * self.w, (b["north"] - lat) / (b["north"] - b["south"]) * self.h)

    def inside(self, x: float, y: float) -> bool:
        return 0 <= x < self.w and 0 <= y < self.h


def metres(lat1, lon1, lat2, lon2) -> float:
    """Equirectangular distance; exact enough over a few hundred metres."""
    x = math.radians(lon2 - lon1) * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(x, math.radians(lat2 - lat1)) * EARTH_R


def build_graph(ways: list[dict], proj: Projector):
    """OSM nodes inside the map, linked by way segments. Ways that leave the
    map are cut at the boundary (the last inside node becomes the end)."""
    pos: dict[int, tuple[float, float]] = {}
    ll: dict[int, tuple[float, float]] = {}
    adj: dict[int, dict[int, tuple[float, str, str]]] = defaultdict(dict)  # u -> v -> (m, class, name)
    for w in ways:
        cls = w["tags"]["highway"]
        name = w["tags"].get("name") or w["tags"].get("ref") or ""
        refs = {w["tags"].get("ref", "")} | {name}
        label = "|".join(sorted(r for r in refs if r))
        prev = None
        for nid, g in zip(w["nodes"], w["geometry"]):
            x, y = proj(g["lat"], g["lon"])
            if not proj.inside(x, y):
                prev = None
                continue
            pos[nid], ll[nid] = (x, y), (g["lat"], g["lon"])
            if prev is not None and prev != nid:
                m = metres(*ll[prev], *ll[nid])
                old = adj[prev].get(nid)
                if old is None or RANK[cls] < RANK[old[1]]:
                    adj[prev][nid] = adj[nid][prev] = (m, cls, label)
            prev = nid
    return pos, adj


def largest_component(adj) -> set[int]:
    seen, best = set(), set()
    for start in adj:
        if start in seen:
            continue
        comp, stack = {start}, [start]
        while stack:
            for v in adj[stack.pop()]:
                if v not in comp:
                    comp.add(v)
                    stack.append(v)
        seen |= comp
        best = max(best, comp, key=len)
    return best


def prune_dead_ends(adj, keep: set[int]) -> None:
    """Repeatedly drop degree-1 nodes on minor roads. A dead-end street can't
    carry a through route, and nobody routes *to* the end of one; the town's
    nearest junction stands in for its residents."""
    stack = [u for u in adj if len(adj[u]) <= 1]
    while stack:
        u = stack.pop()
        if u not in adj or u in keep or len(adj[u]) > 1:
            continue
        if any(cls not in PRUNE_CLASSES for _, cls, _ in adj[u].values()):
            continue
        for v in list(adj[u]):
            del adj[v][u]
            stack.append(v)
        del adj[u]


def rdp(points: list[tuple[float, float]], tol: float) -> list[int]:
    """Indices kept by Douglas-Peucker."""
    if len(points) < 3:
        return list(range(len(points)))
    (x0, y0), (x1, y1) = points[0], points[-1]
    dx, dy = x1 - x0, y1 - y0
    norm = math.hypot(dx, dy) or 1e-9
    worst, wi = -1.0, 0
    for i in range(1, len(points) - 1):
        px, py = points[i]
        d = abs(dy * (px - x0) - dx * (py - y0)) / norm if norm > 1e-9 else math.hypot(px - x0, py - y0)
        if d > worst:
            worst, wi = d, i
    if worst <= tol:
        return [0, len(points) - 1]
    left = rdp(points[: wi + 1], tol)
    right = rdp(points[wi:], tol)
    return left + [wi + r for r in right[1:]]


def simplify(pos, adj, keep: set[int]):
    """Merge chains of degree-2 nodes into edges, keeping just enough interior
    points (Douglas-Peucker) that the polyline stays within SIMPLIFY_CELLS of
    the real road. Chains also break where the road class changes."""

    def is_junction(u):
        if u in keep or len(adj[u]) != 2:
            return True
        (_, c1, _), (_, c2, _) = adj[u].values()
        return c1 != c2

    nodes, index, edges = [], {}, []

    def node_id(u):
        if u not in index:
            index[u] = len(nodes)
            nodes.append([round(pos[u][0], 3), round(pos[u][1], 3)])
        return index[u]

    done = set()

    def walk(s):
        for v in list(adj[s]):
            if (s, v) in done:
                continue
            chain, cls = [s, v], adj[s][v][1]
            done.add((s, v)); done.add((v, s))
            while not is_junction(chain[-1]) and chain[-1] != s:
                cur, back = chain[-1], chain[-2]
                nxt = next(w for w in adj[cur] if w != back)
                if (cur, nxt) in done:
                    break
                done.add((cur, nxt)); done.add((nxt, cur))
                chain.append(nxt)
            kept = rdp([pos[u] for u in chain], SIMPLIFY_CELLS)
            # Split the chain's length over the kept pieces in proportion to
            # the real (unsimplified) distance between them.
            seg = [0.0]
            for a, b in zip(chain, chain[1:]):
                seg.append(seg[-1] + adj[a][b][0])
            for a, b in zip(kept, kept[1:]):
                i, j = node_id(chain[a]), node_id(chain[b])
                if i != j:
                    edges.append([i, j, round(seg[b] - seg[a], 1), cls])

    for u in [u for u in adj if is_junction(u)]:
        walk(u)
    # Loops with no junction on them (a cul-de-sac ring) have no start yet.
    for u in list(adj):
        if any((u, v) not in done for v in adj[u]):
            keep.add(u)
            walk(u)
    return nodes, edges, index


def nearest_node(nodes, x, y, allowed=None) -> int:
    best, bi = math.inf, -1
    for i, (nx, ny) in enumerate(nodes):
        if allowed is not None and i not in allowed:
            continue
        d = (nx - x) ** 2 + (ny - y) ** 2
        if d < best:
            best, bi = d, i
    return bi


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scenario", help="scenario name under assets/scenarios/")
    ap.add_argument("--classes", default=DEFAULT_CLASSES, help="comma-separated OSM highway classes")
    ap.add_argument("--no-prune", action="store_true", help="keep dead-end residential stubs")
    ap.add_argument("--refresh", action="store_true", help="ignore the Overpass cache")
    ap.add_argument("--stations-only", action="store_true", help="only write stations.json")
    args = ap.parse_args()

    d = REPO / "assets" / "scenarios" / args.scenario
    terrain = json.loads((d / "terrain.json").read_text())
    proj = Projector(terrain)
    if args.stations_only:
        write_stations(d, terrain, proj, args.scenario, args.refresh)
        return
    ways = fetch_ways(terrain["bounds"], args.classes.split(","), args.refresh)
    print(f"{len(ways)} ways")

    pos, adj = build_graph(ways, proj)
    comp = largest_component(adj)
    for u in [u for u in adj if u not in comp]:
        del adj[u]

    # Exits must survive pruning: pick each safe zone's OSM node first.
    zones = []
    for z in SAFE_ZONES.get(args.scenario, []):
        on_road = {u for u in adj for v, (_, _, label) in adj[u].items() if set(label.split("|")) & set(z["road"])}
        if not on_road:
            print(f"warning: no road {z['road']} for safe zone {z['name']}", file=sys.stderr)
            continue
        dist = {"west": lambda p: p[0], "east": lambda p: proj.w - p[0], "north": lambda p: p[1], "south": lambda p: proj.h - p[1]}[z["edge"]]
        u = min(on_road, key=lambda u: dist(pos[u]))
        zones.append((z, u))
    keep = {u for _, u in zones}

    # Each town's nearest junction on a major road also survives, so pruning
    # can't strand a town.
    town_osm = []
    for t in TOWNS.get(args.scenario, []):
        x, y = proj(t["lat"], t["lon"])
        u = min(adj, key=lambda u: (pos[u][0] - x) ** 2 + (pos[u][1] - y) ** 2)
        town_osm.append(u)
    keep |= set(town_osm)

    if not args.no_prune:
        prune_dead_ends(adj, keep)
    nodes, edges, index = simplify(pos, adj, keep)
    print(f"Graph: {len(nodes)} nodes, {len(edges)} edges, {sum(e[2] for e in edges) / 1000:.0f} km of road")

    towns = []
    for t in TOWNS.get(args.scenario, []):
        x, y = proj(t["lat"], t["lon"])
        towns.append({
            "name": t["name"], "x": round(x, 2), "y": round(y, 2),
            "radius": round(t["radius_km"] * 1000 / proj.cell_m, 1),
            "population": t["population"], "structures": t["structures"],
        })  # fmt: skip
    safe = [
        {"name": z["name"], "x": nodes[index[u]][0], "y": nodes[index[u]][1], "road": z["road"][0]}
        for z, u in zones
    ]

    roads = {
        "generated_by": "tools/osm_to_layers.py",
        "source": "OpenStreetMap contributors (ODbL), via the Overpass API",
        "classes": args.classes.split(","),
        "nodes": nodes,
        "edges": edges,
    }
    (d / "roads.json").write_text(json.dumps(roads, separators=(",", ":")) + "\n")
    out = {
        "generated_by": "tools/osm_to_layers.py",
        "note": "Populations and structure counts are approximate 2018 figures, for scoring only.",
        "towns": towns,
        "safe_zones": safe,
    }
    (d / "towns.json").write_text(json.dumps(out, indent=2) + "\n")
    print(f"Wrote {d.relative_to(REPO)}/{{roads.json, towns.json}}: {len(towns)} towns, {len(safe)} safe zones")
    for s in safe:
        print(f"  exit {s['name']} at ({s['x']:.1f}, {s['y']:.1f})")


if __name__ == "__main__":
    main()
