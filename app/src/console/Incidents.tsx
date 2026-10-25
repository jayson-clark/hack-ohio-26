// Several fires on one map (#179): one row per incident, biggest first, so
// the operator can see what's burning where before splitting units between
// fires. Shown only when there's more than one; with a single fire the
// Situation numbers above already say it all. A row focuses the map on it.

import { useEngine } from "../shared/engine";
import type { Incident } from "../shared/protocol";
import { Badge, Section } from "./ui";

/** Incident names by id, for chips on cards and orders; empty with one fire. */
export function useIncidentNames(): Map<string, string> {
  const { incidents } = useEngine();
  return new Map(incidents.length > 1 ? incidents.map((i) => [i.id, i.name]) : []);
}

export default function Incidents({ onFocus }: { onFocus: (x: number, y: number) => void }) {
  const { incidents } = useEngine();
  if (incidents.length < 2) return null;
  const rows = [...incidents].sort((a, b) => Number(b.active) - Number(a.active) || b.acres - a.acres);
  return (
    <Section title="Fires" count={incidents.filter((i) => i.active).length}>
      <ul className="-mx-2">
        {rows.map((i) => (
          <li key={i.id}>
            <IncidentRow incident={i} onFocus={onFocus} />
          </li>
        ))}
      </ul>
    </Section>
  );
}

function IncidentRow({ incident: i, onFocus }: { incident: Incident; onFocus: (x: number, y: number) => void }) {
  return (
    <button
      onClick={() => onFocus(i.x, i.y)}
      className="flex w-full items-center gap-2.5 rounded-lg px-2 py-2 text-left transition-colors hover:bg-hover"
    >
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[13px] font-medium text-ink">{i.name}</span>
        <span className="block truncate text-xs text-ink-3 tnum">
          {Math.round(i.acres).toLocaleString()} ac
          {i.active && i.growth_ac_h > 0 && ` · +${Math.round(i.growth_ac_h).toLocaleString()} ac per hour`}
        </span>
      </span>
      <Badge tone={i.active ? "crit" : "neutral"} dot={i.active}>
        {i.active ? "Burning" : "Out"}
      </Badge>
    </button>
  );
}
