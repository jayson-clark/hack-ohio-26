// Every town in one list (#130): its status (from the evacuation clock when
// there is one), how soon fire could get there, how likely within the hour,
// and its way out. Most urgent first; a row opens the town in the inspector.

import type { TownView } from "./model";
import { Badge, Meter, TONE } from "./ui";

const ROUTE = {
  clear: { label: "Route clear", cls: "text-ok" },
  risky: { label: "Route at risk", cls: "text-warn" },
  cut: { label: "Route cut", cls: "text-crit" },
} as const;

export default function Towns({ towns, selected, onSelect }: { towns: TownView[]; selected: string | null; onSelect: (name: string) => void }) {
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
