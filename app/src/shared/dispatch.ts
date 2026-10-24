// How dispatch (#104, engine side in #106) reads in the console (#109): a unit's
// status as a label and colour, and what an order token is waiting for.

import type { Token, UnitInfo, UnitStatus } from "./protocol";
import { formatSimMinutes } from "./round";

export const UNIT_STATUS: Record<UnitStatus, { label: string; color: string }> = {
  available: { label: "Available", color: "#9aa1ab" },
  en_route: { label: "En route", color: "#facc15" },
  working: { label: "On scene", color: "#4ade80" },
  blocked: { label: "No road in", color: "#f87171" },
  grounded: { label: "Grounded", color: "#38bdf8" },
};

/** The unit serving an order token, if dispatch is on and one is assigned. */
export function unitFor(token: Token, units: UnitInfo[]): UnitInfo | undefined {
  return units.find((u) => u.token_id === token.id);
}

/** One line for what an order is waiting on, e.g. "crew arrives in 12m". */
export function orderText(u: UnitInfo): string {
  switch (u.status) {
    case "en_route":
      return u.eta_min != null ? `arrives in ${formatSimMinutes(u.eta_min)}` : "en route";
    case "working":
      return "on scene";
    case "blocked":
      return "no open road in, retrying";
    case "grounded":
      // The engine's limit is routing/units.py TANKER_MAX_WIND_MS; it isn't on
      // the wire, so say what it means rather than repeat the number here.
      return "grounded by wind, flies when it drops";
    default:
      return "waiting for a unit";
  }
}
