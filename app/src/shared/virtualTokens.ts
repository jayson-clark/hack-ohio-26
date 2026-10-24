// Virtual table mode actions, shared by every view that lets you place tokens.
// They go through the same engine path real vision uses. Placing "ignite"
// lights the fire at that spot instead of adding a token.

import { send } from "./engine";
import type { TokenType } from "./protocol";

export type PlaceType = TokenType | "ignite";

export interface MapSize {
  width: number;
  height: number;
}

const clamp = (v: number, max: number) => Math.min(Math.max(v, 0), max);

export function addToken(type: TokenType, x: number, y: number, map: MapSize) {
  send({ type: "virtual_token_add", token_type: type, x: clamp(x, map.width), y: clamp(y, map.height), angle: 0 });
}

export function place(type: PlaceType, x: number, y: number, map: MapSize) {
  if (type === "ignite") send({ type: "ignite", x: clamp(x, map.width), y: clamp(y, map.height) });
  else addToken(type, x, y, map);
}

export function removeToken(id: string) {
  send({ type: "virtual_token_remove", id });
}

/** Returns a move function that sends at most one message per animation frame. */
export function createMover(map: MapSize) {
  let pending: { id: string; x: number; y: number } | null = null;
  const flush = () => {
    if (pending) send({ type: "virtual_token_move", ...pending, angle: null });
    pending = null;
  };
  return (id: string, x: number, y: number) => {
    if (!pending) requestAnimationFrame(flush);
    pending = { id, x: clamp(x, map.width), y: clamp(y, map.height) };
  };
}
