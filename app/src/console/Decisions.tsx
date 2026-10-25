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
import { AutopilotCountdown, type AutopilotState } from "./Demo";
import { Icon, type IconName } from "./icons";
import { minutesUntil, type Selection, type TownView } from "./model";
import { useIncidentNames } from "./Incidents";
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
  /** A heads-up shown in the queue but not counted as a decision. */
  status?: boolean;
  /** What demo mode's autopilot does for this card (#158). */
  auto?: () => void;
}

// Before the order clock's long forecast lands, a town gets an evacuation card
// when at least this share of the simulations reach it within the hour.
const EVAC_SHARE = 0.25;

interface Props {
  scenario: Scenario | null;
  towns: TownView[];
  onSelect: (s: Selection) => void;
  onTryInPlan: (rec: Recommendation) => void;
  /** Opens Review; offered once the exercise is over. */
  onReview?: () => void;
  /** Demo mode's autopilot, to show its countdown on the card it will take. */
  autopilot?: AutopilotState;
}

export function useDecisions({ scenario, towns, onSelect, onTryInPlan }: Props): Item[] {
  const { recommendations, units, tokens, hello, score } = useEngine();
  // With several fires, say which one a card is about (#179).
  const fireNames = useIncidentNames();
  const onFire = (id: string | null | undefined) => (id && fireNames.get(id) ? ` (${fireNames.get(id)})` : "");
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
        title: `No way out of ${t.name}${onFire(t.threat?.incident)}`,
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
        title: `Order ${t.name} to evacuate${onFire(t.threat?.incident)}`,
        detail: (
          <>
            <span className="font-medium text-ink">{when}.</span> {e.people.toLocaleString()} people
            {need !== null && <>, {aboutMinutes(need)} to get everyone out</>}
            {e.exits.length > 0 && <> via {e.exits.map((x) => x.safe_zone).join(" and ")}</>}.
            {e.shares_with.length > 0 && <span className="text-warn"> Shares exit roads with {e.shares_with.join(", ")}.</span>}
            {e.n > 0 && e.people > 0 && (
              <> If ordered now, the last car gets out first in {e.p_safe_bound ? "at most " : ""}{Math.round(e.p_safe * e.n)} of {e.n} simulations.</>
            )}
          </>
        ),
        select: sel,
        auto: () => orderEvacuation(t.name, true),
        actions: (
          <Button size="sm" variant={e.status === "order_soon" ? "secondary" : "primary"} onClick={() => orderEvacuation(t.name, true)}>
            Order evacuation
          </Button>
        ),
      });
      continue;
    }
    if (e && e.ordered_tick !== null && e.status === "evacuating") {
      const out = minutesUntil(e.last_car_out_tick, now, perTick);
      items.push({
        key: `evac-${t.name}`,
        tone: "info",
        icon: "users",
        rank: 5,
        status: true,
        title: `${t.name} is evacuating`,
        detail: `${e.people.toLocaleString()} still in town${out !== null ? `, last car out in ${aboutMinutes(Math.max(0, out))}` : ""}.`,
        select: sel,
        actions: (
          <Button size="sm" onClick={() => orderEvacuation(t.name, false)}>
            Cancel order
          </Button>
        ),
      });
      continue;
    }
    // Until the clock's long forecast lands, fall back to the hour-ahead
    // forecast so a fast fire still gets an evacuation card.
    const th = t.threat;
    const share = th?.within_60 ? th.within_60.k / Math.max(1, th.within_60.n) : 0;
    if ((!e || (e.order_by_tick === null && e.ordered_tick === null && e.status === "watch")) && th && (th.fire_inside || share >= EVAC_SHARE)) {
      items.push({
        key: `evac-${t.name}`,
        tone: th.fire_inside || (th.soonest_min ?? Infinity) <= 30 ? "crit" : "warn",
        icon: "users",
        rank: 2,
        title: `Order ${t.name} to evacuate${onFire(t.threat?.incident)}`,
        detail: (
          <>
            <span className="font-medium text-ink">{th.fire_inside ? "Fire is in town." : arrivalText(th)}</span>{" "}
            {Math.round(share * 100)}% of simulations reach it within the hour. The order clock is still running its long forecast.
          </>
        ),
        select: sel,
        auto: () => orderEvacuation(t.name, true),
        actions: (
          <Button size="sm" variant="primary" onClick={() => orderEvacuation(t.name, true)}>
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
      title: `${r.action === "move" ? "Move a crew" : ORDER_STYLE[r.token_type].verb} ${describeLocation(scenario, r.x, r.y)}${onFire(r.incident)}`,
      detail: <RecLine rec={r} />,
      select: { kind: "rec", id: r.id, x: r.x, y: r.y },
      auto: r.auto ? () => acceptRecommendation(r.id) : undefined,
      actions: (
        <>
          <Button size="sm" variant="primary" disabled={!r.auto} title={r.auto ? undefined : "A crew on the table: move it by hand"} onClick={() => { acceptRecommendation(r.id); onSelect(null); }}>
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
      title: u.status === "grounded" ? "Air tankers grounded" : `${u.id} can't get through${onFire(u.incident)}`,
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
  const pending = props.autopilot?.pending;

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
              {pending?.key === it.key && <AutopilotCountdown at={pending.at} delayS={props.autopilot!.delayS} />}
            </div>
            <Icon name="chevronRight" size={15} className="mt-1 text-ink-3 opacity-0 transition-opacity group-hover:opacity-100" />
          </div>
        </li>
      ))}
    </ul>
  );
}

function RecLine({ rec }: { rec: Recommendation }) {
  // Every number is from the paired simulations, with its 90% range (#11).
  const pct = (x: number) => `${Math.round(x * 100)}%`;
  const parts: ReactNode[] = [];
  if (rec.station && rec.eta_min != null) parts.push(`From ${rec.station}, ${aboutMinutes(rec.eta_min)} out`);
  if (rec.saves.length)
    parts.push(`keeps fire out of ${rec.saves.map((e) => `${e.town} in ${e.hits} of ${e.n} simulations (likely ${pct(e.lo)}–${pct(e.hi)})`).join(", ")}`);
  if (rec.acres_saved > 0)
    parts.push(`saves about ${Math.round(Math.max(0, rec.acres_saved_lo)).toLocaleString()}–${Math.round(rec.acres_saved_hi).toLocaleString()} acres over the next two hours`);
  return (
    <>
      {parts.join("; ")}.
      {rec.act_by_min != null && (
        <span className={rec.act_by_min <= 5 ? "font-medium text-warn" : "font-medium text-ink"}>
          {" "}
          {rec.act_by_min <= 5 ? "Send now: fire reaches this spot soon after the crew could." : `Send within ${aboutMinutes(rec.act_by_min)} to dig in before the fire.`}
        </span>
      )}
      {rec.confidence !== "high" && <span className="text-warn"> Rough estimate: the range is wide.</span>}
    </>
  );
}

/** When fire could reach a town: the calibrated 90% range when the engine has
 * one (#13), else the hour forecast's 10th percentile. */
function arrivalText(th: { soonest_min: number | null; eta_lo_min: number | null; eta_hi_min: number | null }): string {
  if (th.eta_lo_min != null && th.eta_hi_min != null)
    return `Fire likely arrives in ${aboutMinutes(th.eta_lo_min)}–${aboutMinutes(th.eta_hi_min)} (90%).`;
  if (th.eta_lo_min != null) return `Fire could arrive in ${aboutMinutes(th.eta_lo_min)} or later.`;
  return `Fire could arrive in ${aboutMinutes(th.soonest_min ?? 60)}.`;
}
