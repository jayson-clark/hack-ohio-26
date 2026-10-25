// Static overlay drawn once per scenario: town markers and names. Rendered to a
// canvas in map coordinates and sampled by the projection shader, so labels
// drape over the terrain in the virtual table exactly as projected.

import type { Scenario } from "../shared/scenario";

const PX_PER_CELL = 8;

export function drawLabels(s: Scenario): HTMLCanvasElement {
  const canvas = document.createElement("canvas");
  canvas.width = s.width * PX_PER_CELL;
  canvas.height = s.height * PX_PER_CELL;
  const ctx = canvas.getContext("2d")!;
  ctx.scale(PX_PER_CELL, PX_PER_CELL);
  ctx.lineJoin = "round";

  // Towns from towns.json, each with a faint ring for the area the score
  // counts as the town and a marker sized by population, so Paradise reads as
  // bigger than Pulga. terrain.json's places are only a few points; the
  // ignition point still comes from there.
  for (const t of s.towns) {
    ctx.beginPath();
    ctx.arc(t.x, t.y, t.radius, 0, Math.PI * 2);
    ctx.strokeStyle = "rgba(255, 255, 255, 0.28)";
    ctx.lineWidth = 0.35;
    ctx.setLineDash([1.2, 1]);
    ctx.stroke();
    ctx.setLineDash([]);
  }
  const marks: { name: string; x: number; y: number; r: number; origin: boolean }[] = [
    ...s.towns.map((t) => ({ name: t.name, x: t.x, y: t.y, r: townMarkerRadius(t.population), origin: false })),
    ...s.info.places
      .filter((p) => /origin/i.test(p.name) || !s.towns.some((t) => t.name === p.name))
      .map((p) => ({ name: p.name, x: p.map[0], y: p.map[1], r: 1.9, origin: /origin/i.test(p.name) })),
  ];

  for (const { name, x, y, r, origin } of marks) {
    if (origin) {
      // Ignition point: a small cross.
      ctx.strokeStyle = "rgba(255, 120, 60, 0.95)";
      ctx.lineWidth = 0.7;
      ctx.beginPath();
      ctx.moveTo(x - 2, y - 2);
      ctx.lineTo(x + 2, y + 2);
      ctx.moveTo(x + 2, y - 2);
      ctx.lineTo(x - 2, y + 2);
      ctx.stroke();
    } else {
      ctx.beginPath();
      ctx.arc(x, y, r + 0.7, 0, Math.PI * 2);
      ctx.fillStyle = "rgba(10, 12, 16, 0.85)";
      ctx.fill();
      ctx.beginPath();
      ctx.arc(x, y, r, 0, Math.PI * 2);
      ctx.strokeStyle = "rgba(255, 255, 255, 0.95)";
      ctx.lineWidth = 0.55;
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(x, y, Math.max(0.8, r * 0.42), 0, Math.PI * 2);
      ctx.fillStyle = "white";
      ctx.fill();
    }

    const text = origin ? name.toUpperCase() : name;
    ctx.font = origin ? "600 2.6px system-ui, sans-serif" : "650 4px system-ui, sans-serif";
    ctx.textBaseline = "middle";
    // Keep labels on the board: flip to the left near the east edge.
    const right = x < s.width - 28;
    ctx.textAlign = right ? "left" : "right";
    const tx = x + (right ? r + 2.1 : -(r + 2.1));
    ctx.strokeStyle = "rgba(8, 10, 14, 0.85)";
    ctx.lineWidth = 1.1;
    ctx.strokeText(text, tx, y);
    ctx.fillStyle = origin ? "rgba(255, 170, 120, 1)" : "rgba(255, 255, 255, 1)";
    ctx.fillText(text, tx, y);
  }
  return canvas;
}

/** Marker radius in cells: area grows with population, from Pulga (50) at
 * about the old fixed size up to Paradise (26,800) at about twice it. */
export function townMarkerRadius(population: number): number {
  return 1.6 + 0.35 * Math.log10(Math.max(population, 10)) ** 1.5;
}
