"""How long a fire unit takes to get somewhere (#104).

Ground units (engine crews, dozers) leave a station, drive the road graph at
UNIT_SPEED_KMH, skipping roads that are burning right now, and walk the last
stretch off-road at HIKE_KMH. Tankers fly straight from an air base at
TANKER_KMH after a load-and-launch delay. Every order also pays TURNOUT_MIN
before anyone moves.

All times are in sim minutes. With one tick per sim minute (sim.fire), that's
also ticks.
"""

import heapq
import math
from dataclasses import dataclass

import numpy as np

from routing.evac import _adjacency
from routing.roads import RoadNetwork

UNIT_SPEED_KMH = 50.0  # engines on mountain roads, lights on
HIKE_KMH = 4.0  # crews on foot (or a dozer walking) from the road to the spot
TANKER_KMH = 300.0
TURNOUT_MIN = 3.0  # call to wheels rolling
TANKER_LAUNCH_MIN = 10.0  # load retardant and take off
# Tankers don't fly in high wind. Wind at the scenario's 8-10 m/s default is
# fine; much past this, they're grounded (the Camp Fire's first morning).
TANKER_MAX_WIND_MS = 13.0


_NEAREST: dict[tuple, tuple[np.ndarray, np.ndarray]] = {}


def _nearest_nodes(node_xy: np.ndarray, h: int, w: int) -> tuple[np.ndarray, np.ndarray]:
    """Every cell's nearest road node and its distance in cells, (H, W) each.
    About a second for Paradise, so it's cached per road network."""
    key = (h, w, node_xy.shape, hash(np.ascontiguousarray(node_xy).tobytes()))
    if key not in _NEAREST:
        cy, cx = np.mgrid[:h, :w].astype(np.float32) + 0.5
        cells = np.stack([cx.ravel(), cy.ravel()], axis=1)
        nodes = node_xy.astype(np.float32)
        near = np.empty(len(cells), np.int64)
        dist = np.empty(len(cells), np.float32)
        for i in range(0, len(cells), 4096):  # chunks keep the (cells x nodes) table small
            d2 = ((cells[i : i + 4096, None, :] - nodes[None, :, :]) ** 2).sum(axis=2)
            near[i : i + 4096] = d2.argmin(axis=1)
            dist[i : i + 4096] = np.sqrt(d2.min(axis=1))
        _NEAREST[key] = (near.reshape(h, w), dist.reshape(h, w))
    return _NEAREST[key]


@dataclass(frozen=True)
class Station:
    name: str
    x: float
    y: float
    kind: str  # "ground" or "air"
    units: dict[str, int]  # token type -> how many it can send


class UnitRouter:
    """Travel times on one scenario's road graph. Build once, then call
    `refresh(closed)` whenever the set of burning roads changes."""

    def __init__(self, net: RoadNetwork, cell_m: float) -> None:
        self.net = net
        self.cell_m = cell_m
        self.adj = _adjacency(net)
        self.drive_min_per_m = 60.0 / (UNIT_SPEED_KMH * 1000.0)
        self.hike_min_per_m = 60.0 / (HIKE_KMH * 1000.0)
        h, w = net.height, net.width
        near, dist = _nearest_nodes(net.nodes, h, w)
        self.cell_node = near
        self.cell_hike_min = dist * cell_m * self.hike_min_per_m
        self.closed = np.zeros(len(net.edges), bool)
        self._cache: dict[int, tuple[np.ndarray, np.ndarray]] = {}

    def refresh(self, closed: np.ndarray) -> None:
        """New set of impassable (burning) edges; drops cached searches if it changed."""
        if not np.array_equal(closed, self.closed):
            self.closed = closed.copy()
            self._cache.clear()

    def from_node(self, start: int) -> tuple[np.ndarray, np.ndarray]:
        """(minutes to every node, previous node on the fastest path), by road."""
        if start in self._cache:
            return self._cache[start]
        n = len(self.net.nodes)
        t = np.full(n, np.inf)
        prev = np.full(n, -1, np.int64)
        t[start] = 0.0
        heap = [(0.0, start)]
        while heap:
            d, u = heapq.heappop(heap)
            if d > t[u]:
                continue
            for v, eid in self.adj[u]:
                if self.closed[eid]:
                    continue
                nd = d + self.net.length_m[eid] * self.drive_min_per_m
                if nd < t[v]:
                    t[v], prev[v] = nd, u
                    heapq.heappush(heap, (nd, v))
        self._cache[start] = (t, prev)
        return t, prev

    def _start(self, x: float, y: float) -> tuple[int, float]:
        """Nearest road node to (x, y), and the minutes to walk there."""
        i = self.net.nearest_node(x, y)
        nx, ny = self.net.nodes[i]
        return i, math.hypot(nx - x, ny - y) * self.cell_m * self.hike_min_per_m

    def ground_eta(self, x0: float, y0: float, x: float, y: float) -> tuple[float, list[list[float]]]:
        """Minutes for a ground unit at (x0, y0) to reach (x, y), and its path
        (map coords). inf and [] if burning roads cut it off."""
        start, walk_out = self._start(x0, y0)
        t, prev = self.from_node(start)
        h, w = self.cell_node.shape
        cx, cy = min(max(int(x), 0), w - 1), min(max(int(y), 0), h - 1)
        end = int(self.cell_node[cy, cx])
        if not np.isfinite(t[end]):
            return math.inf, []
        hike = math.hypot(*(self.net.nodes[end] - (x, y))) * self.cell_m * self.hike_min_per_m
        path, u = [], end
        while u != -1:
            path.append([round(float(self.net.nodes[u][0]), 2), round(float(self.net.nodes[u][1]), 2)])
            u = int(prev[u]) if u != start else -1
        path.reverse()
        return walk_out + float(t[end]) + hike, [[round(x0, 2), round(y0, 2)]] + path + [[round(x, 2), round(y, 2)]]

    def ground_grid(self, x0: float, y0: float) -> np.ndarray:
        """Minutes for a ground unit at (x0, y0) to reach every cell, float (H, W); inf if cut off."""
        start, walk_out = self._start(x0, y0)
        t, _ = self.from_node(start)
        return walk_out + t[self.cell_node] + self.cell_hike_min

    def air_eta(self, x0: float, y0: float, x: float, y: float) -> float:
        return TANKER_LAUNCH_MIN + math.hypot(x - x0, y - y0) * self.cell_m * 60.0 / (TANKER_KMH * 1000.0)

    def air_grid(self, x0: float, y0: float) -> np.ndarray:
        h, w = self.cell_node.shape
        cy, cx = np.mgrid[:h, :w].astype(np.float32) + 0.5
        return TANKER_LAUNCH_MIN + np.hypot(cx - x0, cy - y0) * self.cell_m * 60.0 / (TANKER_KMH * 1000.0)
