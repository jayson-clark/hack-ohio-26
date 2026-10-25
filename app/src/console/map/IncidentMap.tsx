// The incident map (#130): the basemap and its layers, plus the floating
// controls an operator needs on it: order tools, layers, zoom, a legend and
// the wind. In Monitor a click with an order tool sends that unit; in Plan it
// adds a draft order; otherwise clicks select towns, orders and
// recommendations for the inspector.
//
// With the camera's top-down orthophoto live, the basemap can be the drone's
// photo instead (#203): the same layers and tools, over what's really there.

import { useState } from "react";
import { useEngine } from "../../shared/engine";
import { droneFeedLive, useFeedUrl } from "../../shared/feed";
import { compass, describeLocation } from "../../shared/places";
import type { ForecastEnvelope, TokenType } from "../../shared/protocol";
import { printWindow, type Scenario } from "../../shared/scenario";
import { useTheme } from "../../shared/theme";
import { ORDER_STYLE } from "../../shared/tokens";
import { addToken } from "../../shared/virtualTokens";
import { Icon } from "../icons";
import { findRec, ORDER_COLOR, ORDER_ICON, type Selection, type TownView } from "../model";
import { resultsFor, type DraftOrder } from "../plan";
import { Chip, Floating, IconButton, Segmented } from "../ui";
import { DroneLayer, FocusPulse, ForecastLayer, OrdersLayer, PlacesLayer, PlanLayer, RecsLayer, RoutesLayer, StationsLayer, TownsLayer, UnitsLayer } from "./layers";
import MapView, { type MapHandle } from "./MapView";

export type ConsoleMode = "monitor" | "plan" | "review";

export interface MapLayers {
  terrain: boolean;
  contours: boolean;
  forecast: boolean;
  routes: boolean;
  resources: boolean;
  labels: boolean;
}

export const DEFAULT_MAP_LAYERS: MapLayers = {
  terrain: true,
  contours: true,
  forecast: true,
  routes: true,
  resources: true,
  labels: true,
};

const LAYER_LABELS: Record<keyof MapLayers, string> = {
  terrain: "Terrain shading",
  contours: "Contours",
  forecast: "Fire forecast",
  routes: "Evacuation routes",
  resources: "Stations and units",
  labels: "Place names",
};

// Basemap styling the drone photo covers up.
const BASEMAP_ONLY: (keyof MapLayers)[] = ["terrain", "contours"];

type Basemap = "map" | "drone";

interface Props {
  scenario: Scenario;
  mode: ConsoleMode;
  towns: TownView[];
  layers: MapLayers;
  onLayers: (l: MapLayers) => void;
  tool: TokenType | null;
  onTool: (t: TokenType | null) => void;
  selection: Selection;
  onSelect: (s: Selection) => void;
  drafts: DraftOrder[];
  onDrafts: (update: (d: DraftOrder[]) => DraftOrder[]) => void;
  onAddDraft: (type: TokenType, x: number, y: number) => void;
  focus: { seq: number; x: number; y: number } | null;
  handle: React.RefObject<MapHandle | null>;
}

export default function IncidentMap(props: Props) {
  const { scenario, mode, towns, layers, tool, selection } = props;
  const { simGrid, forecast, envelope, routes, units, tokens, recommendations, hello, plan, scenario: live, score, vision, cameraFrame } = useEngine();
  const [hover, setHover] = useState<{ x: number; y: number } | null>(null);
  const [layersOpen, setLayersOpen] = useState(false);
  // The operator's pick, kept while the feed comes and goes: the drone photo
  // whenever it's live, unless they've switched to the map.
  const [basemap, setBasemap] = useState<Basemap>("drone");
  const feedLive = droneFeedLive(vision);
  // vision_status comes once a second and frames ten times, so also check each
  // frame has the print window's shape (what the camera sees, #197) before
  // laying it over the map.
  const win = printWindow(scenario);
  const ortho = feedLive && cameraFrame && Math.abs(cameraFrame.width / cameraFrame.height - win.w / win.h) < 0.02;
  const feedUrl = useFeedUrl(ortho ? cameraFrame : null);
  const drone = basemap === "drone" && feedLive && !!feedUrl;
  const theme = useTheme();
  const local = props.handle;
  const planning = mode === "plan";
  const reach = hello?.crew_radius ?? 14;
  // An ended exercise takes no orders (#128).
  const tools: TokenType[] =
    score?.phase === "ended" ? [] : planning ? ["crew", "firebreak", "water"] : mode === "monitor" ? ["crew", "firebreak", "water", "bus"] : [];
  const showForecast = layers.forecast && !(planning && plan.grids);
  const selTown = selection?.kind === "town" ? selection.name : null;

  function click(x: number, y: number) {
    if (tool && planning) return props.onAddDraft(tool, x, y);
    if (tool && mode === "monitor" && tools.length) return addToken(tool, x, y, scenario);
    props.onSelect(null);
  }

  return (
    <div className="relative h-full w-full">
      <MapView
        scenario={scenario}
        simGrid={simGrid}
        forecast={forecast}
        envelope={envelope}
        style={{ terrain: layers.terrain, contours: layers.contours, forecast: showForecast && !drone, dark: theme === "dark" }}
        onClick={click}
        onHover={setHover}
        cursor={tool ? "crosshair" : undefined}
        handle={local}
      >
        {(k) => (
          <>
            {drone && <DroneLayer scenario={scenario} url={feedUrl} />}
            {drone && showForecast && <ForecastLayer scenario={scenario} forecast={forecast} simGrid={simGrid} />}
            {layers.routes && <RoutesLayer routes={routes} k={k} highlight={selTown} />}
            {layers.labels && <PlacesLayer scenario={scenario} k={k} />}
            {layers.resources && <StationsLayer stations={hello?.stations ?? []} k={k} />}
            {/* With an order tool picked, clicks go to the map, not to what's under them. */}
            <g pointerEvents={tool ? "none" : undefined}>
            <TownsLayer towns={towns} k={k} selected={selTown} onSelect={(name) => props.onSelect({ kind: "town", name })} />
            {mode !== "review" && (
              <RecsLayer
                recs={recommendations}
                k={k}
                reach={reach}
                selected={selection?.kind === "rec" ? (findRec(recommendations, selection)?.id ?? null) : null}
                onSelect={(r) => props.onSelect({ kind: "rec", id: r.id, x: r.x, y: r.y })}
              />
            )}
            {layers.resources && <UnitsLayer units={units} k={k} />}
            <OrdersLayer
              tokens={tokens}
              k={k}
              reach={reach}
              selected={selection?.kind === "order" ? selection.id : null}
              onSelect={(id) => props.onSelect({ kind: "order", id })}
            />
            </g>
            {planning && (
              <PlanLayer
                scenario={scenario}
                k={k}
                grids={plan.grids}
                drafts={props.drafts}
                results={resultsFor(props.drafts, plan.result)}
                reach={reach}
                onMove={(id, x, y) => props.onDrafts((ds) => ds.map((d) => (d.id === id ? { ...d, x, y } : d)))}
                onRemove={(id) => props.onDrafts((ds) => ds.filter((d) => d.id !== id))}
              />
            )}
            <FocusPulse focus={props.focus} k={k} />
          </>
        )}
      </MapView>

      {/* Order tools */}
      {tools.length > 0 && (
        <div className="pointer-events-none absolute inset-x-0 top-4 flex justify-center">
          <Floating className="pointer-events-auto flex items-center gap-1 p-1">
            <span className="px-2 text-[11px] font-medium text-ink-3">{planning ? "Add to plan" : "Dispatch"}</span>
            <ToolButton active={tool === null} onClick={() => props.onTool(null)} icon="select" label="Select" hint="Esc" />
            <div className="mx-0.5 h-5 w-px bg-line" />
            {tools.map((t, i) => (
              <ToolButton
                key={t}
                active={tool === t}
                onClick={() => props.onTool(tool === t ? null : t)}
                icon={ORDER_ICON[t]}
                color={ORDER_COLOR[t]}
                label={ORDER_STYLE[t].label}
                hint={String(i + 1)}
              />
            ))}
          </Floating>
        </div>
      )}

      {/* Basemap, wind and layers, top right */}
      <div className="absolute right-4 top-4 flex flex-col items-end gap-2">
        <div className="flex items-center gap-2">
          {feedLive && (
            <Floating className="p-1">
              <span title="Basemap: the map, or the drone's live photo">
                <Segmented<Basemap>
                  value={basemap}
                  options={[
                    { value: "map", label: "Map" },
                    { value: "drone", label: "Drone" },
                  ]}
                  onChange={setBasemap}
                />
              </span>
            </Floating>
          )}
          <div className="relative">
            <Floating className="flex items-center p-1">
              <IconButton icon="layers" title="Map layers" active={layersOpen} onClick={() => setLayersOpen(!layersOpen)} />
            </Floating>
            {layersOpen && (
              <Floating className="absolute right-0 top-11 z-20 w-56 p-2">
                <div className="px-2 pb-1.5 pt-1 text-[11px] font-medium text-ink-3">Map layers</div>
                {(Object.keys(LAYER_LABELS) as (keyof MapLayers)[]).map((key) => {
                  const off = drone && BASEMAP_ONLY.includes(key);
                  return (
                    <label
                      key={key}
                      title={off ? "Not shown over the drone photo" : undefined}
                      className={`flex items-center gap-2.5 rounded-md px-2 py-1.5 text-[13px] ${off ? "text-ink-3" : "cursor-pointer text-ink hover:bg-hover"}`}
                    >
                      <input
                        type="checkbox"
                        checked={layers[key]}
                        disabled={off}
                        onChange={() => props.onLayers({ ...layers, [key]: !layers[key] })}
                        className="h-3.5 w-3.5 accent-accent"
                      />
                      {LAYER_LABELS[key]}
                    </label>
                  );
                })}
                <EnvelopeNote envelope={envelope} />
              </Floating>
            )}
          </div>
        </div>
        {basemap === "drone" && vision && vision.camera !== "off" && !feedLive && (
          <Chip>{vision.camera === "no_signal" ? "Drone feed lost" : "Drone feed paused (board not in view)"} · showing the map</Chip>
        )}
        <Floating className="flex flex-col p-1">
          <IconButton icon="plus" title="Zoom in" onClick={() => local.current?.zoomBy(1.6)} />
          <IconButton icon="minus" title="Zoom out" onClick={() => local.current?.zoomBy(1 / 1.6)} />
          <div className="mx-1.5 my-0.5 h-px bg-line" />
          <IconButton icon="fit" title="Fit the whole map" onClick={() => local.current?.fit()} />
        </Floating>
        {live && <WindRose speed={live.wind.speed_ms} from={live.wind.from_deg} />}
      </div>

      {/* Legend and cursor, bottom left */}
      <div className="pointer-events-none absolute bottom-4 left-4 flex flex-col items-start gap-2">
        <Legend planning={planning && !!plan.grids} drone={drone} />
        <div className="rounded-md bg-panel/90 px-2 py-1 text-[11px] text-ink-2 shadow-card tnum">
          {hover ? describeLocation(scenario, hover.x, hover.y) : "Drag to pan · scroll to zoom"}
        </div>
      </div>
    </div>
  );
}

function ToolButton(props: { active: boolean; onClick: () => void; icon: Parameters<typeof Icon>[0]["name"]; label: string; color?: string; hint: string }) {
  return (
    <button
      onClick={props.onClick}
      title={`${props.label} (${props.hint})`}
      className={`flex h-8 items-center gap-1.5 rounded-md px-2.5 text-[13px] font-medium transition-colors ${
        props.active ? "bg-accent-soft text-accent" : "text-ink-2 hover:bg-hover hover:text-ink"
      }`}
    >
      <Icon name={props.icon} size={15} style={props.color && !props.active ? { color: props.color } : undefined} />
      {props.label}
    </button>
  );
}

/** North-up wind indicator: the arrow points where the wind blows to. */
function WindRose({ speed, from }: { speed: number; from: number }) {
  return (
    <Floating className="flex items-center gap-2 py-1.5 pl-1.5 pr-3" >
      <span className="relative flex h-9 w-9 items-center justify-center rounded-full border border-line bg-sunken">
        <span className="absolute top-0.5 text-[8px] font-semibold text-ink-3">N</span>
        <span style={{ transform: `rotate(${from + 180}deg)` }} className="text-accent">
          <Icon name="navigation" size={16} strokeWidth={2} />
        </span>
      </span>
      <span className="leading-tight">
        <span className="block text-[11px] text-ink-3">Wind</span>
        <span className="block text-[13px] font-semibold text-ink tnum">
          {compass(from)} {speed.toFixed(0)} m/s
        </span>
      </span>
    </Floating>
  );
}

function Legend({ planning, drone }: { planning: boolean; drone: boolean }) {
  const [open, setOpen] = useState(true);
  return (
    <Floating className="pointer-events-auto w-52 overflow-hidden">
      <button onClick={() => setOpen(!open)} className="flex w-full items-center justify-between px-3 py-2 text-[11px] font-medium text-ink-2 hover:bg-hover">
        Legend
        <Icon name={open ? "chevronDown" : "chevronUp"} size={14} />
      </button>
      {open && (
        <div className="space-y-1.5 px-3 pb-3 text-[11px] text-ink-2">
          {drone ? (
            <div className="flex items-center gap-2">
              <span className="flex h-3 w-4 items-center justify-center">
                <span className="h-2 w-2 animate-pulse rounded-full bg-crit" />
              </span>
              Live drone photo
            </div>
          ) : (
            <>
              <Swatch fill="#e8451c" label="Active fire" />
              <Swatch fill="#8a807b" label="Burned" />
            </>
          )}
          {planning ? (
            <>
              <Swatch fill="#12b76a" label="Plan keeps fire out" />
              <Swatch fill="#d92d20" label="Plan pushes fire in" />
            </>
          ) : (
            <>
              <Swatch fill="#f5a35f" line="#cc5412" label="Likely fire in 30 min" />
              <Swatch fill="#fad38a" line="#cc850f" label="Likely fire in 60 min" />
            </>
          )}
          <div className="flex items-center gap-2 pt-0.5">
            <span className="flex gap-0.5">
              <span className="h-[3px] w-2.5 rounded bg-ok" />
              <span className="h-[3px] w-2.5 rounded bg-[#dc6803]" />
              <span className="h-[3px] w-2.5 rounded bg-crit" />
            </span>
            <span>Route clear, at risk, cut</span>
          </div>
        </div>
      )}
    </Floating>
  );
}

function Swatch({ fill, line, label }: { fill: string; line?: string; label: string }) {
  return (
    <div className="flex items-center gap-2">
      <span className="h-3 w-4 rounded-sm" style={{ background: fill, boxShadow: line ? `inset 0 0 0 1.5px ${line}` : undefined }} />
      {label}
    </div>
  );
}

/** How well the forecast outline keeps its promise (#12): the share of new
 * fire that recently fell outside it, against the target. Shown once the
 * engine has scored a few forecasts on this map. */
function EnvelopeNote({ envelope }: { envelope: ForecastEnvelope | null }) {
  if (!envelope || envelope.scored.every((n) => n < 3)) return null;
  const pct = (x: number | null) => (x == null ? "–" : `${Math.round(x * 100)}%`);
  const parts = envelope.horizons_min.map((h, i) => `${pct(envelope.miss_recent[i])} at ${h} min`);
  const over = envelope.miss_recent.some((m) => m != null && m > envelope.target_miss + 0.05);
  return (
    <p
      className={`mx-2 mt-1.5 border-t border-line pt-2 text-[11px] leading-snug ${over ? "text-warn" : "text-ink-3"}`}
      title="The outline is calibrated online: each forecast is checked when its time comes, and the outline widens or tightens to keep the miss rate near the target."
    >
      Forecast outline: {parts.join(", ")} of new fire fell outside it lately (target {pct(envelope.target_miss)}).
    </p>
  );
}
