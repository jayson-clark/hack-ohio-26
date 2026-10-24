// Plan mode's draft orders (#123): kept in the console until they're
// dispatched or cleared, so switching modes doesn't lose them.

import type { PlanOrderResult, PlanResult, TokenType } from "../shared/protocol";

export interface DraftOrder {
  id: string;
  token_type: TokenType;
  x: number;
  y: number;
}

/** Order types a plan can try. Buses evacuate rather than fight fire, so they aren't simulated. */
export const PLAN_TYPES: TokenType[] = ["crew", "firebreak", "water"];

let next = 0;
export function newDraft(token_type: TokenType, x: number, y: number): DraftOrder {
  return { id: `d${++next}`, token_type, x, y };
}

/** The result's orders, if they're for exactly these drafts (same order, same spots). */
export function resultsFor(drafts: DraftOrder[], result: PlanResult | null): PlanOrderResult[] | null {
  if (!result || result.orders.length !== drafts.length) return null;
  const same = drafts.every(
    (d, i) =>
      d.token_type === result.orders[i].token_type &&
      Math.abs(d.x - result.orders[i].x) < 0.5 &&
      Math.abs(d.y - result.orders[i].y) < 0.5,
  );
  return same ? result.orders : null;
}
