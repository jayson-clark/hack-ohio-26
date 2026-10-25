// How dispatch (#104, engine side in #106) reads in the console (#109): a unit's
// status as a label and colour, and what an order token is waiting for.

import type { Recommendation, Token, UnitInfo, UnitStatus } from "./protocol";
import { formatSimMinutes } from "./round";
import { ORDER_STYLE } from "./tokens";

export const UNIT_STATUS: Record<UnitStatus, { label: string; color: string }> = {
  available: { label: "Available", color: "#9aa1ab" },
  en_route: { label: "En route", color: "#facc15" },
  working: { label: "On scene", color: "#4ade80" },
  blocked: { label: "No road in", color: "#f87171" },
  grounded: { label: "Grounded", color: "#38bdf8" },
  reloading: { label: "Reloading", color: "#38bdf8" },
  resting: { label: "Resting", color: "#9aa1ab" },
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
      // A crew past its shift fades until relieved (#178).
      // `fatigue` runs 0 (end of shift) to 1 (faded to the engine's floor), so
      // say how far through the fade it is rather than guess the floor here.
      return u.fatigue > 0 ? `on scene, tiring (${Math.round(u.fatigue * 100)}% faded)` : "on scene";
    case "reloading":
      return u.ready_in_min != null ? `refilling at base, out again in ${formatSimMinutes(u.ready_in_min)}` : "refilling at base";
    case "resting":
      return u.ready_in_min != null ? `resting, free in ${formatSimMinutes(u.ready_in_min)}` : "resting";
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

/** How a recommendation card names its action: place, move or relieve (#178). */
export function recVerb(r: Recommendation): string {
  return r.action === "move" ? "Move a crew" : r.action === "relieve" ? "Relieve the crew" : ORDER_STYLE[r.token_type].verb;
}

/** The card's button label for the same action. */
export function recButton(r: Recommendation): string {
  return r.action === "move" ? "Move crew" : r.action === "relieve" ? "Relieve crew" : "Dispatch";
}
