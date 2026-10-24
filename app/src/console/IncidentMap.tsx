// The operator's incident map: top-down, the fire as observed, the forecast,
// evacuation routes, units and orders. In Monitor mode a click with an order
// tool picked sends that unit; in Plan mode clicks edit the plan's draft
// orders instead, and the map shows what the plan changes.

import { useEffect, useState } from "react";
import { useEngine } from "../shared/engine";
import type { TokenType } from "../shared/protocol";
import { describeLocation } from "../shared/places";
import { elevationAt, latLonAt, type Scenario } from "../shared/scenario";
import { ORDER_STYLE, TOKEN_STYLE } from "../shared/tokens";
import type { PlaceType } from "../shared/virtualTokens";
import type { Layers } from "../render/projection";
import ProjectionView from "../render/ProjectionView";
import { EventAlerts } from "./EventLog";
import PlanOverlay from "./PlanOverlay";
import { resultsFor, type DraftOrder } from "./plan";
import { DispatchChip } from "./StationsPanel";
import { Chip, ToggleGroup } from "./ui";

export type ConsoleMode = "monitor" | "plan" | "review";

/** A point the map should draw attention to (a decision's "Show"). */
export interface Focus {
  seq: number;
  x: number;
  y: number;
}

interface Props {
  scenario: Scenario | null;
  error: string | null;
  mode: ConsoleMode;
  layers: Layers;
  onToggleLayer: (k: keyof Layers) => void;
  /** The order tool picked on the map's toolbar, or null to only look. */
  tool: TokenType | null;
  onTool: (t: TokenType | null) => void;
  drafts: DraftOrder[];
  onDrafts: (update: (d: DraftOrder[]) => DraftOrder[]) => void;
  onAddDraft: (type: TokenType, x: number, y: number) => void;
  focus: Focus | null;
}

const LAYER_LABELS: Partial<Record<keyof Layers, string>> = {
  tint: "Terrain",
  contours: "Contours",
  labels: "Labels",
  routes: "Routes",
  forecast: "Forecast",
};

export default function IncidentMap(props: Props) {
  const { scenario, error, mode, layers, tool, drafts } = props;
  const { tokens, simGrid, forecast, routes, plan, hello } = useEngine();
  const [hover, setHover] = useState<{ x: number; y: number } | null>(null);
  const planning = mode === "plan";
  // Review is for looking back: no orders from there.
  const tools: TokenType[] =
    mode === "plan" ? ["crew", "firebreak", "water"] : mode === "monitor" ? ["crew", "firebreak", "water", "bus"] : [];

  // In Plan mode the plan's own forecast replaces the live ghost once it's in.
  const shownLayers = planning && plan.grids ? { ...layers, forecast: false } : layers;
  const placeType: PlaceType | null = !planning && tool ? tool : null;

  return (
    <div className="relative h-full overflow-hidden rounded-xl border border-edge bg-black">
      {scenario ? (
        <div className="h-full px-4 pt-14 pb-12">
          <ProjectionView
            scenario={scenario}
            tokens={tokens}
            simGrid={simGrid}
            forecast={forecast}
            routes={routes}
            layers={shownLayers}
            placeType={placeType}
            selectedId={null}
            onHover={setHover}
            showGlyphs
          >
            {planning && (
              <PlanOverlay
                map={scenario}
                drafts={drafts}
                tool={tool}
                grids={plan.grids}
                results={resultsFor(drafts, plan.result)}
                crewReach={hello?.crew_radius ?? 14}
                onAdd={props.onAddDraft}
                onMove={(id, x, y) => props.onDrafts((ds) => ds.map((d) => (d.id === id ? { ...d, x, y } : d)))}
                onRemove={(id) => props.onDrafts((ds) => ds.filter((d) => d.id !== id))}
                onHover={setHover}
              />
            )}
            <FocusRing map={scenario} focus={props.focus} />
          </ProjectionView>
        </div>
      ) : (
        <div className="flex h-full items-center justify-center text-sm text-fg-subtle">
          {error ? <span className="font-mono text-red-400">{error}</span> : "Loading map…"}
        </div>
      )}

      <div className="pointer-events-none absolute inset-x-3 top-3 flex items-start justify-between gap-3">
        <div className={`pointer-events-auto flex items-center gap-2 ${tools.length ? "" : "invisible"}`}>
          <div className="flex rounded-lg border border-edge bg-surface-1/85 p-0.5 shadow-lg shadow-black/30 backdrop-blur">
            <ToolButton active={tool === null} onClick={() => props.onTool(null)} label="Look" hint="Esc" />
            {tools.map((t, i) => (
              <ToolButton
                key={t}
                active={tool === t}
                onClick={() => props.onTool(tool === t ? null : t)}
                label={ORDER_STYLE[t].label}
                color={TOKEN_STYLE[t].color}
                hint={String(i + 1)}
              />
            ))}
          </div>
        </div>
        <div className="pointer-events-auto">
          <ToggleGroup
            items={(Object.keys(LAYER_LABELS) as (keyof Layers)[]).map((k) => ({
              key: k,
              label: LAYER_LABELS[k]!,
              on: layers[k],
            }))}
            onToggle={props.onToggleLayer}
          />
        </div>
      </div>

      {!planning && <DispatchChip />}
      <EventAlerts />

      <div className="pointer-events-none absolute inset-x-3 bottom-3 flex items-end justify-between gap-3">
        <Chip className="font-mono tabular-nums">
          {scenario && hover ? <Readout scenario={scenario} x={hover.x} y={hover.y} /> : <span>—</span>}
        </Chip>
        <Chip className="hidden md:block">{planning ? <PlanLegend tool={tool} /> : <MonitorLegend tool={tool} />}</Chip>
      </div>
    </div>
  );
}

function ToolButton(props: { active: boolean; onClick: () => void; label: string; color?: string; hint: string }) {
  return (
    <button
      onClick={props.onClick}
      title={`${props.label} (${props.hint})`}
      className={`flex h-7 items-center gap-1.5 rounded-md px-2.5 text-xs font-medium transition-colors ${
        props.active ? "bg-surface-3 text-fg" : "text-fg-muted hover:text-fg"
      }`}
    >
      {props.color && <span className="h-2 w-2 rounded-full" style={{ background: props.color }} />}
      {props.label}
    </button>
  );
}

function MonitorLegend({ tool }: { tool: TokenType | null }) {
  if (tool) {
    return (
      <span>
        Click the map to <span className="text-fg">{ORDER_STYLE[tool].verb.toLowerCase()}</span> there · drag an
        order to move it · right-click to cancel it
      </span>
    );
  }
  return (
    <span className="flex items-center gap-3">
      <span className="flex items-center gap-1.5">
        <span className="h-2 w-3 rounded-sm border border-amber-300/80" /> Forecast 30 / 60 min
      </span>
      <span className="flex items-center gap-1.5">
        <span className="h-0.5 w-3 rounded bg-emerald-400" /> Route clear
      </span>
      <span className="flex items-center gap-1.5">
        <span className="h-0.5 w-3 rounded bg-yellow-400" /> At risk
      </span>
      <span className="flex items-center gap-1.5">
        <span className="h-0.5 w-3 rounded bg-red-500" /> Cut
      </span>
    </span>
  );
}

function PlanLegend({ tool }: { tool: TokenType | null }) {
  return (
    <span className="flex items-center gap-3">
      {tool ? (
        <span>
          Click to add a <span className="text-fg">{ORDER_STYLE[tool].label.toLowerCase()}</span> to the plan
        </span>
      ) : (
        <span>Pick an order type to add to the plan · drag to move · right-click to remove</span>
      )}
      <span className="flex items-center gap-1.5">
        <span className="h-2 w-3 rounded-sm bg-emerald-400/70" /> Kept from fire
      </span>
      <span className="flex items-center gap-1.5">
        <span className="h-2 w-3 rounded-sm bg-red-500/70" /> Fire pushed in
      </span>
    </span>
  );
}

const FOCUS_MS = 2600;

/** A ring that pulses where a decision's "Show" points, then fades. */
function FocusRing({ map, focus }: { map: { width: number; height: number }; focus: Focus | null }) {
  const [shown, setShown] = useState<Focus | null>(null);
  useEffect(() => {
    if (!focus) return;
    setShown(focus);
    const t = window.setTimeout(() => setShown(null), FOCUS_MS);
    return () => clearTimeout(t);
  }, [focus]);
  if (!shown) return null;
  return (
    <svg
      viewBox={`0 0 ${map.width} ${map.height}`}
      preserveAspectRatio="none"
      className="pointer-events-none absolute inset-0 h-full w-full"
    >
      <circle key={shown.seq} cx={shown.x} cy={shown.y} r={10} fill="none" stroke="#fff" strokeWidth={0.8}>
        <animate attributeName="r" values="22;8;12;8" dur="1.2s" repeatCount="2" />
        <animate attributeName="opacity" values="0;1;1;0.6" dur="1.2s" repeatCount="2" />
      </circle>
    </svg>
  );
}

function Readout({ scenario, x, y }: { scenario: Scenario; x: number; y: number }) {
  const { lat, lon } = latLonAt(scenario, x, y);
  return (
    <span className="flex gap-3">
      <span className="text-fg">{describeLocation(scenario, x, y)}</span>
      <span>{Math.round(elevationAt(scenario, x, y))} m</span>
      <span>
        {lat.toFixed(4)}°N {Math.abs(lon).toFixed(4)}°{lon < 0 ? "W" : "E"}
      </span>
    </span>
  );
}
