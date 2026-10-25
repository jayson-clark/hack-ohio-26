// How the console reads the engine (#130): every town joined from the town
// board (situation) and the evacuation clock (#121), with one risk tone and
// one status line, so the map, sidebar and inspector all agree.

import { useEngine } from "../shared/engine";
import type { EvacStatus, TokenType, TownEvac, TownThreat } from "../shared/protocol";
import { aboutMinutes } from "../shared/places";
import type { Scenario, Town } from "../shared/scenario";
import type { Tone } from "./ui";

/** Order colors on the console map (the projector keeps TOKEN_STYLE's). */
export const ORDER_COLOR: Record<TokenType, string> = {
  crew: "#1f4fd6",
  firebreak: "#9a5b13",
  water: "#0e9384",
  bus: "#6941c6",
};

export const ORDER_ICON: Record<TokenType, "crew" | "dozer" | "air" | "bus"> = {
  crew: "crew",
  firebreak: "dozer",
  water: "air",
  bus: "bus",
};

export const EVAC: Record<EvacStatus, { label: string; tone: Tone }> = {
  late: { label: "Order overdue", tone: "crit" },
  trapped: { label: "No way out", tone: "crit" },
  order_now: { label: "Order now", tone: "crit" },
  order_soon: { label: "Order soon", tone: "warn" },
  evacuating: { label: "Evacuating", tone: "info" },
  watch: { label: "Monitoring", tone: "neutral" },
  clear: { label: "Evacuated", tone: "ok" },
};

export interface TownView extends Town {
  threat: TownThreat | null;
  evac: TownEvac | null;
  tone: Tone;
  /** Short status for a badge. */
  status: string;
  /** "Fire in ~25 min", "Fire in town", or null when no threat in the forecast. */
  eta: string | null;
  /** Lower sorts first: how urgent this town is. */
  rank: number;
}

const SHARE_WARN = 0.25;

export function townView(t: Town, threat: TownThreat | null, evac: TownEvac | null): TownView {
  const share = threat?.within_60 ? threat.within_60.k / Math.max(1, threat.within_60.n) : 0;
  const soon = threat?.soonest_min ?? null;
  let tone: Tone = "neutral";
  let status = threat?.within_60 ? "No threat within 1 h" : "No forecast yet";
  if (evac) {
    tone = EVAC[evac.status].tone;
    status = EVAC[evac.status].label;
  }
  if (threat?.fire_inside) {
    tone = evac?.status === "clear" ? "ok" : "crit";
    if (!evac || evac.status === "watch") status = "Fire in town";
  } else if (!evac || evac.status === "watch") {
    if (soon !== null && soon <= 30) [tone, status] = ["crit", "Threatened"];
    else if ((soon !== null && soon <= 60) || share >= SHARE_WARN) [tone, status] = ["warn", "Threatened"];
  }
  const eta = threat?.fire_inside ? "Fire in town" : soon !== null ? `Fire in ~${aboutMinutes(soon)}` : null;
  const toneRank = { crit: 0, warn: 1, info: 2, ok: 4, neutral: 3 }[tone];
  return { ...t, threat, evac, tone, status, eta, rank: toneRank * 1e4 + (threat?.fire_inside ? 0 : (soon ?? 9999)) };
}

/** Every town, most urgent first. */
export function useTowns(scenario: Scenario | null): TownView[] {
  const { situation, evacClock } = useEngine();
  if (!scenario) return [];
  const threats = new Map((situation?.towns ?? []).map((t) => [t.town, t]));
  const evac = new Map((evacClock?.towns ?? []).map((t) => [t.town, t]));
  return scenario.towns
    .map((t) => townView(t, threats.get(t.name) ?? null, evac.get(t.name) ?? null))
    .sort((a, b) => a.rank - b.rank);
}

// What's selected on the map or in a list; the inspector shows it. A recommendation keeps where it was: the engine re-ranks every few seconds
// with new ids, and the inspector follows the nearest one.
export type Selection =
  | { kind: "town"; name: string }
  | { kind: "rec"; id: string; x: number; y: number }
  | { kind: "order"; id: string }
  | null;

/** The selected recommendation, or the nearest current one to where it was. */
export function findRec<R extends { id: string; x: number; y: number }>(recs: R[], sel: { id: string; x: number; y: number }): R | undefined {
  const exact = recs.find((r) => r.id === sel.id);
  if (exact) return exact;
  const near = recs.reduce<R | undefined>((a, r) => (!a || Math.hypot(r.x - sel.x, r.y - sel.y) < Math.hypot(a.x - sel.x, a.y - sel.y) ? r : a), undefined);
  return near && Math.hypot(near.x - sel.x, near.y - sel.y) < 12 ? near : undefined;
}

/** Minutes until a sim tick, from the fire's own clock. */
export function minutesUntil(tick: number | null, now: number, perTick: number): number | null {
  return tick === null ? null : (tick - now) * perTick;
}
