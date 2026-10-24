// How each engine event kind (EventKind in engine/protocol.py) reads in the
// console: a short label, a colour, and whether it's urgent enough to pop up.

import type { Event, EventKind } from "./protocol";

export const EVENT_STYLE: Record<EventKind, { label: string; color: string; alert: boolean }> = {
  town_threatened: { label: "Threatened", color: "#fb923c", alert: true },
  no_safe_route: { label: "No way out", color: "#ef4444", alert: true },
  road_cut: { label: "Road cut", color: "#f87171", alert: true },
  route_changed: { label: "Reroute", color: "#facc15", alert: false },
  forecast_shift: { label: "Forecast", color: "#38bdf8", alert: false },
  town_safe: { label: "Safe", color: "#4ade80", alert: false },
};

/** Towns under threat now: the last threatened/safe event per town decides. */
export function threatenedTowns(events: Event[]): string[] {
  const state = new Map<string, boolean>();
  for (const e of events) {
    if (!e.town) continue;
    if (e.kind === "town_threatened") state.set(e.town, true);
    if (e.kind === "town_safe") state.set(e.town, false);
  }
  return [...state].filter(([, on]) => on).map(([town]) => town).sort();
}
