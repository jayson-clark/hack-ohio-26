# /// script
# requires-python = ">=3.12"
# dependencies = ["numpy>=2.0", "pillow>=10.0"]
# ///
"""Generate a small fictional "training valley" scenario, no DEM download.

Paradise is a real place, so its terrain must come from the shared DEM pipeline
(tools/dem_to_assets.py) to match the 3D print. The training valley is
fictional (PLAN.md, Game layer: "a fictional training valley"), so its
heightmap is synthesised here: a V-shaped valley running west-to-east with a
ridge down each side, which gives the fire an obvious uphill to climb and a
natural evacuation corridor along the valley floor.

    uv run tools/make_valley.py

Writes assets/scenarios/valley/: heightmap.npy, terrain.json, roads.json,
towns.json, stations.json, game.json, preview.png. The grid is smaller than Paradise (160x120)
so forecasts and the sim stay quick. No STL tiles: the valley is a virtual-table
scenario for development and a second demo map, not something we print.
"""

import json
from pathlib import Path

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "assets" / "scenarios" / "valley"

WIDTH, HEIGHT = 160, 120
CELL_SIZE_M = 94.0  # same cell scale as Paradise, so the fire model tuning carries over
# The UI's 3D table needs a model size even for a board that's never printed;
# use Paradise's print scale and relief so the two look alike side by side.
CELL_SIZE_MM = 1.28984375
RELIEF_MM = 35.0
BASE_MM = 6.0
# Corner calibration markers sit this far outside the board, as on Paradise.
MARKER_OFFSET_MM = 18.4
# A made-up spot for the cursor's lat/lon readout; nothing real lives here.
ORIGIN_LAT, ORIGIN_LON = 39.55, -121.25


def heightmap() -> np.ndarray:
    """A valley floor along the middle row, rising to a ridge north and south,
    with a gentle downhill slope from west (high) to east (low) so the fire has
    a prevailing uphill to the west. Metres above sea level."""
    ys, xs = np.mgrid[:HEIGHT, :WIDTH].astype(np.float32)
    # Distance from the valley centreline (row HEIGHT/2), 0 on the floor, 1 at the edges.
    d = np.abs(ys - (HEIGHT - 1) / 2) / ((HEIGHT - 1) / 2)
    ridge = 700.0 * d**1.4  # valley walls climb to ~700 m above the floor
    floor = 300.0 + (WIDTH - 1 - xs) / (WIDTH - 1) * 250.0  # 300 m east, 550 m west
    h = floor + ridge
    # A couple of side canyons cutting into the north wall, for visual interest.
    for cx in (45.0, 110.0):
        canyon = np.exp(-(((xs - cx) / 6.0) ** 2)) * np.clip(ys - HEIGHT / 2, 0, None) * 3.0
        h -= canyon
    return h.astype(np.float32)


def build() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    h = heightmap()
    np.save(OUT / "heightmap.npy", h)

    mid = (HEIGHT - 1) / 2
    places = [
        {"name": "Millbrook", "map": [34.0, mid]},
        {"name": "Cedar Flats", "map": [96.0, mid - 2.0]},
        {"name": "Ridgeview", "map": [128.0, mid - 22.0]},
    ]
    width_mm, height_mm = WIDTH * CELL_SIZE_MM, HEIGHT * CELL_SIZE_MM
    m_per_mm = CELL_SIZE_M / CELL_SIZE_MM
    lat_span = HEIGHT * CELL_SIZE_M / 111_320
    lon_span = WIDTH * CELL_SIZE_M / (111_320 * np.cos(np.radians(ORIGIN_LAT)))

    def corner(name, x_mm, y_mm):
        return {"corner": name, "center_mm": [x_mm, y_mm],
                "center_map": [x_mm / CELL_SIZE_MM, (height_mm - y_mm) / CELL_SIZE_MM]}

    o = MARKER_OFFSET_MM
    terrain = {
        "name": "valley",
        "generated_by": "tools/make_valley.py",
        "source": "synthetic (fictional training scenario)",
        "bounds": {"south": ORIGIN_LAT - lat_span, "west": ORIGIN_LON,
                   "north": ORIGIN_LAT, "east": ORIGIN_LON + float(lon_span)},
        "grid": {"width": WIDTH, "height": HEIGHT, "cell_size_m": CELL_SIZE_M, "cell_size_mm": CELL_SIZE_MM},
        "model": {"width_mm": width_mm, "height_mm": height_mm, "base_mm": BASE_MM, "relief_mm": RELIEF_MM,
                  "m_per_mm": m_per_mm,
                  "vertical_exaggeration": float(RELIEF_MM * m_per_mm / (h.max() - h.min()))},
        "markers": {"marker_size_mm": 30.0, "marker_top_z_mm": 5.0, "corners": [
            corner("NW", -o, height_mm + o), corner("NE", width_mm + o, height_mm + o),
            corner("SE", width_mm + o, -o), corner("SW", -o, -o)]},
        "tiles": [{"row": 0, "col": 0, "origin_mm": [0.0, 0.0], "size_mm": [width_mm, height_mm]}],
        "heightmap": {"file": "heightmap.npy", "dtype": "float32",
                      "units": "m above sea level", "row0": "north"},
        "elevation_m": {"min": float(h.min()), "max": float(h.max())},
        "places": [{"name": p["name"], "map": p["map"]} for p in places],
    }
    (OUT / "terrain.json").write_text(json.dumps(terrain, indent=2))

    # Towns sit along the valley floor; scoring uses population/structures.
    towns = [
        {"name": "Millbrook", "x": 34.0, "y": mid, "radius": 14.0, "population": 4200, "structures": 1800},
        {"name": "Cedar Flats", "x": 96.0, "y": mid - 2.0, "radius": 10.0, "population": 1500, "structures": 650},
        {"name": "Ridgeview", "x": 128.0, "y": mid - 22.0, "radius": 7.0, "population": 500, "structures": 240},
    ]
    # Safe zones are the valley-mouth exits at the east and west map edges.
    safe_zones = [
        {"name": "West Junction (Valley Road)", "x": 1.0, "y": mid, "road": "Valley Road"},
        {"name": "East Gate (Valley Road)", "x": WIDTH - 2.0, "y": mid, "road": "Valley Road"},
    ]
    (OUT / "towns.json").write_text(json.dumps(
        {"generated_by": "tools/make_valley.py", "towns": towns, "safe_zones": safe_zones}, indent=2))

    # A simple road graph: one highway down the valley floor through the towns
    # to each exit, plus a spur up to Ridgeview. nodes are [x, y]; edges are
    # [i, j, length_m, class] (same shape routing.roads.build_network reads).
    nodes = [
        [1.0, mid],            # 0 west exit
        [34.0, mid],           # 1 Millbrook
        [96.0, mid - 2.0],     # 2 Cedar Flats
        [120.0, mid - 2.0],    # 3 junction for the Ridgeview spur
        [WIDTH - 2.0, mid],    # 4 east exit
        [128.0, mid - 22.0],   # 5 Ridgeview
    ]

    def seg(i, j, cls="primary"):
        (xi, yi), (xj, yj) = nodes[i], nodes[j]
        length_m = float(np.hypot(xj - xi, yj - yi) * CELL_SIZE_M)
        return [i, j, length_m, cls]

    edges = [seg(0, 1), seg(1, 2), seg(2, 3), seg(3, 4), seg(3, 5, "secondary")]
    (OUT / "roads.json").write_text(json.dumps(
        {"generated_by": "tools/make_valley.py", "nodes": nodes, "edges": edges}, indent=2))

    # Dispatch (#104): ground stations on road nodes (units snap to the
    # nearest node, so on-node means no hike), and an air base off the west
    # edge. Same schema and unit mix as Paradise's stations.json.
    stations = [
        {"name": "Millbrook Station", "x": nodes[1][0], "y": nodes[1][1], "kind": "ground",
         "units": {"crew": 1, "firebreak": 1}},
        {"name": "Cedar Flats Station", "x": nodes[2][0], "y": nodes[2][1], "kind": "ground",
         "units": {"crew": 1, "firebreak": 1}},
        {"name": "Valley Air Attack Base", "x": -40.0, "y": mid, "kind": "air", "units": {"water": 2}},
    ]
    (OUT / "stations.json").write_text(json.dumps(
        {"generated_by": "tools/make_valley.py", "stations": stations}, indent=2))

    # Round settings: shorter than Paradise, ignite on the east (downhill) end
    # so the fire runs uphill/west toward the towns and the wind can steer it.
    (OUT / "game.json").write_text(json.dumps(
        {"duration_min": 360, "ignition": [WIDTH - 10.0, mid + 6.0], "bus_people_per_min": 30}, indent=2))

    # A quick grayscale preview of the heightmap (north at the top).
    norm = (h - h.min()) / max(1e-6, h.max() - h.min())
    Image.fromarray((norm * 255).astype(np.uint8), "L").save(OUT / "preview.png")

    print(f"wrote {OUT} ({WIDTH}x{HEIGHT}, {len(towns)} towns, {len(edges)} road segments)")


if __name__ == "__main__":
    build()
