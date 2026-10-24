import type { TokenType } from "./protocol";

export const TOKEN_TYPES: TokenType[] = ["crew", "firebreak", "water", "bus"];

export const TOKEN_STYLE: Record<TokenType, { label: string; letter: string; color: string }> = {
  crew: { label: "Fire crew", letter: "C", color: "#facc15" },
  firebreak: { label: "Firebreak", letter: "F", color: "#fb923c" },
  water: { label: "Water drop", letter: "W", color: "#38bdf8" },
  bus: { label: "Evac bus", letter: "B", color: "#4ade80" },
};
