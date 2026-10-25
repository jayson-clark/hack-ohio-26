// The four numbers at the top of Monitor (#130): how big the fire is and how
// fast it's growing, towns at risk, evacuation routes, and units committed.

import { useEffect, useRef, useState } from "react";
import { useEngine } from "../shared/engine";
import type { TownView } from "./model";
import { Stat } from "./ui";

const GROWTH_WINDOW_MIN = 60;

/** Acres per hour over the last sim hour, from the score's acres burned. */
function useGrowth(): number | null {
  const { score, hello } = useEngine();
  const history = useRef<{ tick: number; acres: number }[]>([]);
  const [rate, setRate] = useState<number | null>(null);
  const perTick = hello?.sim_minutes_per_tick ?? 1;
  useEffect(() => {
    if (!score) return;
    const h = history.current;
    // A reset or scenario switch sends the clock backwards: start over.
    if (h.length && score.tick < h[h.length - 1].tick) h.length = 0;
    h.push({ tick: score.tick, acres: score.acres_burned });
    while (h.length > 2 && (score.tick - h[1].tick) * perTick >= GROWTH_WINDOW_MIN) h.shift();
    const first = h[0];
    const minutes = (score.tick - first.tick) * perTick;
    setRate(minutes >= 5 ? ((score.acres_burned - first.acres) * 60) / minutes : null);
  }, [score, perTick]);
  return rate;
}

export default function Situation({ towns }: { towns: TownView[] }) {
  const { score, units, routes, simGrid } = useEngine();
  const growth = useGrowth();
  const burning = !!simGrid && simGrid.payload.includes(2);
  const atRisk = towns.filter((t) => t.tone === "crit" || t.tone === "warn");
  const due = towns.filter((t) => t.evac && t.evac.ordered_tick === null && ["late", "order_now", "order_soon"].includes(t.evac.status)).length;
  const townRoutes = routes.filter((r) => !r.bus);
  const cut = townRoutes.filter((r) => r.status === "cut").length;
  const risky = townRoutes.filter((r) => r.status === "risky").length;
  const out = units.filter((u) => u.status !== "available");

  return (
    <div className="grid grid-cols-2 gap-2 px-4 pt-4">
      <Stat
        label="Fire size"
        value={score ? `${Math.round(score.acres_burned).toLocaleString()} ac` : "—"}
        sub={!burning ? "No active fire" : growth !== null ? `+${Math.round(growth).toLocaleString()} ac per hour` : "Measuring growth…"}
        tone={burning ? "crit" : undefined}
      />
      <Stat
        label="Towns at risk"
        value={`${atRisk.length} of ${towns.length}`}
        sub={due ? `${due} evacuation order${due > 1 ? "s" : ""} due` : "No orders due"}
        tone={atRisk.some((t) => t.tone === "crit") ? "crit" : atRisk.length ? "warn" : undefined}
      />
      <Stat
        label="Evacuation routes"
        value={cut ? `${cut} cut` : risky ? `${risky} at risk` : "All clear"}
        sub={cut && risky ? `${risky} more at risk` : `${townRoutes.length} towns routed`}
        tone={cut ? "crit" : risky ? "warn" : "ok"}
      />
      <Stat
        label="Units committed"
        value={`${out.length} of ${units.length}`}
        sub={`${units.filter((u) => u.status === "en_route").length} en route`}
      />
    </div>
  );
}
