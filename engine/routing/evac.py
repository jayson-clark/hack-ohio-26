"""Arrival-time-aware evacuation routing (PLAN.md, Evacuation routing).

Edge cost is `length * (1 + LAMBDA * P(edge burns by the time the bus gets
there))`, so routes avoid roads that *will* burn, not only roads burning now.
Edges that are burning or near-certain to burn by arrival are impassable.

The approximation, chosen so a full replan stays in the tens of milliseconds:

1. Time is bucketed. For every edge we precompute P(burn by t) at fixed
   time bins (BIN_MINUTES apart) in one vectorized pass over the forecast's
   first_burn array: each edge's probability is the max over the cells it
   crosses of the fraction of rollouts that burned that cell by t.
2. A plain label-setting Dijkstra runs on that cost. Each label also carries
   the bus's arrival time, which is free-flow drive time along the label's
   own path (path metres / BUS_SPEED), and the edge's probability is read at
   the bin containing the arrival time at the edge's midpoint. This isn't a
   full time-dependent shortest path (a cheaper-but-later prefix can't be
   revisited), but the bus speed doesn't depend on cost, so the two only
   disagree when a detour is both cheaper and slower, and then only by a bin.
3. Arrival times past the forecast horizon read the horizon's probability.
"""

import heapq
import math
from dataclasses import dataclass, field

import numpy as np

from protocol import RouteInfo, Routes
from routing.roads import RoadNetwork

LAMBDA = 8.0  # how many extra "lengths" a certain-to-burn edge costs
BLOCK_P = 0.9  # at or above this P(burn by arrival) an edge is impassable
RISKY_P = 0.25  # route status turns "risky" above this
BUS_SPEED_KMH = 25.0  # evacuation traffic, not free-flow (Camp Fire roads jammed)
BIN_MINUTES = 5.0
DEFAULT_MINUTES_PER_TICK = 1.0  # until sim/fire.py exists


def sim_minutes_per_tick() -> float:
    """SIM_MINUTES_PER_TICK from the sim, imported lazily so routing (and its
    tests) work before the sim lands."""
    try:
        from sim.fire import SIM_MINUTES_PER_TICK
    except ImportError:
        return DEFAULT_MINUTES_PER_TICK
    return float(SIM_MINUTES_PER_TICK)


@dataclass
class Route:
    town: str  # the town evacuated, or "Bus <id>" for a bus token's route
    safe_zone: str | None
    points: list[list[float]] = field(default_factory=list)  # map coords
    length_m: float = 0.0
    eta_min: float = 0.0  # drive time, sim minutes
    risk: float = 0.0  # max P(burn by arrival) over the route's edges
    status: str = "clear"  # clear | risky | cut
    bus: str | None = None  # token id when this is a bus's route
    # For re-evaluating and comparing routes; not sent to the UI.
    nodes: list[int] = field(default_factory=list, repr=False)
    edges: list[int] = field(default_factory=list, repr=False)
    cost: float = math.inf

    @property
    def key(self) -> str:
        """Stable identity across replans: the town, or the bus token."""
        return f"bus:{self.bus}" if self.bus else self.town


def edge_burn_curves(
    net: RoadNetwork, first_burn: np.ndarray, bin_ticks: float, n_bins: int, elapsed_ticks: float = 0.0
) -> np.ndarray:
    """float32 (E, n_bins): P(edge burns by bin_k * bin_ticks from now).

    `elapsed_ticks` is how old the forecast is; first_burn counts from the
    tick the forecast was made, so subtract the time that has since passed.
    """
    n = first_burn.shape[0]
    fb = first_burn.reshape(n, -1)[:, net.sample_cell].astype(np.float32) - np.float32(elapsed_ticks)
    # Bin k holds t_k = k * bin_ticks; a cell first burning at fb counts as
    # burned from bin ceil(fb / bin_ticks) on. inf (never) and anything past
    # the last bin land in an overflow bin that's dropped.
    idx = np.ceil(np.maximum(fb, 0.0) / bin_ticks)
    idx = np.where(np.isfinite(idx), np.minimum(idx, n_bins), n_bins).astype(np.int64)
    s = fb.shape[1]
    flat = (np.arange(s, dtype=np.int64)[None, :] * (n_bins + 1) + idx).ravel()
    counts = np.bincount(flat, minlength=s * (n_bins + 1)).reshape(s, n_bins + 1)
    p_sample = np.cumsum(counts[:, :n_bins], axis=1, dtype=np.float32) / n
    if len(net.sample_start) == 0:
        return np.zeros((0, n_bins), np.float32)
    return np.maximum.reduceat(p_sample, net.sample_start, axis=0)


def _adjacency(net: RoadNetwork) -> list[list[tuple[int, int]]]:
    adj = getattr(net, "_adj", None)
    if adj is None:
        adj = [[] for _ in range(len(net.nodes))]
        for eid, (i, j) in enumerate(net.edges):
            adj[i].append((int(j), eid))
            adj[j].append((int(i), eid))
        net._adj = adj
    return adj


@dataclass
class _Context:
    """Everything one replan's searches share: built once, read by each."""

    net: RoadNetwork
    adj: list[list[tuple[int, int]]]
    curves: np.ndarray  # (E, n_bins) P(edge burns by bin)
    closed: np.ndarray  # (E,) bool: burning right now, impassable regardless of forecast
    zones: dict[int, int]  # node -> safe zone index
    speed: float  # metres per tick
    bin_ticks: float
    mpt: float  # sim minutes per tick


def _context(net, first_burn, elapsed_ticks, minutes_per_tick, horizon_minutes, closed) -> _Context:
    mpt = minutes_per_tick or sim_minutes_per_tick()
    bin_ticks = BIN_MINUTES / mpt
    n_bins = max(1, int(math.ceil(horizon_minutes / BIN_MINUTES)) + 1)
    if first_burn is None:
        curves = np.zeros((len(net.edges), n_bins), np.float32)
    else:
        curves = edge_burn_curves(net, first_burn, bin_ticks, n_bins, elapsed_ticks)
    if closed is None:
        closed = np.zeros(len(net.edges), bool)
    return _Context(
        net=net,
        adj=_adjacency(net),
        curves=curves,
        closed=closed,
        zones={node: zi for zi, node in enumerate(net.zone_node)},
        speed=BUS_SPEED_KMH * 1000 / 60 * mpt,
        bin_ticks=bin_ticks,
        mpt=mpt,
    )


def _edge(ctx: _Context, eid: int, t: float) -> tuple[float, bool]:
    """(P(edge burns by the time a bus that set off at t reaches its middle), impassable?)."""
    t_mid = t + 0.5 * ctx.net.length_m[eid] / ctx.speed
    k = min(int(math.ceil(t_mid / ctx.bin_ticks)), ctx.curves.shape[1] - 1)
    p = float(ctx.curves[eid, k])
    return p, bool(ctx.closed[eid]) or p >= BLOCK_P


def plan_routes(
    net: RoadNetwork,
    first_burn: np.ndarray | None,
    *,
    elapsed_ticks: float = 0.0,
    minutes_per_tick: float | None = None,
    horizon_minutes: float = 180.0,
    closed: np.ndarray | None = None,
    buses: list[tuple[str, float, float]] = (),
) -> list[Route]:
    """Best route from every town (and every bus at (x, y)) to its best safe
    zone. With no forecast every edge has P = 0 and routes are just shortest
    paths. `closed` marks edges that are burning now."""
    ctx = _context(net, first_burn, elapsed_ticks, minutes_per_tick, horizon_minutes, closed)
    return _plan(ctx, buses)


def replan_routes(
    net: RoadNetwork,
    first_burn: np.ndarray | None,
    held: dict[str, tuple[list[int], list[int]]],
    *,
    elapsed_ticks: float = 0.0,
    minutes_per_tick: float | None = None,
    horizon_minutes: float = 180.0,
    closed: np.ndarray | None = None,
    buses: list[tuple[str, float, float]] = (),
) -> tuple[list[Route], dict[str, Route]]:
    """Like plan_routes, plus each currently shown route (`held`: key ->
    (node path, edge ids)) re-scored under the same forecast, so RouteTracker can compare the
    route on screen with the new best one fairly."""
    ctx = _context(net, first_burn, elapsed_ticks, minutes_per_tick, horizon_minutes, closed)
    best = _plan(ctx, buses)
    names = {r.key: (r.town, r.bus) for r in best}
    rescored = {}
    for key, (nodes, edges) in held.items():
        if key in names and edges:
            rescored[key] = evaluate_path(ctx, nodes, edges, *names[key])
    return best, rescored


def _plan(ctx: _Context, buses) -> list[Route]:
    net = ctx.net
    routes = [_route_one(ctx, start, town.name) for town, start in zip(net.towns, net.town_node)]
    for token_id, x, y in buses:
        routes.append(_route_one(ctx, net.nearest_node(x, y), f"Bus {token_id}", bus=token_id))
    return routes


def _route_one(ctx: _Context, start: int, town: str, bus: str | None = None) -> Route:
    net, adj = ctx.net, ctx.adj
    cost = {start: 0.0}
    t_at = {start: 0.0}
    prev: dict[int, tuple[int, int]] = {}  # node -> (previous node, edge id)
    done = set()
    heap = [(0.0, start)]
    best_zone = None
    while heap:
        c, u = heapq.heappop(heap)
        if u in done:
            continue
        done.add(u)
        if u in ctx.zones:
            # Dijkstra settles nodes in cost order, so the first zone reached
            # is the cheapest.
            best_zone = u
            break
        tu = t_at[u]
        for v, eid in adj[u]:
            if v in done:
                continue
            p, blocked = _edge(ctx, eid, tu)
            if blocked:
                continue
            nc = c + net.length_m[eid] * (1.0 + LAMBDA * p)
            if nc < cost.get(v, math.inf):
                cost[v] = nc
                t_at[v] = tu + net.length_m[eid] / ctx.speed
                prev[v] = (u, eid)
                heapq.heappush(heap, (nc, v))

    if best_zone is None:
        return Route(town=town, safe_zone=None, status="cut", risk=1.0, bus=bus)
    path, edges = [best_zone], []
    while path[-1] != start:
        u, eid = prev[path[-1]]
        path.append(u)
        edges.append(eid)
    path.reverse()
    edges.reverse()
    return evaluate_path(ctx, path, edges, town, bus)


def evaluate_path(ctx: _Context, nodes: list[int], edges: list[int], town: str, bus: str | None = None) -> Route:
    """Score a fixed node path under ctx's forecast: the same numbers the
    search uses, and status "cut" if any edge on it is now impassable."""
    net = ctx.net
    t = cost = risk = length = 0.0
    blocked_any = False
    for eid in edges:
        p, blocked = _edge(ctx, eid, t)
        blocked_any |= blocked
        m = net.length_m[eid]
        cost += m * (1.0 + LAMBDA * p)
        t += m / ctx.speed
        risk = max(risk, p)
        length += m
    if blocked_any:
        status = "cut"
    else:
        status = "risky" if risk >= RISKY_P else "clear"
    end = nodes[-1]
    zone = net.safe_zones[ctx.zones[end]].name if end in ctx.zones else None
    return Route(
        town=town,
        safe_zone=zone if not blocked_any else None,
        points=[[round(float(x), 2), round(float(y), 2)] for x, y in net.nodes[nodes]],
        length_m=round(float(length), 1),
        eta_min=round(t * ctx.mpt, 1),
        risk=1.0 if blocked_any else round(risk, 3),
        status=status,
        bus=bus,
        nodes=list(nodes),
        edges=list(edges),
        cost=math.inf if blocked_any else cost,
    )


def burning_edges(net: RoadNetwork, state: np.ndarray, burning_value: int) -> np.ndarray:
    """(E,) bool: edges with a cell that is burning right now in the live sim."""
    if len(net.sample_start) == 0:
        return np.zeros(0, bool)
    hot = state.reshape(-1)[net.sample_cell] == burning_value
    return np.logical_or.reduceat(hot, net.sample_start)


def routes_message(routes: list[Route], tick: int) -> Routes:
    """The `routes` message for the UI, with every number as a plain float."""
    return Routes(
        tick=tick,
        routes=[
            RouteInfo(
                town=r.town,
                safe_zone=r.safe_zone,
                points=[[float(x), float(y)] for x, y in r.points],
                length_m=float(r.length_m),
                eta_min=float(r.eta_min),
                risk=float(r.risk),
                status=r.status,
                bus=r.bus,
            )
            for r in routes
        ],
    )
