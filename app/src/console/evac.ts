// Wording for the evacuation order clock (#121), shared by the decision queue
// and the town board: when each town has to be ordered out, from a long fire
// forecast against the time to empty it through exits shared with other towns.

import type { EvacStatus, TownEvac } from "../shared/protocol";
import { formatSimMinutes } from "../shared/round";

export const EVAC_COLOR: Record<EvacStatus, string> = {
  late: "#f87171",
  trapped: "#f87171",
  order_now: "#fb923c",
  order_soon: "#fbbf24",
  evacuating: "#38bdf8",
  watch: "#8b929c",
  clear: "#34d399",
};

/** Sim minutes until the latest safe order time (negative once it's passed). */
export function orderByLeft(t: TownEvac, now: number, mpt: number): number | null {
  return t.order_by_tick === null ? null : (t.order_by_tick - now) * mpt;
}

/** The one line that says what to do and by when. */
export function evacHeadline(t: TownEvac, now: number, mpt: number): string {
  switch (t.status) {
    case "clear":
      return "Everyone is out.";
    case "trapped":
      return "No open way out. Shelter in place or at a refuge.";
    case "evacuating": {
      const out = t.last_car_out_tick === null ? null : (t.last_car_out_tick - now) * mpt;
      return `${t.people.toLocaleString()} still in town${out !== null ? `, last car out in about ${formatSimMinutes(out)}` : ""}.`;
    }
  }
  const left = orderByLeft(t, now, mpt);
  if (left === null) return "Waiting for the long forecast.";
  if (t.order_by_bound) return `Order within ${formatSimMinutes(Math.max(0, left))} or more (fire not yet in the forecast).`;
  if (left > 0) return `Order within ${formatSimMinutes(left)}.`;
  return `${formatSimMinutes(-left)} past the latest safe order time.`;
}

/** "12,000 people need about 7h 50m to get out via Chico and Oroville." */
export function evacNeed(t: TownEvac): string | null {
  if (t.clearance_min === null || t.people === 0) return null;
  const via = t.exits.length > 0 ? ` via ${t.exits.map((x) => x.safe_zone).join(" and ")}` : "";
  return `${t.people.toLocaleString()} people need about ${formatSimMinutes(t.mobilize_min + t.clearance_min)} to get out${via}.`;
}

/** In how many simulations the last car beats the fire. */
export function evacSafe(t: TownEvac): string | null {
  if (t.n === 0 || t.people === 0 || t.status === "trapped") return null;
  const k = Math.round(t.p_safe * t.n);
  const lead = t.ordered_tick === null ? "If ordered now, the last car gets out" : "The last car gets out";
  return `${lead} ahead of the fire in ${t.p_safe_bound ? "at most " : ""}${k} of ${t.n} simulations.`;
}

/** A few words for the town board: "Order in 4h 10m", "Evacuating". */
export function evacShort(t: TownEvac, now: number, mpt: number): string | null {
  switch (t.status) {
    case "clear":
      return "All out";
    case "trapped":
      return "Trapped";
    case "evacuating":
      return "Evacuating";
    case "late":
      return "Order late";
    case "order_now":
      return "Order now";
  }
  const left = orderByLeft(t, now, mpt);
  if (left === null) return null;
  return `Order in ${formatSimMinutes(Math.max(0, left))}${t.order_by_bound ? "+" : ""}`;
}
