"""The evacuation order clock (#121): when each town has to be ordered out.

Fire tools forecast the fire and alerting tools send the order, but the call
an incident commander actually has to make is *when* to order each town,
given how long it takes to empty. Trigger-boundary research (k-PERIL,
WUI-NITY) frames it as available against required safe evacuation time.
This is that comparison, live, for every town:

- Available time: when the fire first enters the town, per rollout of a
  long forecast (forecast.runner.EVAC_HORIZON_MIN, longer than the ghost's
  hour, because a big town takes hours to empty).
- Required time: MOBILIZE_MIN for the order to reach people and for them to
  set off, then the time for the town's vehicles to drain through the
  tightest road on its way out. Evacuees keep to the biggest roads that
  don't add more than DETOUR_MIN to the drive, and a town uses every open
  exit whose drive is within EXIT_SLACK_MIN of its best one, split in
  proportion to each exit's capacity. Towns already ordered out load the
  same roads, so ordering Magalia slows Paradise down Skyway. That shared
  queue is how Paradise gridlocked in 2018 (NIST TN 2135).

The traffic model is a fluid queue. A road carries CAPACITY_VPH[its class]
vehicles an hour, shared fairly between the towns on it (merging traffic
takes turns), so a town with L_i vehicles on a road is through it after
sum_j min(L_j, L_i) / capacity. A small town joining a big town's road gets
out early; the big town waits for everything on the road. A town is clear
once it's through every road on its exits. Minor streets inside a town's
own disk don't count, since traffic leaves a town by many streets at once.

What it leaves out: an exit road burning while cars are still on it (the
router already avoids roads likely to burn, and a cut road triggers a
recompute), smoke and darkness slowing traffic, and contraflow.
"""

import dataclasses
import math
from dataclasses import dataclass, field

import numpy as np

from protocol import EvacClock, EvacExit, EvacStatus, TownEvac
from routing.evac import _context, _route_one
from routing.roads import RoadNetwork
from uq.mc import wilson

# Vehicles an hour one way, in evacuation traffic. Studies of real
# evacuations see roughly 1,000-1,300 per lane; minor roads are slower
# because of junctions and parked cars, and motorways and trunks have two lanes.
# Primary roads are often two lanes each way through towns (Skyway was).
CAPACITY_VPH = {
    "motorway": 3600.0,
    "trunk": 2400.0,
    "primary": 1800.0,
    "secondary": 1100.0,
    "tertiary": 900.0,
}
MINOR_VPH = 600.0  # unclassified, residential and anything else
MINOR = {"unclassified", "residential", "road", "living_street", "service"}
# About 2.2 people a household and 1.4 vehicles a household when they leave.
PEOPLE_PER_VEHICLE = 1.6
# From the order to the first cars on the road: getting the word out, then
# the pre-evacuation delay, which drills and surveys put at 10-30 minutes.
MOBILIZE_MIN = 20.0
EXIT_SLACK_MIN = 20.0  # also use exits whose drive is within this of the best one
DETOUR_MIN = 15.0  # how much longer a drive evacuees accept to stay on bigger roads
SAFE_Q = 0.1  # order-by time: 90% of simulations have the last car out first
ORDER_SOON_MIN = 30.0  # "order soon" when the order-by time is this close
LATE_P = 0.5  # past the order-by time, "late" when fewer than this get out first


@dataclass
class Exit:
    safe_zone: str
    share: float  # of the town's vehicles
    bottleneck_vph: float
    drive_min: float
    edges: list[int] = field(repr=False)  # the edges that limit flow


@dataclass
class TownClock:
    town: str
    status: EvacStatus
    ordered_tick: int | None
    people: int  # still in town
    vehicles: int
    mobilize_min: float  # still to go before cars move
    clearance_min: float  # draining the queue once they do; inf with no way out
    last_car_out_tick: int | None  # if ordered now, or as ordered
    order_by_tick: int | None  # latest order that still clears in time (not for ordered towns)
    order_by_bound: bool  # order_by_tick is only a lower bound: the fire isn't seen that far ahead
    fire_tick: int | None  # SAFE_Q-quantile fire arrival; None if under SAFE_Q of rollouts reach it
    reach: int  # rollouts with fire in the town within the forecast
    k_safe: int  # rollouts where the last car gets out first
    n: int
    p_safe_bound: bool  # the last car leaves past the forecast, so k_safe/n is an upper bound
    exits: list[Exit]
    shares_with: list[str]  # other towns loading the same bottleneck
    people_per_min: float  # outflow once cars are moving (for the game layer)

    @property
    def p_safe(self) -> float:
        return self.k_safe / self.n if self.n else 0.0


def capacity(net: RoadNetwork) -> np.ndarray:
    """(E,) vehicles an hour for each edge, from its OSM road class."""
    cap = getattr(net, "_capacity", None)
    if cap is None:
        cap = net._capacity = np.array([CAPACITY_VPH.get(c, MINOR_VPH) for c in net.classes], float)
    return cap


def _local_edges(net: RoadNetwork, town) -> np.ndarray:
    """(E,) bool: minor streets with both ends inside the town's disk."""
    d = np.hypot(net.nodes[:, 0] - town.x, net.nodes[:, 1] - town.y) <= town.radius
    inside = d[net.edges[:, 0]] & d[net.edges[:, 1]]
    minor = np.array([c in MINOR or c not in CAPACITY_VPH for c in net.classes], bool)
    return inside & minor


def town_masks(net: RoadNetwork) -> np.ndarray:
    """(T, H*W) bool: each town's disk on the map grid."""
    masks = getattr(net, "_town_masks", None)
    if masks is None:
        cy, cx = np.mgrid[: net.height, : net.width].astype(np.float32) + 0.5
        masks = np.stack([(np.hypot(cx - t.x, cy - t.y) <= t.radius).ravel() for t in net.towns]) if net.towns \
            else np.zeros((0, net.height * net.width), bool)
        net._town_masks = masks
    return masks


def town_arrivals(first_burn: np.ndarray, masks: np.ndarray, elapsed: float) -> np.ndarray:
    """(n, T) ticks from now until fire first enters each town; inf if not in the forecast."""
    n = first_burn.shape[0]
    fb = first_burn.reshape(n, -1)
    out = np.full((n, masks.shape[0]), np.inf, np.float32)
    for t, m in enumerate(masks):
        if m.any():
            out[:, t] = fb[:, m].min(axis=1)
    return np.maximum(out - elapsed, 0.0)


def exits_for(ctx, net: RoadNetwork, i: int) -> list[Exit]:
    """Every open exit from town i within EXIT_SLACK_MIN of its best, with its
    share of the town's traffic (in proportion to its bottleneck)."""
    town, start = net.towns[i], net.town_node[i]
    cap, local = capacity(net), _local_edges(net, town)
    found = []
    for zi, node in enumerate(net.zone_node):
        r = _arterial_route(dataclasses.replace(ctx, zones={node: zi}), start, town.name, cap, local)
        if r is None:
            continue
        limiting = [e for e in r.edges if not local[e]] or list(r.edges)
        found.append((r, limiting, float(cap[limiting].min())))
    if not found:
        return []
    best = min(r.eta_min for r, _, _ in found)
    found = [f for f in found if f[0].eta_min <= best + EXIT_SLACK_MIN]
    total = sum(b for _, _, b in found)
    return [Exit(r.safe_zone, b / total, b, r.eta_min, edges) for r, edges, b in found]


def _arterial_route(ctx, start: int, name: str, cap: np.ndarray, local: np.ndarray):
    """The route to ctx's one safe zone on the biggest roads that add at most
    DETOUR_MIN to the shortest drive, or None if the zone can't be reached."""
    shortest = _route_one(ctx, start, name)
    if shortest.status == "cut" or not shortest.edges:
        return None
    for level in sorted({c for c in cap if c > cap[shortest.edges].min()}, reverse=True):
        only = dataclasses.replace(ctx, closed=ctx.closed | ((cap < level) & ~local))
        r = _route_one(only, start, name)
        if r.status != "cut" and r.edges and r.eta_min <= shortest.eta_min + DETOUR_MIN:
            return r
    return shortest


def compute_clock(
    net: RoadNetwork,
    first_burn: np.ndarray | None,
    *,
    tick: int,
    forecast_tick: int,
    horizon_min: float,
    orders: dict[str, int],
    evacuated: list[float],
    minutes_per_tick: float,
    closed: np.ndarray | None = None,
) -> list[TownClock]:
    """The clock for every town at sim tick `tick`. `first_burn` is a forecast
    made at `forecast_tick` out to `horizon_min`; `orders` maps an ordered
    town to the tick it was ordered; `evacuated` is people already out, per town."""
    mpt = minutes_per_tick
    elapsed = tick - forecast_tick
    ctx = _context(net, first_burn, elapsed, mpt, horizon_min, closed)
    cap = capacity(net)
    horizon_left = horizon_min / mpt - elapsed  # ticks
    if first_burn is None:
        arrivals, n = np.full((0, len(net.towns)), np.inf, np.float32), 0
    else:
        arrivals, n = town_arrivals(first_burn, town_masks(net), elapsed), first_burn.shape[0]

    exits = [exits_for(ctx, net, i) for i in range(len(net.towns))]
    people = [max(0.0, t.population - e) for t, e in zip(net.towns, evacuated)]
    # Vehicles each town puts on each road, all of them still to leave.
    load = np.zeros((len(net.towns), len(net.edges)))
    for i, ex in enumerate(exits):
        for x in ex:
            load[i, x.edges] += people[i] / PEOPLE_PER_VEHICLE * x.share
    ordered = np.array([t.name in orders and people[i] > 0 for i, t in enumerate(net.towns)], bool)

    out = []
    for i, t in enumerate(net.towns):
        is_ordered = t.name in orders
        # The ordered towns share the roads, plus this one if it's asking "if I order now".
        sharing = ordered.copy()
        sharing[i] = True
        used = sorted({e for x in exits[i] for e in x.edges})
        if used and people[i] > 0:
            mine = load[i, used]
            hours = np.minimum(load[sharing][:, used], mine).sum(axis=0) / cap[used]
            worst = used[int(np.argmax(hours))]
            clearance = float(hours.max()) * 60
            shares = [o.name for j, o in enumerate(net.towns) if j != i and ordered[j] and load[j, worst] > 0]
            flow = people[i] / clearance if clearance > 0 else 0.0
        else:
            clearance, shares, flow = (0.0 if people[i] <= 0 else math.inf), [], 0.0
        if is_ordered:
            mobilize = max(0.0, MOBILIZE_MIN - (tick - orders[t.name]) * mpt)
        else:
            mobilize = MOBILIZE_MIN
        need = (mobilize + clearance) / mpt  # ticks until the last car is out

        a = arrivals[:, i] if n else np.zeros(0, np.float32)
        reach = int((a <= horizon_left).sum()) if n else 0
        srt = np.sort(a) if n else a
        q = float(srt[int(math.floor(SAFE_Q * n))]) if n else math.inf
        fire_tick = tick + round(q) if math.isfinite(q) and q <= horizon_left else None
        k_safe = int((a > need).sum()) if math.isfinite(need) else 0
        bound = math.isfinite(need) and need > horizon_left and n > 0

        order_by, order_by_bound = None, False
        if not is_ordered and math.isfinite(need) and n:
            if fire_tick is not None:
                order_by = round(tick + q - need)
            else:
                order_by, order_by_bound = round(tick + horizon_left - need), True

        out.append(TownClock(
            town=t.name,
            status=_status(is_ordered, people[i], exits[i], order_by, order_by_bound, tick, mpt, reach,
                           k_safe, n, bound),
            ordered_tick=orders.get(t.name),
            people=round(people[i]),
            vehicles=round(people[i] / PEOPLE_PER_VEHICLE),
            mobilize_min=round(mobilize, 1),
            clearance_min=round(clearance, 1) if math.isfinite(clearance) else math.inf,
            last_car_out_tick=tick + round(need) if math.isfinite(need) else None,
            order_by_tick=order_by,
            order_by_bound=order_by_bound,
            fire_tick=fire_tick,
            reach=reach,
            k_safe=k_safe,
            n=n,
            p_safe_bound=bound,
            exits=exits[i],
            shares_with=shares,
            people_per_min=round(flow, 2),
        ))
    return out


def _status(ordered, people, exits, order_by, bound, tick, mpt, reach, k_safe, n, p_bound) -> EvacStatus:
    if people <= 0:
        return EvacStatus.CLEAR
    if not exits:
        return EvacStatus.TRAPPED
    if ordered:
        return EvacStatus.EVACUATING
    if order_by is None:
        return EvacStatus.WATCH  # no forecast yet
    left = (order_by - tick) * mpt
    if bound:
        # The town takes longer to empty than the forecast looks ahead. Say
        # so if any simulation has the fire there within it; otherwise watch.
        return EvacStatus.ORDER_SOON if reach and left <= ORDER_SOON_MIN else EvacStatus.WATCH
    if left <= 0:
        # k_safe is an upper bound when p_bound, so under LATE_P is late either way.
        return EvacStatus.LATE if k_safe < LATE_P * n else EvacStatus.ORDER_NOW
    return EvacStatus.ORDER_SOON if left <= ORDER_SOON_MIN else EvacStatus.WATCH


def clock_message(clocks: list[TownClock], tick: int, forecast_tick: int | None, horizon_min: float) -> EvacClock:
    """The `evac_clock` message: most urgent town first."""
    rows = []
    for c in clocks:
        lo, hi = wilson(c.k_safe, c.n) if c.n else (0.0, 0.0)
        rows.append(TownEvac(
            town=c.town,
            status=c.status,
            ordered_tick=c.ordered_tick,
            people=c.people,
            vehicles=c.vehicles,
            mobilize_min=float(c.mobilize_min),
            clearance_min=float(c.clearance_min) if math.isfinite(c.clearance_min) else None,
            last_car_out_tick=c.last_car_out_tick,
            order_by_tick=c.order_by_tick,
            order_by_bound=c.order_by_bound,
            fire_tick=c.fire_tick,
            reach=c.reach,
            n=c.n,
            p_safe=round(c.p_safe, 3),
            p_safe_lo=round(float(lo), 3),
            p_safe_hi=round(float(hi), 3),
            p_safe_bound=c.p_safe_bound,
            exits=[EvacExit(safe_zone=x.safe_zone, share=round(x.share, 3), bottleneck_vph=x.bottleneck_vph,
                            drive_min=float(x.drive_min)) for x in c.exits],
            shares_with=c.shares_with,
        ))
    rank = {s: k for k, s in enumerate([EvacStatus.LATE, EvacStatus.TRAPPED, EvacStatus.ORDER_NOW,
                                        EvacStatus.ORDER_SOON, EvacStatus.EVACUATING, EvacStatus.WATCH,
                                        EvacStatus.CLEAR])}
    rows.sort(key=lambda r: (rank[r.status], r.order_by_tick if r.order_by_tick is not None else math.inf,
                             -r.people))
    return EvacClock(tick=tick, forecast_tick=forecast_tick, horizon_min=horizon_min, towns=rows)
