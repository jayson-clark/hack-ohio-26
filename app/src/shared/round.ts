// Formatting for the game layer's `score` message (engine/sim/game.py), shared
// by the console's round panel and the end-of-round summaries.

import type { EndReason, Score, TokenType } from "./protocol";

/** Sim minutes as "4h 05m" or "38m". */
export function formatSimMinutes(min: number): string {
  const m = Math.max(0, Math.round(min));
  const h = Math.floor(m / 60);
  return h ? `${h}h ${String(m % 60).padStart(2, "0")}m` : `${m}m`;
}

export const END_REASON_TEXT: Record<EndReason, string> = {
  time: "Time's up",
  contained: "Fire contained",
  stopped: "Exercise ended",
};

export function pct(part: number, whole: number): number {
  return whole > 0 ? Math.round((100 * part) / whole) : 0;
}

/** The headline numbers, in the order every summary shows them. */
export function headline(score: Score) {
  const saved = score.structures_total - score.structures_lost;
  return [
    {
      label: "People evacuated",
      short: "Evacuated",
      value: score.people_evacuated.toLocaleString(),
      of: `of ${score.people_total.toLocaleString()}`,
      pct: pct(score.people_evacuated, score.people_total),
    },
    {
      label: "Structures saved",
      short: "Homes saved",
      value: saved.toLocaleString(),
      of: `of ${score.structures_total.toLocaleString()}`,
      pct: pct(saved, score.structures_total),
    },
    { label: "Acres burned", short: "Acres burned", value: Math.round(score.acres_burned).toLocaleString(), of: "", pct: null },
  ];
}

/** Limit for a token type in the current phase, or null when unlimited. */
export function limitFor(score: Score | null, type: TokenType): number | null {
  return score?.resources.find((r) => r.token_type === type)?.limit ?? null;
}
