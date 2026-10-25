// The operator console, the product (#122, #130). For an incident manager or
// planning chief: what's happening, what needs a decision, and what each
// option would do. Layout: a top bar, the mode's sidebar on the left, the
// incident map filling the rest, an inspector on the right for whatever is
// selected, and the commander docked in the map's corner.
//
// - Monitor: situation, decisions, towns, units and orders.
// - Plan: try orders and an assumed wind against doing nothing (#123).
// - Review: the outcome so far and the timeline.
//
// Nothing here plays the world (fire, wind, clock); that's exercise control
// (?view=control), which stands in for the real incident.

import { useEffect, useRef, useState } from "react";
import { getPlatform } from "../platform";
import { pttStart, pttStop, useEngine } from "../shared/engine";
import type { Recommendation, TokenType } from "../shared/protocol";
import { formatSimMinutes } from "../shared/round";
import { useEngineScenario } from "../shared/scenario";
import CommanderDock from "./CommanderDock";
import Decisions, { useDecisions } from "./Decisions";
import { DemoBar, useAutopilot, useDemoMode } from "./Demo";
import DispatchDrafts from "./DispatchDrafts";
import { EventAlerts } from "./EventLog";
import { FlameMark, Icon, type IconName } from "./icons";
import Inspector from "./Inspector";
import IncidentMap, { DEFAULT_MAP_LAYERS, type ConsoleMode, type MapLayers } from "./map/IncidentMap";
import type { MapHandle } from "./map/MapView";
import { useTowns, type Selection } from "./model";
import { newDraft, PLAN_TYPES, type DraftOrder } from "./plan";
import PlanPanel, { type PlanWind } from "./PlanPanel";
import Resources from "./Resources";
import ReviewPanel from "./ReviewPanel";
import Situation from "./Situation";
import SoundToggle from "./SoundToggle";
import ThemeToggle from "./ThemeToggle";
import Towns from "./Towns";
import { Button, ConnectionBadge, Section } from "./ui";

const MODES: { value: ConsoleMode; label: string; icon: IconName; hint: string }[] = [
  { value: "monitor", label: "Monitor", icon: "monitor", hint: "What's happening and what needs a decision" },
  { value: "plan", label: "Plan", icon: "plan", hint: "Try orders and weather before committing" },
  { value: "review", label: "Review", icon: "review", hint: "How it has gone so far" },
];

const ORDER_TOOLS: TokenType[] = ["crew", "firebreak", "water", "bus"];

export default function Console() {
  const { status, situation, hello, score, simGrid } = useEngine();
  const { scenario, error } = useEngineScenario();
  const [mode, setMode] = useState<ConsoleMode>("monitor");
  const [layers, setLayers] = useState<MapLayers>(DEFAULT_MAP_LAYERS);
  const [tool, setTool] = useState<TokenType | null>(null);
  const [selection, setSelection] = useState<Selection>(null);
  const [focus, setFocus] = useState<{ seq: number; x: number; y: number } | null>(null);
  const [drafts, setDrafts] = useState<DraftOrder[]>([]);
  const [planWind, setPlanWind] = useState<PlanWind>({ custom: false, speed_ms: 8, from_deg: 45 });
  const [horizon, setHorizon] = useState(120);
  const map = useRef<MapHandle>(null);
  const seq = useRef(0);
  const towns = useTowns(scenario);

  useEffect(() => {
    document.title = "Fireline";
  }, []);

  const focusOn = (x: number, y: number) => {
    setFocus({ seq: ++seq.current, x, y });
    map.current?.focus(x, y);
  };
  function select(s: Selection) {
    setSelection(s);
    if (!s || !scenario) return;
    if (s.kind === "town") {
      const t = scenario.towns.find((x) => x.name === s.name);
      if (t) focusOn(t.x, t.y);
    } else if (s.kind === "rec") focusOn(s.x, s.y);
  }
  const switchMode = (m: ConsoleMode) => {
    setMode(m);
    // A tool picked in Plan only edits the plan; carried into Monitor it would
    // send real units with the next click. Every mode starts out selecting.
    setTool(null);
  };
  function tryInPlan(r: Recommendation) {
    setDrafts((ds) => [...ds, newDraft(r.token_type, r.x, r.y)]);
    setSelection(null);
    switchMode("plan");
  }
  // An ended exercise takes no orders, so nothing is waiting on a decision (#128).
  const over = score?.phase === "ended";
  // Heads-ups such as a town already evacuating show in the queue but aren't
  // decisions, so they don't count toward the badge.
  const items = useDecisions({ scenario, towns, onSelect: select, onTryInPlan: tryInPlan });
  const decisions = over ? 0 : items.filter((i) => !i.status).length;
  const pendingDrafts = useEngine().dispatchDrafts.filter((d) => d.status === "draft").length;
  // Demo mode (#158): the clock in the console, and an autopilot that takes
  // decisions on its own while the presenter talks.
  const demo = useDemoMode();
  const [autopilot, setAutopilot] = useAutopilot(over ? [] : items, demo);

  // Keys: 1-4 pick an order tool, Esc goes back to selecting (then closes the
  // inspector), M/P/R switch modes, and holding Space talks to the commander.
  const modeRef = useRef(mode);
  modeRef.current = mode;
  const toolRef = useRef(tool);
  toolRef.current = tool;
  const overRef = useRef(over);
  overRef.current = over;
  useEffect(() => {
    const typing = (e: KeyboardEvent) =>
      e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement || e.target instanceof HTMLSelectElement;
    function down(e: KeyboardEvent) {
      if (typing(e) || e.metaKey || e.ctrlKey) return;
      if (e.code === "Space") {
        e.preventDefault();
        if (!e.repeat) pttStart();
        return;
      }
      const tools = overRef.current ? [] : modeRef.current === "plan" ? PLAN_TYPES : modeRef.current === "monitor" ? ORDER_TOOLS : [];
      const i = Number(e.key) - 1;
      if (i >= 0 && i < tools.length) setTool(tools[i]);
      if (e.key === "Escape") {
        if (toolRef.current === null) setSelection(null);
        setTool(null);
      }
      const m = MODES.find((x) => x.value[0] === e.key.toLowerCase());
      if (m) switchMode(m.value);
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

  // scenario_state.tick counts engine ticks; the fire's clock is the score's.
  const perTick = hello?.sim_minutes_per_tick ?? 1;
  // In free play the fire's clock runs from the last map reset whether or not
  // anything has burned, so hide it until something has (#128).
  const fireStarted = !!score && (score.phase !== "sandbox" || score.acres_burned > 0);
  const fireTick = fireStarted ? score.tick : null;
  const forecastAge = fireTick != null && situation?.forecast_tick != null ? (fireTick - situation.forecast_tick) * perTick : null;
  const burning = !!simGrid && simGrid.payload.includes(2);

  return (
    <div className="flex h-full flex-col">
      <header className="relative z-20 flex h-14 shrink-0 items-center gap-4 border-b border-line bg-panel px-4">
        <div className="flex items-center gap-2.5">
          <FlameMark size={26} />
          <span className="text-[15px] font-semibold tracking-tight text-ink">Fireline</span>
        </div>
        <div className="h-6 w-px bg-line" />
        <div className="min-w-0 leading-tight">
          <div className="flex items-center gap-2">
            <span className="truncate text-[13px] font-semibold capitalize text-ink">{scenario?.info.name ?? "—"} incident</span>
            {over ? (
              <span className="rounded-full bg-sunken px-2 text-[11px] font-medium leading-[18px] text-ink-2">Exercise over</span>
            ) : burning ? (
              <span className="flex items-center gap-1 rounded-full bg-crit-soft px-2 text-[11px] font-medium leading-[18px] text-crit">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-crit" />
                Active fire
              </span>
            ) : (
              <span className="rounded-full bg-sunken px-2 text-[11px] font-medium leading-[18px] text-ink-2">No active fire</span>
            )}
          </div>
          <div className="text-[11px] text-ink-3 tnum">
            {fireTick != null ? `T+${formatSimMinutes(fireTick * perTick)}` : "—"}
            {forecastAge != null && ` · forecast ${forecastAge < 2 ? "current" : `${Math.round(forecastAge)} min old`}`}
          </div>
        </div>

        <nav className="absolute left-1/2 flex -translate-x-1/2 rounded-lg bg-sunken p-1 ring-1 ring-line ring-inset">
          {MODES.map((m) => (
            <button
              key={m.value}
              title={`${m.hint} (${m.label[0]})`}
              onClick={() => switchMode(m.value)}
              className={`flex h-8 items-center gap-2 rounded-md px-3.5 text-[13px] font-medium transition-colors ${
                mode === m.value ? "bg-panel text-ink shadow-card ring-1 ring-line" : "text-ink-2 hover:text-ink"
              }`}
            >
              <Icon name={m.icon} size={15} />
              {m.label}
              {m.value === "monitor" && decisions > 0 && (
                <span className="rounded-full bg-crit px-1.5 text-[10px] font-semibold leading-4 text-white tnum">{decisions}</span>
              )}
            </button>
          ))}
        </nav>

        <div className="flex-1" />
        <Button
          size="sm"
          variant="ghost"
          icon="sliders"
          title="Open exercise control: the stand-in for the real world (fire, weather, the table)"
          onClick={() => getPlatform().then((p) => p.openControl())}
        >
          Exercise control
        </Button>
        <SoundToggle />
        <ThemeToggle />
        <div className="h-6 w-px bg-line" />
        <ConnectionBadge status={status} />
      </header>

      <div className="flex min-h-0 flex-1">
        <aside className="flex w-[380px] shrink-0 flex-col overflow-y-auto border-r border-line bg-panel">
          {scenario && mode === "monitor" && (
            <>
              <Situation towns={towns} />
              <Section title="Needs decision" count={decisions} className="mt-2">
                <Decisions scenario={scenario} towns={towns} onSelect={select} onTryInPlan={tryInPlan} onReview={() => switchMode("review")} autopilot={autopilot} />
              </Section>
              <Section title="Drafts" count={pendingDrafts}>
                <DispatchDrafts />
              </Section>
              <Section title="Towns" count={towns.length}>
                <Towns towns={towns} selected={selection?.kind === "town" ? selection.name : null} onSelect={(name) => select({ kind: "town", name })} />
              </Section>
              <Section title="Units and orders">
                <Resources scenario={scenario} selected={selection?.kind === "order" ? selection.id : null} onSelect={(id) => select({ kind: "order", id })} />
              </Section>
            </>
          )}
          {scenario && mode === "plan" && (
            <PlanPanel
              scenario={scenario}
              drafts={drafts}
              onDrafts={setDrafts}
              wind={planWind}
              onWind={setPlanWind}
              horizon={horizon}
              onHorizon={setHorizon}
              onFocus={focusOn}
              onDispatched={() => {
                setTool(null);
                setMode("monitor");
              }}
            />
          )}
          {mode === "review" && <ReviewPanel />}
        </aside>

        <main className="relative min-w-0 flex-1 bg-canvas">
          {scenario ? (
            <IncidentMap
              scenario={scenario}
              mode={mode}
              towns={towns}
              layers={layers}
              onLayers={setLayers}
              tool={tool}
              onTool={setTool}
              selection={selection}
              onSelect={select}
              drafts={drafts}
              onDrafts={setDrafts}
              onAddDraft={(t, x, y) => setDrafts((ds) => [...ds, newDraft(t, x, y)])}
              focus={focus}
              handle={map}
            />
          ) : (
            <div className="flex h-full items-center justify-center text-sm text-ink-3">
              {error ? <span className="font-mono text-crit">{error}</span> : "Loading map…"}
            </div>
          )}
          <EventAlerts onSelect={select} />
          {demo && (
            <div className="pointer-events-none absolute inset-x-0 bottom-4 z-10 flex justify-center">
              <DemoBar autopilot={autopilot} onAutopilot={setAutopilot} />
            </div>
          )}
          <div className="absolute bottom-4 right-4 z-10">
            <CommanderDock />
          </div>
        </main>

        {scenario && selection && (
          <Inspector scenario={scenario} towns={towns} selection={selection} onClose={() => setSelection(null)} onFocus={focusOn} onTryInPlan={tryInPlan} />
        )}
      </div>
    </div>
  );
}
