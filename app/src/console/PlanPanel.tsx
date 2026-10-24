// Plan mode's side panel (#123): build a set of orders and an assumed wind,
// and see it against doing nothing, on paired simulations from the fire as it
// is now. Nothing changes until the operator dispatches the plan. The plan
// re-runs on its own a moment after each edit.

import { useEffect, useState } from "react";
import { clearPlan, evaluatePlan, useEngine } from "../shared/engine";
import { aboutMinutes, compass, describeLocation } from "../shared/places";
import type { PlanResult, PlanTown, TokenType, WindState } from "../shared/protocol";
import type { Scenario } from "../shared/scenario";
import { ORDER_STYLE, TOKEN_STYLE } from "../shared/tokens";
import { addToken } from "../shared/virtualTokens";
import { CloseIcon } from "./icons";
import { newDraft, PLAN_TYPES, resultsFor, type DraftOrder } from "./plan";
import { Button, Label, Segmented } from "./ui";

/** The wind a plan assumes: the observed one, or one the operator dials in. */
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
  /** Called after the plan's orders have been sent for real. */
  onDispatched: () => void;
}

export default function PlanPanel(props: Props) {
  const { scenario, drafts, wind, horizon } = props;
  const { plan, scenario: live, recommendations, hello, score } = useEngine();
  const observed = live?.wind ?? null;
  const [runs, setRuns] = useState(0);

  // Re-run a moment after the plan changes (and once on opening Plan mode).
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
  // Plans run from the fire's tick (the score's), not the engine's.
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
    <div className="space-y-4">
      <p className="text-[11px] leading-relaxed text-fg-subtle">
        Try orders and weather without changing anything. Each plan runs against doing nothing on the same
        simulations, so the difference is the plan, not luck.
      </p>

      <section>
        <div className="mb-1.5 flex items-center justify-between">
          <Label>Orders</Label>
          {recommendations.length > 0 && (
            <button onClick={addRecommended} className="text-[11px] text-ember-300 hover:text-ember-400">
              + Add recommended
            </button>
          )}
        </div>
        {drafts.length === 0 ? (
          <p className="text-[11px] leading-relaxed text-fg-subtle">
            Pick Crew, Dozer line or Air drop above the map and click where it should go. With no orders, the plan
            shows what the assumed wind alone would do.
          </p>
        ) : (
          <ol className="-mx-1.5 space-y-0.5">
            {drafts.map((d, i) => {
              const r = orders?.[i];
              return (
                <li key={d.id} className="group flex items-center gap-2 rounded-md px-1.5 py-1 hover:bg-surface-2">
                  <span
                    className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full border text-[10px] font-bold"
                    style={{ borderColor: TOKEN_STYLE[d.token_type].color, color: TOKEN_STYLE[d.token_type].color }}
                  >
                    {i + 1}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-xs text-fg">
                      {ORDER_STYLE[d.token_type].label} {describeLocation(scenario, d.x, d.y)}
                    </div>
                    <div className="truncate text-[10px] text-fg-subtle">
                      {!r ? (
                        "…"
                      ) : !r.counted ? (
                        <span className="text-red-400">No free unit can get there; left out</span>
                      ) : r.station ? (
                        <>
                          {r.station}, acts in about {aboutMinutes(r.eta_min ?? 0)}
                        </>
                      ) : (
                        "Acts at once"
                      )}
                    </div>
                  </div>
                  <TypeSwitch
                    value={d.token_type}
                    onChange={(t) => props.onDrafts((ds) => ds.map((x) => (x.id === d.id ? { ...x, token_type: t } : x)))}
                  />
                  <button
                    title="Remove from plan"
                    onClick={() => props.onDrafts((ds) => ds.filter((x) => x.id !== d.id))}
                    className="rounded p-1 text-fg-subtle opacity-0 hover:bg-surface-3 hover:text-fg group-hover:opacity-100"
                  >
                    <CloseIcon />
                  </button>
                </li>
              );
            })}
          </ol>
        )}
      </section>

      <section className="space-y-2">
        <div className="flex items-center justify-between">
          <Label>Assume wind</Label>
          <Segmented
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
        </div>
        {wind.custom ? (
          <div className="space-y-2 text-[11px]">
            <Slider
              label="Speed"
              value={`${wind.speed_ms.toFixed(0)} m/s`}
              min={0}
              max={20}
              step={1}
              v={wind.speed_ms}
              onChange={(v) => props.onWind({ ...wind, speed_ms: v })}
            />
            <Slider
              label="From"
              value={`${compass(wind.from_deg)} ${wind.from_deg.toFixed(0)}°`}
              min={0}
              max={355}
              step={5}
              v={wind.from_deg}
              onChange={(v) => props.onWind({ ...wind, from_deg: v })}
            />
          </div>
        ) : (
          observed && (
            <p className="text-[11px] text-fg-muted">
              {compass(observed.from_deg)} {observed.speed_ms.toFixed(0)} m/s, as it is now
            </p>
          )
        )}
        <div className="flex items-center justify-between pt-1">
          <Label>Look ahead</Label>
          <Segmented
            value={String(horizon)}
            onChange={(v) => props.onHorizon(Number(v))}
            options={HORIZONS.map((h) => ({ value: String(h), label: `${h / 60} h` }))}
          />
        </div>
      </section>

      <section>
        <div className="mb-1.5 flex items-center justify-between">
          <Label>Outcome by +{horizon / 60} h</Label>
          {running ? (
            <span className="flex items-center gap-1.5 text-[11px] text-fg-subtle">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-ember-400" />
              Simulating…
            </span>
          ) : (
            result &&
            staleMin >= 10 && (
              <button onClick={() => setRuns((n) => n + 1)} className="text-[11px] text-ember-300 hover:text-ember-400">
                Fire moved {Math.round(staleMin)} min on · re-run
              </button>
            )
          )}
        </div>
        {result?.error ? (
          <p className="text-[11px] text-fg-subtle">{result.error}</p>
        ) : result ? (
          <Outcome result={result} faded={running} />
        ) : (
          <p className="text-[11px] text-fg-subtle">{running ? "Running the plan…" : "—"}</p>
        )}
      </section>

      <div className="flex gap-2">
        <Button variant="primary" className="flex-1" onClick={counted.length ? dispatch : undefined}>
          {counted.length ? `Dispatch ${counted.length} order${counted.length > 1 ? "s" : ""}` : "Nothing to dispatch"}
        </Button>
        <Button onClick={() => props.onDrafts(() => [])}>Clear</Button>
      </div>
    </div>
  );
}

function Outcome({ result, faded }: { result: PlanResult; faded: boolean }) {
  const towns = result.towns.filter((t) => t.base.k > 0 || t.plan.k > 0);
  const saved = result.acres_saved;
  const sure = result.acres_saved_lo > 0;
  return (
    <div className={`space-y-3 transition-opacity ${faded ? "opacity-50" : ""}`}>
      <div className="grid grid-cols-2 gap-2">
        <Stat
          label="Acres burned"
          base={Math.round(result.acres_base).toLocaleString()}
          plan={Math.round(result.acres_plan).toLocaleString()}
          note={
            Math.abs(saved) < 1
              ? "no change"
              : `${saved > 0 ? "saves" : "adds"} ${Math.abs(Math.round(saved)).toLocaleString()} (${Math.round(result.acres_saved_lo).toLocaleString()} to ${Math.round(result.acres_saved_hi).toLocaleString()})`
          }
          good={sure}
          bad={result.acres_saved_hi < 0}
        />
        <Stat
          label="Residents in burned areas"
          base={Math.round(result.people_base).toLocaleString()}
          plan={Math.round(result.people_plan).toLocaleString()}
          note={`averaged over ${result.n} runs`}
          good={result.people_plan < result.people_base - 0.5}
          bad={result.people_plan > result.people_base + 0.5}
        />
      </div>
      {towns.length > 0 && (
        <table className="w-full text-[11px]">
          <thead>
            <tr className="text-left text-[10px] uppercase tracking-wide text-fg-subtle">
              <th className="pb-1 font-medium">Fire reaches</th>
              <th className="pb-1 text-right font-medium">Now</th>
              <th className="pb-1 text-right font-medium">With plan</th>
            </tr>
          </thead>
          <tbody>
            {towns.map((t) => (
              <TownRow key={t.town} t={t} />
            ))}
          </tbody>
        </table>
      )}
      <p className="text-[10px] leading-relaxed text-fg-subtle">
        {result.n} paired simulations, wind {compass(result.wind.from_deg)} {result.wind.speed_ms.toFixed(0)} m/s. Ranges
        are 90% intervals from the sampling.
      </p>
    </div>
  );
}

function Stat(props: { label: string; base: string; plan: string; note: string; good: boolean; bad: boolean }) {
  return (
    <div className="rounded-lg border border-edge bg-surface-2 p-2">
      <div className="text-[10px] text-fg-subtle">{props.label}</div>
      <div className="mt-0.5 font-mono text-[13px] tabular-nums">
        <span className="text-fg-muted">{props.base}</span>
        <span className="text-fg-subtle"> → </span>
        <span className={props.good ? "text-emerald-300" : props.bad ? "text-red-300" : "text-fg"}>{props.plan}</span>
      </div>
      <div className="mt-0.5 text-[10px] text-fg-subtle">{props.note}</div>
    </div>
  );
}

function TownRow({ t }: { t: PlanTown }) {
  const better = t.saves > t.worsens;
  const worse = t.worsens > t.saves;
  const fmt = (k: number, n: number, median: number | null) => (
    <>
      {k}/{n}
      {median != null && <span className="text-fg-subtle"> · {Math.round(median)}m</span>}
    </>
  );
  return (
    <tr className="border-t border-edge/60">
      <td className="py-1 text-fg">{t.town}</td>
      <td className="py-1 text-right font-mono tabular-nums text-fg-muted">{fmt(t.base.k, t.base.n, t.base_median_min)}</td>
      <td
        className={`py-1 text-right font-mono tabular-nums ${better ? "text-emerald-300" : worse ? "text-red-300" : "text-fg"}`}
        title={`Kept out in ${t.saves} simulations, pushed in in ${t.worsens}`}
      >
        {fmt(t.plan.k, t.plan.n, t.plan_median_min)}
      </td>
    </tr>
  );
}

function TypeSwitch({ value, onChange }: { value: TokenType; onChange: (t: TokenType) => void }) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value as TokenType)}
      title="Change the order type"
      className="rounded bg-transparent px-0.5 text-[10px] text-fg-subtle outline-none hover:bg-surface-3"
    >
      {PLAN_TYPES.map((t) => (
        <option key={t} value={t} className="bg-surface-1">
          {ORDER_STYLE[t].label}
        </option>
      ))}
    </select>
  );
}

function Slider(props: {
  label: string;
  value: string;
  min: number;
  max: number;
  step: number;
  v: number;
  onChange: (v: number) => void;
}) {
  return (
    <label className="block">
      <span className="flex justify-between text-fg-subtle">
        <span>{props.label}</span>
        <span className="font-mono tabular-nums text-fg">{props.value}</span>
      </span>
      <input
        type="range"
        min={props.min}
        max={props.max}
        step={props.step}
        value={props.v}
        onChange={(e) => props.onChange(Number(e.target.value))}
        className="w-full accent-ember-500"
      />
    </label>
  );
}
