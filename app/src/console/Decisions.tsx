// What needs a decision now (#122, #130), most urgent first: evacuation
// orders coming due on the evacuation clock (#121), towns with no way out,
// crew recommendations, and units that can't get through. Each card says
// what to do and by when, and carries its action; clicking it opens the
// details in the inspector.

import type { ReactNode } from "react";
import { orderText } from "../shared/dispatch";
import { acceptRecommendation, orderEvacuation, useEngine } from "../shared/engine";
import { aboutMinutes, describeLocation } from "../shared/places";
import { END_REASON_TEXT, formatSimMinutes, headline } from "../shared/round";
import type { Recommendation } from "../shared/protocol";
import type { Scenario } from "../shared/scenario";
import { ORDER_STYLE } from "../shared/tokens";
import { Icon, type IconName } from "./icons";
import { minutesUntil, type Selection, type TownView } from "./model";
import { Button, Empty, TONE, type Tone } from "./ui";

interface Item {
  key: string;
  tone: Tone;
  icon: IconName;
  rank: number;
  title: string;
  detail: ReactNode;
  select: Selection;
  actions: ReactNode;
}

interface Props {
  scenario: Scenario | null;
  towns: TownView[];
  onSelect: (s: Selection) => void;
  onTryInPlan: (rec: Recommendation) => void;
  /** Opens Review; offered once the exercise is over. */
  onReview?: () => void;
}

export function useDecisions({ scenario, towns, onTryInPlan }: Props): Item[] {
  const { recommendations, units, tokens, hello, score } = useEngine();
  const perTick = hello?.sim_minutes_per_tick ?? 1;
  const now = score?.tick ?? 0;
  const items: Item[] = [];
  if (!scenario) return items;

  for (const t of towns) {
    const e = t.evac;
    const sel: Selection = { kind: "town", name: t.name };
    if (e?.status === "trapped" || (!e && t.threat?.route_status === "cut" && (t.tone === "crit" || t.tone === "warn"))) {
      items.push({
        key: `trap-${t.name}`,
        tone: "crit",
        icon: "alert",
        rank: 0,
        title: `No way out of ${t.name}`,
        detail: `${t.population.toLocaleString()} residents. Every exit is cut or will burn first. Shelter in place, or send a crew to hold a road.`,
        select: sel,
        actions: null,
      });
      continue;
    }
    if (e && e.ordered_tick === null && (e.status === "late" || e.status === "order_now" || e.status === "order_soon")) {
      const left = minutesUntil(e.order_by_tick, now, perTick);
      const when =
        left === null
          ? "Waiting for the long forecast"
          : left > 0
            ? `Order within ${aboutMinutes(left)}${e.order_by_bound ? " or more" : ""}`
            : `${aboutMinutes(-left)} past the latest safe time`;
      const need = e.clearance_min === null ? null : e.mobilize_min + e.clearance_min;
      items.push({
        key: `evac-${t.name}`,
        tone: e.status === "order_soon" ? "warn" : "crit",
        icon: "users",
        rank: e.status === "order_soon" ? 2 : 1,
        title: `Order ${t.name} to evacuate`,
        detail: (
          <>
            <span className="font-medium text-ink">{when}.</span> {e.people.toLocaleString()} people
            {need !== null && <>, {aboutMinutes(need)} to get everyone out</>}
            {e.exits.length > 0 && <> via {e.exits.map((x) => x.safe_zone).join(" and ")}</>}.
          </>
        ),
        select: sel,
        actions: (
          <Button size="sm" variant={e.status === "order_soon" ? "secondary" : "primary"} onClick={() => orderEvacuation(t.name, true)}>
            Order evacuation
          </Button>
        ),
      });
    }
  }

  recommendations.forEach((r, i) => {
    items.push({
      key: r.id,
      tone: "info",
      icon: "bulb",
      rank: 3 + i * 0.01,
      title: `${r.action === "move" ? "Move a crew" : ORDER_STYLE[r.token_type].verb} ${describeLocation(scenario, r.x, r.y)}`,
      detail: <RecLine rec={r} />,
      select: { kind: "rec", id: r.id, x: r.x, y: r.y },
      actions: (
        <>
          <Button size="sm" variant="primary" disabled={!r.auto} title={r.auto ? undefined : "A crew on the table: move it by hand"} onClick={() => acceptRecommendation(r.id)}>
            {r.action === "move" ? "Move crew" : "Dispatch"}
          </Button>
          <Button size="sm" onClick={() => onTryInPlan(r)}>
            Try in plan
          </Button>
        </>
      ),
    });
  });

  for (const u of units) {
    if (u.status !== "blocked" && u.status !== "grounded") continue;
    const order = tokens.find((t) => t.id === u.token_id);
    items.push({
      key: `unit-${u.id}`,
      tone: "warn",
      icon: "route",
      rank: 4,
      title: u.status === "grounded" ? "Air tankers grounded" : `${u.id} can't get through`,
      detail: `${orderText(u)}.${u.status === "blocked" ? " Cancel the order or pick a spot a road reaches." : ""}`,
      select: order ? { kind: "order", id: order.id } : null,
      actions: null,
    });
  }

  return items.sort((a, b) => a.rank - b.rank);
}

export default function Decisions(props: Props) {
  const items = useDecisions(props);
  const { simGrid, situation, score } = useEngine();
  const burning = !!simGrid && simGrid.payload.includes(2);

  // Once the exercise ends the fire is frozen and orders do nothing, so its
  // last "act now" cards would only mislead (#128).
  if (score?.phase === "ended") {
    return (
      <div className="rounded-lg border border-line bg-panel p-3 shadow-card">
        <div className="text-[13px] font-semibold leading-snug text-ink">
          {score.end_reason ? END_REASON_TEXT[score.end_reason] : "Exercise over"} after {formatSimMinutes(score.elapsed_min)}
        </div>
        <p className="mt-0.5 text-xs leading-relaxed text-ink-2">
          {headline(score)
            .map((s) => `${s.value} ${s.label.toLowerCase()}${s.pct !== null ? ` (${s.pct}%)` : ""}`)
            .join(" · ")}
          . Start another from Exercise control.
        </p>
        {props.onReview && (
          <div className="mt-2.5 flex">
            <Button size="sm" variant="primary" onClick={props.onReview}>
              Review the exercise
            </Button>
          </div>
        )}
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <Empty>
        {!burning
          ? "No active fire. Start one from Exercise control."
          : situation?.forecast_tick == null
            ? "Running the first forecast…"
            : "Nothing needs a decision right now."}
      </Empty>
    );
  }
  return (
    <ul className="space-y-2">
      {items.map((it) => (
        <li
          key={it.key}
          onClick={() => it.select && props.onSelect(it.select)}
          className="group cursor-pointer rounded-lg border border-line bg-panel p-3 shadow-card transition-colors hover:border-line-strong"
        >
          <div className="flex gap-3">
            <span className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full ${TONE[it.tone].soft} ${TONE[it.tone].text}`}>
              <Icon name={it.icon} size={15} />
            </span>
            <div className="min-w-0 flex-1">
              <div className="text-[13px] font-semibold leading-snug text-ink">{it.title}</div>
              <p className="mt-0.5 text-xs leading-relaxed text-ink-2">{it.detail}</p>
              {it.actions && (
                <div className="mt-2.5 flex gap-1.5" onClick={(e) => e.stopPropagation()}>
                  {it.actions}
                </div>
              )}
            </div>
            <Icon name="chevronRight" size={15} className="mt-1 text-ink-3 opacity-0 transition-opacity group-hover:opacity-100" />
          </div>
        </li>
      ))}
    </ul>
  );
}

function RecLine({ rec }: { rec: Recommendation }) {
  const parts: ReactNode[] = [];
  if (rec.station && rec.eta_min != null) parts.push(`From ${rec.station}, ${aboutMinutes(rec.eta_min)} out`);
  if (rec.saves.length) parts.push(`keeps fire out of ${rec.saves.map((e) => `${e.town} (${e.hits}/${e.n})`).join(", ")}`);
  else if (rec.acres_saved > 0) parts.push(`saves about ${Math.round(rec.acres_saved).toLocaleString()} acres in the next hour`);
  return (
    <>
      {parts.join("; ")}.{rec.confidence !== "high" && <span className="text-warn"> Rough estimate.</span>}
    </>
  );
}
