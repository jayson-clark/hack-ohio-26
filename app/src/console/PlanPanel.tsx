// Plan mode (#123, #130): build a set of orders and an assumed wind, and see
// it against doing nothing on paired simulations from the fire as it is now.
// Nothing changes until the plan is dispatched. It re-runs a moment after
// each edit.

import { useEffect, useState, type ReactNode } from "react";
import { clearPlan, evaluatePlan, useEngine } from "../shared/engine";
import { aboutMinutes, compass, describeLocation } from "../shared/places";
import type { PlanResult, PlanTown, TokenType, WindState } from "../shared/protocol";
import type { Scenario } from "../shared/scenario";
import { ORDER_STYLE } from "../shared/tokens";
import { addToken } from "../shared/virtualTokens";
import { Icon } from "./icons";
import { ORDER_COLOR, ORDER_ICON } from "./model";
import { newDraft, PLAN_TYPES, resultsFor, type DraftOrder } from "./plan";
import { Button, Empty, IconButton, Section, Segmented } from "./ui";

/** The wind a plan assumes: as observed, or dialed in. */
export interface PlanWind {
  custom: boolean;
  speed_ms: number;
  from_deg: number;
}

const RERUN_MS = 600;
const HORIZONS = [60, 120, 180] as const;

interface Props {
  scenario: Scenario;
  drafts: DraftOrder[];
  onDrafts: (update: (d: DraftOrder[]) => DraftOrder[]) => void;
  wind: PlanWind;
  onWind: (w: PlanWind) => void;
  horizon: number;
  onHorizon: (min: number) => void;
  onDispatched: () => void;
  onFocus: (x: number, y: number) => void;
}

export default function PlanPanel(props: Props) {
  const { scenario, drafts, wind, horizon } = props;
  const { plan, scenario: live, recommendations, hello, score } = useEngine();
  // A plan can still be tried after the exercise ends, but not sent (#128).
  const over = score?.phase === "ended";
  const observed = live?.wind ?? null;
  const [runs, setRuns] = useState(0);

  const assumed: WindState | null = wind.custom ? { speed_ms: wind.speed_ms, from_deg: wind.from_deg } : null;
  const key = JSON.stringify([drafts.map((d) => [d.token_type, Math.round(d.x), Math.round(d.y)]), assumed, horizon, runs]);
  useEffect(() => {
    const t = window.setTimeout(() => {
      evaluatePlan(
        drafts.map((d) => ({ token_type: d.token_type, x: d.x, y: d.y })),
        assumed,
        horizon,
      );
    }, RERUN_MS);
    return () => clearTimeout(t);
    // `key` captures everything the plan depends on.
  }, [key]);

  const result = plan.result;
  const running = plan.pending !== 0 && result?.id !== plan.pending;
  const orders = resultsFor(drafts, result);
  const perTick = hello?.sim_minutes_per_tick ?? 1;
  const staleMin = result && score ? (score.tick - result.tick) * perTick : 0;
  const counted = drafts.filter((_, i) => orders?.[i]?.counted ?? true);

  function dispatch() {
    for (const d of counted) addToken(d.token_type, d.x, d.y, scenario);
    props.onDrafts(() => []);
    clearPlan();
    props.onDispatched();
  }

  function addRecommended() {
    const have = new Set(drafts.map((d) => `${d.token_type}${Math.round(d.x)},${Math.round(d.y)}`));
    const add = recommendations
      .filter((r) => r.action === "place" && PLAN_TYPES.includes(r.token_type))
      .filter((r) => !have.has(`${r.token_type}${Math.round(r.x)},${Math.round(r.y)}`))
      .map((r) => newDraft(r.token_type, r.x, r.y));
    props.onDrafts((ds) => [...ds, ...add]);
  }

  return (
    <div className="flex min-h-full flex-col">
      <div className="border-b border-line bg-sunken px-4 py-3 text-xs leading-relaxed text-ink-2">
        Try orders and weather without changing anything. Each plan runs against doing nothing on the same simulations, so
        the difference is the plan, not luck.
      </div>

      <Section
        title="Orders"
        count={drafts.length}
        action={
          recommendations.length > 0 && (
            <Button size="sm" variant="ghost" icon="bulb" onClick={addRecommended}>
              Add recommended
            </Button>
          )
        }
      >
        {drafts.length === 0 ? (
          <Empty>Pick Crew, Dozer line or Air drop above the map and click where it goes. With no orders, the plan shows what the assumed wind alone would do.</Empty>
        ) : (
          <ol className="-mx-2">
            {drafts.map((d, i) => {
              const r = orders?.[i];
              return (
                <li key={d.id} className="group flex items-center gap-2.5 rounded-lg px-2 py-1.5 hover:bg-hover">
                  <button
                    onClick={() => props.onFocus(d.x, d.y)}
                    title="Show on map"
                    className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md border-2 border-dashed text-xs font-bold"
                    style={{ borderColor: ORDER_COLOR[d.token_type], color: ORDER_COLOR[d.token_type] }}
                  >
                    {i + 1}
                  </button>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-[13px] font-medium text-ink">
                      {ORDER_STYLE[d.token_type].label} {describeLocation(scenario, d.x, d.y)}
                    </div>
                    <div className="truncate text-xs text-ink-3">
                      {!r ? (
                        "Checking which unit would go…"
                      ) : !r.counted ? (
                        <span className="text-crit">No free unit can get there, so it's left out</span>
                      ) : r.station ? (
                        `${r.station} · acts in ${aboutMinutes(r.eta_min ?? 0)}`
                      ) : (
                        "Acts at once"
                      )}
                    </div>
                  </div>
                  <TypeSwitch value={d.token_type} onChange={(t) => props.onDrafts((ds) => ds.map((x) => (x.id === d.id ? { ...x, token_type: t } : x)))} />
                  <IconButton icon="close" title="Remove from plan" onClick={() => props.onDrafts((ds) => ds.filter((x) => x.id !== d.id))} className="opacity-0 group-hover:opacity-100" />
                </li>
              );
            })}
          </ol>
        )}
      </Section>

      <Section title="Conditions">
        <div className="space-y-3">
          <Row label="Wind">
            <Segmented
              size="sm"
              value={wind.custom ? "custom" : "observed"}
              onChange={(v) =>
                props.onWind({
                  custom: v === "custom",
                  speed_ms: wind.custom ? wind.speed_ms : (observed?.speed_ms ?? wind.speed_ms),
                  from_deg: wind.custom ? wind.from_deg : (observed?.from_deg ?? wind.from_deg),
                })
              }
              options={[
                { value: "observed", label: "As observed" },
                { value: "custom", label: "What if…" },
              ]}
            />
          </Row>
          {wind.custom ? (
            <div className="space-y-2.5 rounded-lg border border-line bg-sunken p-3">
              <Slider label="Speed" value={`${wind.speed_ms.toFixed(0)} m/s`} min={0} max={20} step={1} v={wind.speed_ms} onChange={(v) => props.onWind({ ...wind, speed_ms: v })} />
              <Slider label="From" value={`${compass(wind.from_deg)} · ${wind.from_deg.toFixed(0)}°`} min={0} max={355} step={5} v={wind.from_deg} onChange={(v) => props.onWind({ ...wind, from_deg: v })} />
            </div>
          ) : (
            observed && (
              <p className="text-xs text-ink-2">
                {compass(observed.from_deg)} at {observed.speed_ms.toFixed(0)} m/s, as it is now.
              </p>
            )
          )}
          <Row label="Look ahead">
            <Segmented size="sm" value={String(horizon)} onChange={(v) => props.onHorizon(Number(v))} options={HORIZONS.map((h) => ({ value: String(h), label: `${h / 60} h` }))} />
          </Row>
        </div>
      </Section>

      <Section
        title={`Outcome in ${horizon / 60} h`}
        action={
          running ? (
            <span className="flex items-center gap-1.5 text-xs text-ink-3">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" />
              Simulating
            </span>
          ) : (
            result &&
            staleMin >= 10 && (
              <Button size="sm" variant="ghost" icon="history" onClick={() => setRuns((n) => n + 1)}>
                Fire moved on · re-run
              </Button>
            )
          )
        }
      >
        {result?.error ? (
          <Empty>{result.error}</Empty>
        ) : result ? (
          <Outcome result={result} faded={running} />
        ) : (
          <Empty>{running ? "Running the plan…" : "—"}</Empty>
        )}
      </Section>

      <div className="flex-1" />
      <footer className="sticky bottom-0 flex gap-2 border-t border-line bg-panel px-4 py-3">
        <Button variant="primary" className="flex-1" disabled={!counted.length || over} onClick={dispatch} icon="send">
          {over
            ? "Exercise over"
            : counted.length
              ? `Dispatch ${counted.length} order${counted.length > 1 ? "s" : ""}`
              : "Nothing to dispatch"}
        </Button>
        <Button disabled={!drafts.length} onClick={() => props.onDrafts(() => [])}>
          Clear
        </Button>
      </footer>
    </div>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-xs text-ink-2">{label}</span>
      {children}
    </div>
  );
}

function Outcome({ result, faded }: { result: PlanResult; faded: boolean }) {
  const towns = result.towns.filter((t) => t.base.k > 0 || t.plan.k > 0);
  const saved = result.acres_saved;
  return (
    <div className={`space-y-4 transition-opacity ${faded ? "opacity-50" : ""}`}>
      <div className="grid grid-cols-2 gap-2">
        <Compare
          label="Acres burned"
          base={Math.round(result.acres_base)}
          plan={Math.round(result.acres_plan)}
          note={
            Math.abs(saved) < 1
              ? "No change"
              : `${saved > 0 ? "Saves" : "Adds"} ${Math.abs(Math.round(saved)).toLocaleString()} (range ${Math.round(result.acres_saved_lo).toLocaleString()} to ${Math.round(result.acres_saved_hi).toLocaleString()})`
          }
          good={result.acres_saved_lo > 0}
          bad={result.acres_saved_hi < 0}
        />
        <Compare
          label="Residents in burned areas"
          base={Math.round(result.people_base)}
          plan={Math.round(result.people_plan)}
          note={`Average of ${result.n} runs`}
          good={result.people_plan < result.people_base - 0.5}
          bad={result.people_plan > result.people_base + 0.5}
        />
      </div>
      {towns.length > 0 && (
        <div>
          <div className="mb-1 grid grid-cols-[1fr_auto_auto] gap-x-4 text-[11px] font-medium text-ink-3">
            <span>Fire reaches</span>
            <span className="text-right">Do nothing</span>
            <span className="w-16 text-right">With plan</span>
          </div>
          {towns.map((t) => (
            <TownRow key={t.town} t={t} />
          ))}
        </div>
      )}
      <p className="text-[11px] leading-relaxed text-ink-3">
        {result.n} paired simulations, wind {compass(result.wind.from_deg)} {result.wind.speed_ms.toFixed(0)} m/s. Ranges are 90% intervals.
      </p>
    </div>
  );
}

function Compare(props: { label: string; base: number; plan: number; note: string; good: boolean; bad: boolean }) {
  return (
    <div className="rounded-lg border border-line p-3">
      <div className="text-[11px] font-medium text-ink-3">{props.label}</div>
      <div className="mt-1 flex items-baseline gap-1.5 tnum">
        <span className="text-xs text-ink-3 line-through decoration-line-strong">{props.base.toLocaleString()}</span>
        <Icon name="chevronRight" size={12} className="text-ink-3" />
        <span className={`text-[17px] font-semibold ${props.good ? "text-ok" : props.bad ? "text-crit" : "text-ink"}`}>{props.plan.toLocaleString()}</span>
      </div>
      <div className="mt-0.5 text-[11px] leading-snug text-ink-3">{props.note}</div>
    </div>
  );
}

function TownRow({ t }: { t: PlanTown }) {
  const better = t.saves > t.worsens;
  const worse = t.worsens > t.saves;
  return (
    <div className="grid grid-cols-[1fr_auto_auto] items-center gap-x-4 border-t border-line py-1.5 text-xs" title={`Kept out in ${t.saves} simulations, pushed in in ${t.worsens}`}>
      <span className="text-ink">{t.town}</span>
      <span className="text-right text-ink-3 tnum">
        {t.base.k}/{t.base.n}
      </span>
      <span className={`w-16 text-right font-medium tnum ${better ? "text-ok" : worse ? "text-crit" : "text-ink"}`}>
        {t.plan.k}/{t.plan.n}
      </span>
    </div>
  );
}

function TypeSwitch({ value, onChange }: { value: TokenType; onChange: (t: TokenType) => void }) {
  return (
    <span className="flex items-center gap-1 rounded-md border border-line px-1.5 py-0.5" style={{ color: ORDER_COLOR[value] }}>
      <Icon name={ORDER_ICON[value]} size={12} />
      <select value={value} onChange={(e) => onChange(e.target.value as TokenType)} title="Change the order type" className="bg-transparent text-[11px] text-ink-2 outline-none">
        {PLAN_TYPES.map((t) => (
          <option key={t} value={t}>
            {ORDER_STYLE[t].label}
          </option>
        ))}
      </select>
    </span>
  );
}

function Slider(props: { label: string; value: string; min: number; max: number; step: number; v: number; onChange: (v: number) => void }) {
  return (
    <label className="block text-xs">
      <span className="mb-1 flex justify-between">
        <span className="text-ink-2">{props.label}</span>
        <span className="font-medium text-ink tnum">{props.value}</span>
      </span>
      <input type="range" min={props.min} max={props.max} step={props.step} value={props.v} onChange={(e) => props.onChange(Number(e.target.value))} className="w-full accent-[#1f4fd6]" />
    </label>
  );
}
