"""Road graph, towns and safe zones for a scenario.

All three come from tools/osm_to_layers.py (roads.json, towns.json). The graph
is loaded once; per-forecast work lives in routing/evac.py and only touches
the precomputed sample arrays here, so it stays fast.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

import networkx as nx
import numpy as np

# Burn is sampled every this many cells along each edge. One cell is the
# sim's resolution, so finer sampling only finds the same cells again.
SAMPLE_STEP_CELLS = 1.0


@dataclass(frozen=True)
class Town:
    name: str
    x: float
    y: float
    radius: float  # cells
    population: int
    structures: int


@dataclass(frozen=True)
class SafeZone:
    name: str
    x: float
    y: float


@dataclass
class RoadNetwork:
    graph: nx.Graph  # node -> {"x", "y"}; edge -> {"length_m", "class", "eid"}
    nodes: np.ndarray  # float (N, 2) map coords
    edges: np.ndarray  # int (E, 2) node indices
    length_m: np.ndarray  # float (E,)
    classes: list[str]
    width: int
    height: int
    # Flattened burn samples for every edge: the cell index each sample falls
    # in, and which edge it belongs to. Samples are sorted by edge, and
    # `sample_start[e]` is where edge e's run begins (for np.maximum.reduceat).
    sample_cell: np.ndarray = field(repr=False)
    sample_start: np.ndarray = field(repr=False)
    towns: list[Town] = field(default_factory=list)
    safe_zones: list[SafeZone] = field(default_factory=list)
    town_node: list[int] = field(default_factory=list)
    zone_node: list[int] = field(default_factory=list)

    def nearest_node(self, x: float, y: float) -> int:
        return int(np.argmin(((self.nodes - (x, y)) ** 2).sum(axis=1)))


def build_network(
    nodes: list, edges: list, width: int, height: int, towns=(), safe_zones=()
) -> RoadNetwork:
    """From roads.json-shaped lists. Tests build tiny networks with this."""
    pts = np.asarray(nodes, dtype=float).reshape(-1, 2)
    ij = np.asarray([[e[0], e[1]] for e in edges], dtype=np.int64).reshape(-1, 2)
    length = np.asarray([e[2] for e in edges], dtype=float)
    classes = [e[3] if len(e) > 3 else "road" for e in edges]

    g = nx.Graph()
    for i, (x, y) in enumerate(pts):
        g.add_node(i, x=float(x), y=float(y))
    for eid, ((i, j), m, c) in enumerate(zip(ij, length, classes)):
        g.add_edge(int(i), int(j), length_m=float(m), cls=c, eid=eid)

    cells, starts = [], []
    total = 0
    for i, j in ij:
        a, b = pts[i], pts[j]
        n = max(2, int(np.ceil(np.hypot(*(b - a)) / SAMPLE_STEP_CELLS)) + 1)
        t = np.linspace(0.0, 1.0, n)[:, None]
        p = a + (b - a) * t
        cx = np.clip(p[:, 0].astype(int), 0, width - 1)
        cy = np.clip(p[:, 1].astype(int), 0, height - 1)
        c = np.unique(cy * width + cx)
        starts.append(total)
        cells.append(c)
        total += len(c)

    net = RoadNetwork(
        graph=g,
        nodes=pts,
        edges=ij,
        length_m=length,
        classes=classes,
        width=width,
        height=height,
        sample_cell=np.concatenate(cells) if cells else np.zeros(0, np.int64),
        sample_start=np.asarray(starts, dtype=np.int64),
        towns=[Town(**t) if isinstance(t, dict) else t for t in towns],
        safe_zones=[SafeZone(z["name"], z["x"], z["y"]) if isinstance(z, dict) else z for z in safe_zones],
    )
    net.town_node = [net.nearest_node(t.x, t.y) for t in net.towns]
    net.zone_node = [net.nearest_node(z.x, z.y) for z in net.safe_zones]
    return net


def load_network(scenario_dir: Path, width: int, height: int) -> RoadNetwork | None:
    """None when the scenario has no road layer, so the engine still runs."""
    roads_path, towns_path = scenario_dir / "roads.json", scenario_dir / "towns.json"
    if not roads_path.exists():
        return None
    roads = json.loads(roads_path.read_text())
    layer = json.loads(towns_path.read_text()) if towns_path.exists() else {}
    towns = [
        {k: t[k] for k in ("name", "x", "y", "radius", "population", "structures")}
        for t in layer.get("towns", [])
    ]
    return build_network(roads["nodes"], roads["edges"], width, height, towns, layer.get("safe_zones", []))
