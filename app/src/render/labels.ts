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

  for (const place of s.info.places) {
    const [x, y] = place.map;
    const origin = /origin/i.test(place.name);

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
      ctx.arc(x, y, 2.6, 0, Math.PI * 2);
      ctx.fillStyle = "rgba(10, 12, 16, 0.85)";
      ctx.fill();
      ctx.beginPath();
      ctx.arc(x, y, 1.9, 0, Math.PI * 2);
      ctx.strokeStyle = "rgba(255, 255, 255, 0.95)";
      ctx.lineWidth = 0.55;
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(x, y, 0.8, 0, Math.PI * 2);
      ctx.fillStyle = "white";
      ctx.fill();
    }

    const text = origin ? place.name.toUpperCase() : place.name;
    ctx.font = origin ? "600 2.6px system-ui, sans-serif" : "650 4px system-ui, sans-serif";
    ctx.textBaseline = "middle";
    // Keep labels on the board: flip to the left near the east edge.
    const right = x < s.width - 28;
    ctx.textAlign = right ? "left" : "right";
    const tx = x + (right ? 4 : -4);
    ctx.strokeStyle = "rgba(8, 10, 14, 0.85)";
    ctx.lineWidth = 1.1;
    ctx.strokeText(text, tx, y);
    ctx.fillStyle = origin ? "rgba(255, 170, 120, 1)" : "rgba(255, 255, 255, 1)";
    ctx.fillText(text, tx, y);
  }
  return canvas;
}
