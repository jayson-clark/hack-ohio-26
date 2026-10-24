// Plain-language locations for the operator ("2.1 km SW of Paradise"), from
// the scenario's towns and named places.

import type { Scenario } from "./scenario";

const COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];

/** Compass point for a wind direction or bearing in degrees (0 = north). */
export function compass(deg: number): string {
  return COMPASS[Math.round((((deg % 360) + 360) % 360) / 45) % 8];
}

/** Nearest town or place to a map point, and where the point lies from it. */
export function describeLocation(s: Scenario, x: number, y: number): string {
  const named = [
    ...s.towns.map((t) => ({ name: t.name, x: t.x, y: t.y, r: t.radius })),
    ...s.info.places.filter((p) => !/origin/i.test(p.name)).map((p) => ({ name: p.name, x: p.map[0], y: p.map[1], r: 0 })),
  ];
  if (named.length === 0) return `${x.toFixed(0)}, ${y.toFixed(0)}`;
  const near = named.reduce((a, b) => (Math.hypot(b.x - x, b.y - y) < Math.hypot(a.x - x, a.y - y) ? b : a));
  const cells = Math.hypot(near.x - x, near.y - y);
  if (cells <= Math.max(near.r, 3)) return `in ${near.name}`;
  const km = (cells * s.info.grid.cell_size_m) / 1000;
  // Map y runs south, so north is -y.
  const bearing = (Math.atan2(x - near.x, near.y - y) * 180) / Math.PI;
  return `${km < 10 ? km.toFixed(1) : km.toFixed(0)} km ${compass(bearing)} of ${near.name}`;
}

/** Minutes as "~25 min" or "~1h 40m", for times that are estimates. */
export function aboutMinutes(min: number): string {
  const m = Math.max(0, Math.round(min));
  if (m < 60) return `${m} min`;
  return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m`;
}
