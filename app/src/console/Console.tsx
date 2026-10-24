// The operator's console, the product (#122). Built for an incident manager
// or planning chief: what's happening, what needs a decision, and what each
// option would do. Three modes over one incident map:
//
// - Monitor: the decision queue, the town board, units and orders.
// - Plan: try orders and an assumed wind against doing nothing (#123).
// - Review: how it has gone so far, and the event log.
//
// Nothing here plays the world (lighting fires, setting the wind, running the
// clock); that's exercise control (?view=control), which stands in for the
// real incident and its drone footage.

import { useEffect, useRef, useState, type ReactNode } from "react";
import { getPlatform } from "../platform";
import { pttStart, pttStop, useEngine } from "../shared/engine";
import { compass } from "../shared/places";
import type { Recommendation, TokenType } from "../shared/protocol";
import { formatSimMinutes } from "../shared/round";
import { useEngineScenario } from "../shared/scenario";
import { DEFAULT_LAYERS, type Layers } from "../render/projection";
import CommanderPanel from "./CommanderPanel";
import Decisions from "./Decisions";
import { EventLogPanel } from "./EventLog";
import { FlameMark } from "./icons";
import IncidentMap, { type ConsoleMode, type Focus } from "./IncidentMap";
import { newDraft, PLAN_TYPES, type DraftOrder } from "./plan";
import PlanPanel, { type PlanWind } from "./PlanPanel";
import Resources from "./Resources";
import ReviewPanel from "./ReviewPanel";
import SoundToggle from "./SoundToggle";
import TownBoard from "./TownBoard";
import { ConnectionBadge, Panel } from "./ui";

const MODES: { value: ConsoleMode; label: string; hint: string }[] = [
  { value: "monitor", label: "Monitor", hint: "What's happening and what needs a decision" },
  { value: "plan", label: "Plan", hint: "Try orders and weather before committing" },
  { value: "review", label: "Review", hint: "How it has gone so far" },
];

const ORDER_TOOLS: TokenType[] = ["crew", "firebreak", "water", "bus"];

export default function Console() {
  const { status, scenario: live, situation, hello, score } = useEngine();
  const { scenario, error } = useEngineScenario();
  const [mode, setMode] = useState<ConsoleMode>("monitor");
  const [layers, setLayers] = useState<Layers>({ ...DEFAULT_LAYERS, contours: false });
  const [tool, setTool] = useState<TokenType | null>(null);
  const [focus, setFocus] = useState<Focus | null>(null);
  const [drafts, setDrafts] = useState<DraftOrder[]>([]);
  const [planWind, setPlanWind] = useState<PlanWind>({ custom: false, speed_ms: 8, from_deg: 45 });
  const [horizon, setHorizon] = useState(120);
  const seq = useRef(0);

  useEffect(() => {
    document.title = "Firewatch";
  }, []);

  const focusOn = (x: number, y: number) => setFocus({ seq: ++seq.current, x, y });
  const switchMode = (m: ConsoleMode) => {
    setMode(m);
    // A tool picked in Plan only edits the plan; carried into Monitor it would
    // send real units with the next click. Every mode starts out just looking.
    setTool(null);
  };
  function tryInPlan(r: Recommendation) {
    setDrafts((ds) => [...ds, newDraft(r.token_type, r.x, r.y)]);
    switchMode("plan");
  }

  // Keys: 1-4 pick an order tool, Esc goes back to looking, M/P/R switch
  // modes, and holding Space talks to the commander.
  const modeRef = useRef(mode);
  modeRef.current = mode;
  useEffect(() => {
    const typing = (e: KeyboardEvent) =>
      e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement || e.target instanceof HTMLSelectElement;
    function down(e: KeyboardEvent) {
      if (typing(e)) return;
      if (e.code === "Space") {
        e.preventDefault();
        if (!e.repeat) pttStart();
        return;
      }
      const tools = modeRef.current === "plan" ? PLAN_TYPES : modeRef.current === "monitor" ? ORDER_TOOLS : [];
      const i = Number(e.key) - 1;
      if (i >= 0 && i < tools.length) setTool(tools[i]);
      if (e.key === "Escape") setTool(null);
      const m = MODES.find((x) => x.value[0] === e.key.toLowerCase());
      if (m && !e.metaKey && !e.ctrlKey) switchMode(m.value);
    }
    function up(e: KeyboardEvent) {
      if (e.code === "Space" && !typing(e)) pttStop();
    }
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    window.addEventListener("blur", pttStop);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
      window.removeEventListener("blur", pttStop);
    };
    // switchMode only touches state through setters, so the first one is fine.
  }, []);

  // scenario_state.tick counts engine ticks since startup; the fire's own
  // clock (reset with the map) is the one the score and forecasts use.
  const perTick = hello?.sim_minutes_per_tick ?? 1;
  const fireTick = score?.tick ?? null;
  const forecastAge =
    fireTick != null && situation?.forecast_tick != null ? (fireTick - situation.forecast_tick) * perTick : null;

  // The town board (in Monitor), units, orders and the commander sit in their
  // own column on wide screens, and under the mode's panels otherwise.
  const side = scenario && (
    <>
      {mode === "monitor" && (
        <Panel title="Towns">
          <TownBoard scenario={scenario} onFocus={focusOn} />
        </Panel>
      )}
      <Panel title="Units and orders">
        <Resources scenario={scenario} onFocus={focusOn} />
      </Panel>
      <CommanderPanel />
    </>
  );

  return (
    <div className="flex h-full flex-col">
      <header className="flex h-12 shrink-0 items-center gap-3 whitespace-nowrap border-b border-edge px-4">
        <div className="flex items-center gap-2">
          <FlameMark />
          <span className="text-[13px] font-semibold tracking-[0.14em]">FIREWATCH</span>
        </div>
        {scenario && <span className="text-xs capitalize text-fg-muted">{scenario.info.name} incident</span>}
        <nav className="ml-2 flex rounded-lg border border-edge bg-surface-1 p-0.5">
          {MODES.map((m) => (
            <button
              key={m.value}
              title={`${m.hint} (${m.label[0]})`}
              onClick={() => switchMode(m.value)}
              className={`h-7 rounded-md px-3 text-xs font-medium transition-colors ${
                mode === m.value ? "bg-surface-3 text-fg" : "text-fg-muted hover:text-fg"
              }`}
            >
              {m.label}
            </button>
          ))}
        </nav>
        <div className="flex-1" />
        {live && (
          <>
            {fireTick != null && (
              <HeaderStat label="Clock" title="Sim time since the map was last reset">
                T+{formatSimMinutes(fireTick * perTick)}
              </HeaderStat>
            )}
            <HeaderStat label="Wind" title="Observed wind (where it blows from)">
              {compass(live.wind.from_deg)} {live.wind.speed_ms.toFixed(0)} m/s
            </HeaderStat>
            <HeaderStat label="Forecast" title="How old the forecast behind the town board is">
              {forecastAge == null ? "—" : forecastAge < 2 ? "current" : `${Math.round(forecastAge)} min old`}
            </HeaderStat>
          </>
        )}
        {live?.paused && (
          <span className="rounded bg-sky-500/15 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-sky-300">
            Paused
          </span>
        )}
        <div className="h-5 w-px bg-edge" />
        <button
          onClick={() => getPlatform().then((p) => p.openControl())}
          title="Open exercise control: the stand-in for the real world (fire, weather, the table)"
          className="h-7 rounded-md border border-edge bg-surface-1 px-2.5 text-xs text-fg-muted hover:bg-surface-2 hover:text-fg"
        >
          Exercise control ↗
        </button>
        <SoundToggle />
        <ConnectionBadge status={status} />
      </header>

      <div className="flex min-h-0 flex-1 gap-3 p-3">
        <aside className="flex w-[360px] shrink-0 flex-col gap-3 overflow-y-auto pb-3">
          {scenario && mode === "monitor" && (
            <>
              <Panel title="Decisions">
                <Decisions scenario={scenario} onFocus={focusOn} onTryInPlan={tryInPlan} />
              </Panel>
            </>
          )}
          {scenario && mode === "plan" && (
            <Panel title="Plan">
              <PlanPanel
                scenario={scenario}
                drafts={drafts}
                onDrafts={setDrafts}
                wind={planWind}
                onWind={setPlanWind}
                horizon={horizon}
                onHorizon={setHorizon}
                onDispatched={() => {
                  setTool(null);
                  setMode("monitor");
                }}
              />
            </Panel>
          )}
          {mode === "review" && (
            <>
              <Panel title="Outcome">
                <ReviewPanel />
              </Panel>
              <EventLogPanel />
            </>
          )}
          <div className="flex flex-col gap-3 xl:hidden">{side}</div>
        </aside>

        <main className="relative min-w-0 flex-1">
          <IncidentMap
            scenario={scenario}
            error={error}
            mode={mode}
            layers={layers}
            onToggleLayer={(k) => setLayers((l) => ({ ...l, [k]: !l[k] }))}
            tool={tool}
            onTool={setTool}
            drafts={drafts}
            onDrafts={setDrafts}
            onAddDraft={(t, x, y) => setDrafts((ds) => [...ds, newDraft(t, x, y)])}
            focus={focus}
          />
        </main>

        <aside className="hidden w-[340px] shrink-0 flex-col gap-3 overflow-y-auto pb-3 xl:flex">{side}</aside>
      </div>
    </div>
  );
}

function HeaderStat({ label, title, children }: { label: string; title: string; children: ReactNode }) {
  return (
    <span className="flex items-baseline gap-1.5 text-[11px]" title={title}>
      <span className="text-fg-subtle">{label}</span>
      <span className="font-mono tabular-nums text-fg">{children}</span>
    </span>
  );
}
