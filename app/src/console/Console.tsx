import { useEffect, useMemo, useRef, useState } from "react";
import type { BinaryFrame } from "../shared/binary";
import { pttStart, pttStop, setVoiceMode, useEngine } from "../shared/engine";
import { speechSupported } from "../shared/speech";
import { useScenario, type Scenario } from "../shared/scenario";
import { TOKEN_TYPES } from "../shared/tokens";
import { removeToken, type PlaceType } from "../shared/virtualTokens";
import { DEFAULT_LAYERS, type Layers } from "../render/projection";
import type { CameraCommand } from "../render/TableView";
import { EventAlerts } from "./EventLog";
import { FlameMark } from "./icons";
import { RoundSummaryCard } from "./RoundSummary";
import { Segmented } from "./ui";
import Sidebar from "./Sidebar";
import SimControls from "./SimControls";
import Viewport, { type ViewMode } from "./Viewport";

export default function Console() {
  const {
    status,
    scenario: state,
    tokens,
    simGrid,
    forecast,
    routes,
    vision,
    cameraFrame,
    score,
    voiceMode,
    hello,
    listening,
    heard,
  } = useEngine();
  const { scenario, error } = useScenario();
  const [placeType, setPlaceType] = useState<PlaceType>("crew");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [mode, setMode] = useState<ViewMode>("table");
  const [layers, setLayers] = useState<Layers>(DEFAULT_LAYERS);
  const [camera, setCamera] = useState<CameraCommand | null>(null);
  const seq = useRef(0);

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

  // Hold Space to talk to the commander (outside text fields).
  useEffect(() => {
    const typing = (e: KeyboardEvent) =>
      e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement;
    function down(e: KeyboardEvent) {
      if (e.code !== "Space" || e.repeat || typing(e)) return;
      e.preventDefault();
      pttStart();
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
  }, []);

  return (
    <div className="flex h-full flex-col">
      {/* Everything here stays on one line: low-value text (scenario size, tick)
          only shows on wide screens, so the demo controls always fit. */}
      <header className="flex h-12 shrink-0 items-center gap-3 whitespace-nowrap border-b border-edge px-4">
        <div className="flex items-center gap-2">
          <FlameMark />
          <span className="text-[13px] font-semibold tracking-[0.14em]">FIREWATCH</span>
        </div>
        {scenario && <ScenarioBadge scenario={scenario} />}
        <div className="flex-1" />
        <SimControls state={state} />
        <FireStats scenario={scenario} simGrid={simGrid} />
        <div className="h-5 w-px bg-edge" />
        {state && (
          <span className="hidden font-mono text-[11px] tabular-nums text-fg-subtle 2xl:inline">
            tick <span className="text-fg-muted">{state.tick}</span>
          </span>
        )}
        <TalkButton available={hello?.speech_to_text ?? false} listening={listening} heard={heard} />
        <span className="flex items-center gap-1.5">
          <span className="text-[11px] text-fg-subtle">Voice</span>
          <Segmented
            value={voiceMode}
            onChange={setVoiceMode}
            options={[
              { value: "off", label: "Off" },
              ...(speechSupported ? [{ value: "console" as const, label: "Console" }] : []),
              { value: "mac", label: "Mac" },
            ]}
          />
        </span>
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

function ScenarioBadge({ scenario }: { scenario: Scenario }) {
  const { info } = scenario;
  const km = (cells: number) => ((cells * info.grid.cell_size_m) / 1000).toFixed(0);
  return (
    <div className="flex items-center gap-2 rounded-md border border-edge bg-surface-1 px-2 py-1 text-[11px]">
      <span className="font-medium capitalize text-fg">{info.name}</span>
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

function ConnectionBadge({ status }: { status: string }) {
  const open = status === "open";
  const color = open ? "bg-emerald-400" : status === "connecting" ? "bg-amber-400" : "bg-red-500";
  return (
    <span
      className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] ${
        open ? "border-emerald-500/25 bg-emerald-500/10 text-emerald-300" : "border-edge bg-surface-1 text-fg-muted"
      }`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${color} ${open ? "" : "animate-pulse"}`} />
      {/* "Connected" on a laptop, "Engine connected" where there's room. */}
      <span className="hidden 2xl:inline">Engine </span>
      <span className="2xl:lowercase">{open ? "Connected" : status === "connecting" ? "Connecting…" : "Offline"}</span>
    </span>
  );
}

function TalkButton({
  available,
  listening,
  heard,
}: {
  available: boolean;
  listening: boolean;
  heard: { text: string; error: string | null } | null;
}) {
  // Push-to-talk for the incident commander (also: hold Space). Moves into the commander panel (#29).
  const label = listening ? "Listening…" : "Hold to talk";
  const note = heard ? (heard.text ? `“${heard.text}”` : heard.error) : null;
  return (
    <div className="flex min-w-0 items-center gap-2">
      <button
        disabled={!available}
        title={available ? "Hold (or hold Space) and ask the commander a question" : "Speech-to-text isn't installed: cd engine && uv sync --extra voice"}
        onPointerDown={(e) => {
          e.currentTarget.setPointerCapture(e.pointerId);
          pttStart();
        }}
        onPointerUp={pttStop}
        onPointerCancel={pttStop}
        className={`h-7 shrink-0 rounded-md border px-2.5 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
          listening ? "border-ember-400 bg-ember-500/20 text-ember-300" : "border-edge bg-surface-2 text-fg hover:bg-surface-3"
        }`}
      >
        {label}
      </button>
      {note && <span className="max-w-[18rem] truncate text-[11px] text-fg-muted">{note}</span>}
    </div>
  );
}
