import type { TokenType } from "./protocol";

export const TOKEN_TYPES: TokenType[] = ["crew", "firebreak", "water", "bus"];

export const TOKEN_STYLE: Record<TokenType, { label: string; letter: string; color: string; hint: string }> = {
  crew: { label: "Fire crew", letter: "C", color: "#facc15", hint: "Suppresses fire nearby over time" },
  firebreak: { label: "Firebreak", letter: "F", color: "#fb923c", hint: "Removes fuel along a line" },
  water: { label: "Water drop", letter: "W", color: "#38bdf8", hint: "Instant knockdown, then cooldown" },
  bus: { label: "Evac bus", letter: "B", color: "#4ade80", hint: "Drives the route, picks up residents" },
};

// Sizes in map cells (1 cell is about 1.3 mm on the Paradise print). The puck
// is the physical token; the halo is the white disc projected under it so its
// marker stays readable under fire light.
export const TOKEN_RADIUS = 6;
export const HALO_RADIUS = 9;
