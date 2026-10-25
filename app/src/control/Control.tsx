// Exercise control: the window that plays the real world. It lights the fire,
// sets the weather, runs the clock and the exercise, and drives the physical
// table (3D virtual table, projector, camera). In a real incident this is the
// fire itself plus drone footage and weather stations; the operator never
// needs it, and works in the console instead.

import { useEffect, useMemo, useRef, useState } from "react";
import type { BinaryFrame } from "../shared/binary";
import { send, useEngine } from "../shared/engine";
import { SCENARIOS, useEngineScenario, type Scenario } from "../shared/scenario";
import { TOKEN_TYPES } from "../shared/tokens";
import { removeToken, type PlaceType } from "../shared/virtualTokens";
import { isTauri } from "../platform";
import { DEFAULT_LAYERS, type Layers } from "../render/projection";
import type { CameraCommand } from "../render/TableView";
import { EventAlerts } from "../console/EventLog";
import { FlameMark } from "../console/icons";
import ThemeToggle from "../console/ThemeToggle";
import { ConnectionBadge } from "../console/ui";
import { RoundSummaryCard } from "./RoundSummary";
import Sidebar from "./Sidebar";
import SimControls from "./SimControls";
import Viewport, { type ViewMode } from "./Viewport";

export default function Control() {
  const { status, scenario: state, tokens, simGrid, forecast, routes, vision, cameraFrame, score } = useEngine();
  const { scenario, error } = useEngineScenario();
  const [placeType, setPlaceType] = useState<PlaceType>("ignite");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [mode, setMode] = useState<ViewMode>("table");
  const [layers, setLayers] = useState<Layers>(DEFAULT_LAYERS);
  const [camera, setCamera] = useState<CameraCommand | null>(null);
  const seq = useRef(0);

  useEffect(() => {
    document.title = "Fireline · Exercise control";
  }, []);

  // Drop the selection when its token goes away.
  useEffect(() => {
    if (selectedId && !tokens.some((t) => t.id === selectedId)) setSelectedId(null);
  }, [tokens, selectedId]);

  // Keyboard: 1-4 pick a token type, I picks ignite, Delete removes the selection, Esc clears it.
  const live = useRef({ tokens, selectedId });
  live.current = { tokens, selectedId };
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLSelectElement) return;
      const index = Number(e.key) - 1;
      if (index >= 0 && index < TOKEN_TYPES.length) setPlaceType(TOKEN_TYPES[index]);
      if (e.key === "i") setPlaceType("ignite");
      if (e.key === "Escape") setSelectedId(null);
      if (e.key === "Delete" || e.key === "Backspace") {
        const t = live.current.tokens.find((tk) => tk.id === live.current.selectedId);
        if (t?.source === "virtual") removeToken(t.id);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="flex h-full flex-col">
      <header
        data-tauri-drag-region
        className={`flex h-12 shrink-0 items-center gap-3 whitespace-nowrap border-b border-edge pr-4 ${isTauri ? "pl-[80px]" : "pl-4"}`}
      >
        <div data-tauri-drag-region className="flex items-center gap-2">
          <FlameMark size={24} />
          <span className="text-[15px] font-semibold tracking-tight text-ink">Fireline</span>
          <span className="rounded-full bg-accent-soft px-2 text-[11px] font-medium leading-5 text-accent">Exercise control</span>
        </div>
        {scenario && <ScenarioPicker scenario={scenario} />}
        <div data-tauri-drag-region className="h-full flex-1" />
        <SimControls state={state} />
        <FireStats scenario={scenario} simGrid={simGrid} />
        <div className="h-5 w-px bg-edge" />
        {state && (
          <span className="hidden font-mono text-[11px] tabular-nums text-fg-subtle 2xl:inline">
            tick <span className="text-fg-muted">{state.tick}</span>
          </span>
        )}
        <ThemeToggle />
        <ConnectionBadge status={status} />
      </header>

      <div className="flex min-h-0 flex-1 gap-3 p-3">
        <main className="relative min-w-0 flex-1">
          <Viewport
            scenario={scenario}
            error={error}
            mode={mode}
            onModeChange={setMode}
            tokens={tokens}
            simGrid={simGrid}
            forecast={forecast}
            routes={routes}
            vision={vision}
            cameraFrame={cameraFrame}
            layers={layers}
            onToggleLayer={(k) => setLayers((l) => ({ ...l, [k]: !l[k] }))}
            placeType={placeType}
            selectedId={selectedId}
            onSelect={setSelectedId}
            camera={camera}
            onCameraPreset={(preset) => setCamera({ seq: ++seq.current, kind: "preset", preset })}
          />
          <EventAlerts />
          <RoundSummaryCard score={score} />
        </main>
        <Sidebar
          scenario={scenario}
          wind={state?.wind ?? null}
          score={score}
          tokens={tokens}
          placeType={placeType}
          onPlaceType={setPlaceType}
          selectedId={selectedId}
          onSelect={setSelectedId}
          onFocusPlace={(x, y) => {
            setMode("table");
            setCamera({ seq: ++seq.current, kind: "focus", x, y });
          }}
        />
      </div>
    </div>
  );
}

// Choosing a scenario tells the engine to switch (#57), and every window
// follows the hello it sends back.
function ScenarioPicker({ scenario }: { scenario: Scenario }) {
  const { info } = scenario;
  const km = (cells: number) => ((cells * info.grid.cell_size_m) / 1000).toFixed(0);
  return (
    <div className="flex items-center gap-2 rounded-md border border-edge bg-surface-1 px-1 py-0.5 text-[11px]">
      <select
        value={info.name}
        title="Switch scenario (resets the fire and clears virtual tokens)"
        onChange={(e) => send({ type: "load_scenario", scenario: e.target.value })}
        className="cursor-pointer rounded bg-transparent px-1 py-0.5 font-medium capitalize text-fg outline-none hover:bg-surface-2"
      >
        {SCENARIOS.map((name) => (
          <option key={name} value={name} className="bg-surface-1 capitalize">
            {name}
          </option>
        ))}
      </select>
      <span className="hidden text-fg-subtle 2xl:inline">
        {km(scenario.width)} × {km(scenario.height)} km · {scenario.width}×{scenario.height} cells
      </span>
    </div>
  );
}

const SQ_M_PER_ACRE = 4046.86;

function FireStats({ scenario, simGrid }: { scenario: Scenario | null; simGrid: BinaryFrame | null }) {
  const stats = useMemo(() => {
    if (!simGrid) return null;
    let burning = 0;
    let burned = 0;
    for (const c of simGrid.payload) {
      if (c === 2) burning++;
      else if (c === 3) burned++;
    }
    return { burning, burned };
  }, [simGrid]);

  if (!stats || !scenario) {
    return <span className="text-[11px] text-fg-subtle">No fire data yet</span>;
  }
  const acres = (cells: number) =>
    Math.round((cells * scenario.info.grid.cell_size_m ** 2) / SQ_M_PER_ACRE).toLocaleString();
  return (
    <div className="flex items-center gap-4 text-[11px]">
      <span className="flex items-center gap-1.5">
        <span className="h-2 w-2 animate-pulse rounded-full bg-ember-500" />
        <span className="text-fg-subtle">Burning</span>
        <span className="font-mono tabular-nums text-ember-300">{acres(stats.burning)} ac</span>
      </span>
      <span className="flex items-center gap-1.5">
        <span className="text-fg-subtle">Burned</span>
        <span className="font-mono tabular-nums text-fg">{acres(stats.burned)} ac</span>
      </span>
    </div>
  );
}
