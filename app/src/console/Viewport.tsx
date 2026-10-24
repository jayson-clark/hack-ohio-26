// The console's main view: the 3D virtual table or the flat projection, with
// floating toolbars and a cursor readout.

import { useState } from "react";
import type { BinaryFrame } from "../shared/binary";
import type { ForecastGrids } from "../shared/engine";
import type { Token } from "../shared/protocol";
import { elevationAt, latLonAt, type Scenario } from "../shared/scenario";
import { TOKEN_STYLE } from "../shared/tokens";
import type { PlaceType } from "../shared/virtualTokens";
import type { Layers } from "../render/projection";
import ProjectionView from "../render/ProjectionView";
import TableView, { type CameraCommand, type CameraPreset } from "../render/TableView";
import { CubeIcon, ProjectorIcon } from "./icons";
import { Chip, Segmented, ToggleGroup } from "./ui";

export type ViewMode = "table" | "projection";

interface Props {
  scenario: Scenario | null;
  error: string | null;
  mode: ViewMode;
  onModeChange: (m: ViewMode) => void;
  tokens: Token[];
  simGrid: BinaryFrame | null;
  forecast: ForecastGrids | null;
  layers: Layers;
  onToggleLayer: (k: keyof Layers) => void;
  placeType: PlaceType;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  camera: CameraCommand | null;
  onCameraPreset: (p: CameraPreset) => void;
}

const LAYER_LABELS: Record<keyof Layers, string> = {
  tint: "Topo",
  contours: "Contours",
  labels: "Labels",
  grid: "Grid",
};

const IGNITE_COLOR = "#f97316";

export default function Viewport(props: Props) {
  const { scenario, error, mode, layers, placeType } = props;
  const [hover, setHover] = useState<{ x: number; y: number } | null>(null);
  const [preset, setPreset] = useState<CameraPreset>("oblique");

  const viewProps = scenario && {
    scenario,
    tokens: props.tokens,
    simGrid: props.simGrid,
    forecast: props.forecast,
    layers,
    placeType,
    selectedId: props.selectedId,
    onSelect: props.onSelect,
    onHover: setHover,
  };

  return (
    <div className="relative h-full overflow-hidden rounded-xl border border-edge bg-black">
      {viewProps ? (
        mode === "table" ? (
          <TableView {...viewProps} camera={props.camera} />
        ) : (
          <div className="h-full px-6 pt-16 pb-14">
            <ProjectionView {...viewProps} showGlyphs />
          </div>
        )
      ) : (
        <div className="flex h-full items-center justify-center text-sm text-fg-subtle">
          {error ? <span className="font-mono text-red-400">{error}</span> : "Loading terrain…"}
        </div>
      )}

      <div className="pointer-events-none absolute inset-x-3 top-3 flex items-start justify-between gap-3">
        <div className="pointer-events-auto">
          <Segmented
            value={mode}
            onChange={props.onModeChange}
            options={[
              { value: "table", label: "Virtual table", icon: <CubeIcon /> },
              { value: "projection", label: "Projection", icon: <ProjectorIcon /> },
            ]}
          />
        </div>
        <div className="pointer-events-auto flex flex-wrap justify-end gap-2">
          {mode === "table" && (
            <Segmented
              value={preset}
              onChange={(p) => {
                setPreset(p);
                props.onCameraPreset(p);
              }}
              options={[
                { value: "oblique", label: "Oblique" },
                { value: "top", label: "Top" },
                { value: "low", label: "Low" },
              ]}
            />
          )}
          <ToggleGroup
            items={(Object.keys(LAYER_LABELS) as (keyof Layers)[]).map((k) => ({
              key: k,
              label: LAYER_LABELS[k],
              on: layers[k],
            }))}
            onToggle={props.onToggleLayer}
          />
        </div>
      </div>

      <div className="pointer-events-none absolute inset-x-3 bottom-3 flex items-end justify-between gap-3">
        <Chip className="font-mono tabular-nums">
          {scenario && hover ? <Readout scenario={scenario} x={hover.x} y={hover.y} /> : <span>—</span>}
        </Chip>
        <Chip className="hidden items-center gap-2 md:flex">
          <span
            className="h-2 w-2 rounded-full"
            style={{ background: placeType === "ignite" ? IGNITE_COLOR : TOKEN_STYLE[placeType].color }}
          />
          <span>
            {placeType === "ignite" ? (
              <>
                Click to <span className="text-fg">ignite</span>
              </>
            ) : (
              <>
                Click to place <span className="text-fg">{TOKEN_STYLE[placeType].label.toLowerCase()}</span>
              </>
            )}{" "}
            · drag to move · right-click to remove
            {mode === "table" && " · drag empty space to orbit"}
          </span>
        </Chip>
      </div>
    </div>
  );
}

function Readout({ scenario, x, y }: { scenario: Scenario; x: number; y: number }) {
  const { lat, lon } = latLonAt(scenario, x, y);
  return (
    <span className="flex gap-3">
      <span>
        <span className="text-fg-subtle">x</span> <span className="text-fg">{x.toFixed(1)}</span>{" "}
        <span className="text-fg-subtle">y</span> <span className="text-fg">{y.toFixed(1)}</span>
      </span>
      <span className="text-fg">{Math.round(elevationAt(scenario, x, y))} m</span>
      <span>
        {lat.toFixed(4)}°N {Math.abs(lon).toFixed(4)}°{lon < 0 ? "W" : "E"}
      </span>
    </span>
  );
}
