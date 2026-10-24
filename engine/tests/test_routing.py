import json
import sys
from pathlib import Path

import networkx as nx
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from routing.evac import plan_routes
from routing.roads import build_network, load_network
from scenario import load_scenario


def test_projection_matches_terrain_places():
    # Same linear lon/lat -> map projection tools/osm_to_layers.py uses.
    s = load_scenario("paradise")
    b = s.terrain["bounds"]
    for p in s.terrain["places"]:
        x = (p["lon"] - b["west"]) / (b["east"] - b["west"]) * s.width
        y = (b["north"] - p["lat"]) / (b["north"] - b["south"]) * s.height
        assert abs(x - p["map"][0]) < 1 and abs(y - p["map"][1]) < 1, p["name"]


def test_paradise_towns_reach_a_safe_zone():
    s = load_scenario("paradise")
    net = load_network(s.dir, s.width, s.height)
    assert net is not None and len(net.edges) < 5000
    assert nx.is_connected(net.graph)
    routes = plan_routes(net, None)
    assert len(routes) == len(net.towns) >= 4
    for r in routes:
        assert r.status == "clear" and r.safe_zone, r
        assert r.length_m > 0


def test_routes_avoid_corridor_that_will_burn():
    # Town at (2, 10), exit at (38, 10). The direct road runs along y=10;
    # the detour goes up through y=2. The fake forecast burns the y=10
    # corridor a few ticks from now, before the bus could get there.
    W, H = 40, 20
    nodes = [[2, 10], [20, 10], [38, 10], [2, 2], [38, 2]]
    edges = [[0, 1, 1700, "primary"], [1, 2, 1700, "primary"],
             [0, 3, 750, "tertiary"], [3, 4, 3400, "tertiary"], [4, 2, 750, "tertiary"]]
    town = {"name": "T", "x": 2, "y": 10, "radius": 1, "population": 1, "structures": 1}
    net = build_network(nodes, edges, W, H, [town], [{"name": "Exit", "x": 38, "y": 10}])

    first_burn = np.full((8, H, W), np.inf, np.float32)
    [clear] = plan_routes(net, first_burn, minutes_per_tick=1.0)
    assert clear.length_m == 3400  # direct road when nothing burns

    first_burn[:, 8:13, 10:30] = 3.0
    [r] = plan_routes(net, first_burn, minutes_per_tick=1.0)
    assert [2.0, 2.0] in r.points and r.safe_zone == "Exit"
    assert r.length_m == 4900

    first_burn[:, 0:20, 18:22] = 0.0  # both roads already burning
    [cut] = plan_routes(net, first_burn, minutes_per_tick=1.0)
    assert cut.status == "cut"


def test_towns_json_shape():
    layer = json.loads((load_scenario("paradise").dir / "towns.json").read_text())
    assert {"Paradise", "Magalia", "Concow", "Pulga"} <= {t["name"] for t in layer["towns"]}
    assert 1 <= len(layer["safe_zones"]) <= 3
