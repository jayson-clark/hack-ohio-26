// Every town in one list (#130): its status (from the evacuation clock when
// there is one), how soon fire could get there, how likely within the hour,
// its way out, and when its evacuation order is due (#121). Most urgent
// first; a row opens the town in the inspector.

import { useEngine } from "../shared/engine";
import { aboutMinutes } from "../shared/places";
import { minutesUntil, type TownView } from "./model";
import { Badge, Meter, TONE } from "./ui";

const ROUTE = {
  clear: { label: "Route clear", cls: "text-ok" },
  risky: { label: "Route at risk", cls: "text-warn" },
  cut: { label: "Route cut", cls: "text-crit" },
} as const;

export default function Towns({ towns, selected, onSelect }: { towns: TownView[]; selected: string | null; onSelect: (name: string) => void }) {
  const { hello, score } = useEngine();
  const perTick = hello?.sim_minutes_per_tick ?? 1;
  const now = score?.tick ?? 0;
  return (
    <ul className="-mx-2">
      {towns.map((t) => {
        const w = t.threat?.within_60;
        const share = w ? w.k / Math.max(1, w.n) : 0;
        const route = t.threat?.route_status;
        return (
          <li key={t.name}>
            <button
              onClick={() => onSelect(t.name)}
              className={`w-full rounded-lg px-2 py-2 text-left transition-colors ${t.name === selected ? "bg-accent-soft" : "hover:bg-hover"}`}
            >
              <div className="flex items-center gap-2">
                <span className={`h-2 w-2 shrink-0 rounded-full ${TONE[t.tone].solid}`} />
                <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-ink">{t.name}</span>
                <Badge tone={t.tone}>{t.status}</Badge>
              </div>
              <div className="mt-1 flex items-center gap-2 pl-4 text-xs text-ink-2">
                <span className="tnum">{t.population.toLocaleString()} people</span>
                <span className="text-line-strong">·</span>
                <span className={t.eta ? `font-medium ${TONE[t.tone].text}` : "text-ink-3"}>{t.eta ?? "Not in the 1 h forecast"}</span>
                {route && (
                  <>
                    <span className="text-line-strong">·</span>
                    <span className={ROUTE[route].cls}>{ROUTE[route].label}</span>
                  </>
                )}
              </div>
              <OrderBy t={t} now={now} perTick={perTick} />
              {w && share > 0 && (
                <div className="mt-1.5 flex items-center gap-2 pl-4" title={`${w.k} of ${w.n} simulations reach it within 1 hour (likely ${Math.round(w.lo * 100)}–${Math.round(w.hi * 100)}%)`}>
                  <div className="flex-1">
                    <Meter value={share} lo={w.lo} hi={w.hi} tone={t.tone === "neutral" ? "warn" : t.tone} />
                  </div>
                  <span className="whitespace-nowrap text-right text-[11px] text-ink-3 tnum">
                    {Math.round(share * 100)}% within 1 h
                  </span>
                </div>
              )}
            </button>
          </li>
        );
      })}
    </ul>
  );
}

/** When the town's evacuation order has to go out, while it's still ahead:
 * a town far from the hour-ahead forecast can need hours to empty. Overdue
 * and ordered towns say so in their badge. */
function OrderBy({ t, now, perTick }: { t: TownView; now: number; perTick: number }) {
  const e = t.evac;
  if (!e || e.ordered_tick !== null || (e.status !== "watch" && e.status !== "order_soon")) return null;
  const left = minutesUntil(e.order_by_tick, now, perTick);
  if (left === null || left <= 0) return null;
  return (
    <div className={`mt-1 pl-4 text-xs ${e.status === "order_soon" ? "font-medium text-warn" : "text-ink-2"}`}>
      Order evacuation within <span className="tnum">{aboutMinutes(left)}</span>
      {e.order_by_bound && " or more"}
    </div>
  );
}
