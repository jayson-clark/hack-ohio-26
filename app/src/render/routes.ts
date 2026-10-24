// Evacuation routes, redrawn whenever the engine sends a `routes` message.
// Like labels.ts, it's a canvas in map coordinates that the projection shader
// samples, so routes drape over the terrain and land on the physical roads.

import type { RouteInfo, RouteStatus } from "../shared/protocol";
import type { Scenario } from "../shared/scenario";

const PX_PER_CELL = 8;

export const ROUTE_COLORS: Record<RouteStatus, string> = {
  clear: "#4ade80",
  risky: "#facc15",
  cut: "#ef4444",
};

export function createRoutesCanvas(s: Scenario): HTMLCanvasElement {
  const canvas = document.createElement("canvas");
  canvas.width = s.width * PX_PER_CELL;
  canvas.height = s.height * PX_PER_CELL;
  return canvas;
}

export function drawRoutes(canvas: HTMLCanvasElement, s: Scenario, routes: RouteInfo[]) {
  const ctx = canvas.getContext("2d")!;
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.scale(PX_PER_CELL, PX_PER_CELL);
  ctx.lineJoin = "round";
  ctx.lineCap = "round";

  // Dark casing first for every route, then the colored lines, so where
  // routes share a road the colors stay readable.
  for (const pass of ["casing", "line"] as const) {
    for (const r of routes) {
      if (r.points.length < 2) continue;
      ctx.beginPath();
      ctx.moveTo(r.points[0][0], r.points[0][1]);
      for (const [x, y] of r.points.slice(1)) ctx.lineTo(x, y);
      if (pass === "casing") {
        ctx.strokeStyle = "rgba(8, 10, 14, 0.8)";
        ctx.lineWidth = 2.2;
      } else {
        ctx.strokeStyle = ROUTE_COLORS[r.status];
        ctx.lineWidth = 1.1;
      }
      // A bus's own route is dashed, so it reads apart from the town routes.
      ctx.setLineDash(r.bus && pass === "line" ? [2, 1.4] : []);
      ctx.stroke();
    }
  }

  // Exits: a small arrowhead at the end of each route, plus the safe zone's name once.
  const named = new Set<string>();
  for (const r of routes) {
    if (r.points.length < 2 || !r.safe_zone) continue;
    const [x, y] = r.points[r.points.length - 1];
    const [px, py] = r.points[r.points.length - 2];
    const a = Math.atan2(y - py, x - px);
    ctx.save();
    ctx.translate(x, y);
    ctx.rotate(a);
    ctx.beginPath();
    ctx.moveTo(1.8, 0);
    ctx.lineTo(-1.6, -1.6);
    ctx.lineTo(-1.6, 1.6);
    ctx.closePath();
    ctx.fillStyle = ROUTE_COLORS[r.status];
    ctx.strokeStyle = "rgba(8, 10, 14, 0.85)";
    ctx.lineWidth = 0.5;
    ctx.fill();
    ctx.stroke();
    ctx.restore();

    if (named.has(r.safe_zone)) continue;
    named.add(r.safe_zone);
    ctx.font = "600 3px system-ui, sans-serif";
    ctx.textBaseline = "middle";
    // Exits sit at the map edge, so pull the label inward.
    const right = x < s.width / 2;
    ctx.textAlign = right ? "left" : "right";
    const tx = x + (right ? 3 : -3);
    const ty = Math.min(Math.max(y, 3), s.height - 3);
    ctx.strokeStyle = "rgba(8, 10, 14, 0.85)";
    ctx.lineWidth = 1;
    ctx.strokeText(r.safe_zone, tx, ty);
    ctx.fillStyle = "rgba(220, 255, 230, 1)";
    ctx.fillText(r.safe_zone, tx, ty);
  }

  // A town with no way out gets a red ring.
  for (const r of routes) {
    if (r.status !== "cut") continue;
    const place = s.info.places.find((p) => p.name === r.town);
    if (!place) continue;
    ctx.beginPath();
    ctx.arc(place.map[0], place.map[1], 4.2, 0, Math.PI * 2);
    ctx.strokeStyle = ROUTE_COLORS.cut;
    ctx.lineWidth = 0.9;
    ctx.stroke();
  }
}
