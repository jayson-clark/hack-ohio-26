// Map-grid view of the table, used by the console mini-map and (until the
// Phase 1 WebGL renderer lands) the projector. Draws in map coordinates via
// the SVG viewBox, so nothing here knows about screen or projector pixels.
//
// Virtual table mode: click empty map to add a token, drag a virtual token to
// move it, right-click it to remove it. These go through the same engine path
// real vision uses. With placeType "ignite", a click lights the fire instead.
//
// The fire is drawn as one pixelated <image> under the tokens, rebuilt from
// the sim_grid and forecast_grid frames. It's a stopgap until the WebGL
// projector renderer; the console mini-map can keep using it.

import { useMemo, useRef } from "react";
import { Cell, type ForecastGrids, type Grid, send, useEngine } from "./engine";
import type { Token, TokenType } from "./protocol";
import { TOKEN_STYLE } from "./tokens";

const TOKEN_RADIUS = 6;
const HALO_RADIUS = 9;

export type PlaceType = TokenType | "ignite";

interface Props {
  placeType: PlaceType;
  showGrid?: boolean;
  className?: string;
}

export default function MapView({ placeType, showGrid = false, className }: Props) {
  const { hello, tokens, simGrid, forecast } = useEngine();
  // The map isn't square (Paradise is 256 x 192); size comes from the engine.
  const width = hello?.map_width ?? 256;
  const height = hello?.map_height ?? 192;
  const svgRef = useRef<SVGSVGElement>(null);
  const dragging = useRef<string | null>(null);
  const pendingMove = useRef<{ id: string; x: number; y: number } | null>(null);

  function toMap(e: React.PointerEvent | React.MouseEvent) {
    const svg = svgRef.current!;
    const pt = new DOMPoint(e.clientX, e.clientY).matrixTransform(svg.getScreenCTM()!.inverse());
    return { x: pt.x, y: pt.y };
  }

  function flushMove() {
    const move = pendingMove.current;
    pendingMove.current = null;
    if (move) send({ type: "virtual_token_move", ...move, angle: null });
  }

  function onBackgroundDown(e: React.PointerEvent) {
    if (e.button !== 0) return;
    const { x, y } = toMap(e);
    if (placeType === "ignite") send({ type: "ignite", x, y });
    else send({ type: "virtual_token_add", token_type: placeType, x, y, angle: 0 });
  }

  function onTokenDown(e: React.PointerEvent, token: Token) {
    e.stopPropagation();
    if (e.button !== 0 || token.source !== "virtual") return;
    dragging.current = token.id;
    svgRef.current!.setPointerCapture(e.pointerId);
  }

  function onPointerMove(e: React.PointerEvent) {
    if (!dragging.current) return;
    // Coalesce to one move message per animation frame.
    if (!pendingMove.current) requestAnimationFrame(flushMove);
    pendingMove.current = { id: dragging.current, ...toMap(e) };
  }

  function onPointerUp() {
    dragging.current = null;
  }

  function onTokenContextMenu(e: React.MouseEvent, token: Token) {
    e.preventDefault();
    if (token.source === "virtual") send({ type: "virtual_token_remove", id: token.id });
  }

  return (
    <svg
      ref={svgRef}
      viewBox={`0 0 ${width} ${height}`}
      className={className}
      style={{ aspectRatio: `${width} / ${height}` }}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onContextMenu={(e) => e.preventDefault()}
    >
      <rect width={width} height={height} fill="#111" onPointerDown={onBackgroundDown} />
      <FireLayer grid={simGrid} forecast={forecast} />
      {showGrid && <GridLines width={width} height={height} />}
      {tokens.map((t) => {
        const style = TOKEN_STYLE[t.token_type];
        return (
          <g
            key={t.id}
            transform={`translate(${t.x} ${t.y})`}
            className={t.source === "virtual" ? "cursor-grab" : undefined}
            onPointerDown={(e) => onTokenDown(e, t)}
            onContextMenu={(e) => onTokenContextMenu(e, t)}
          >
            {/* White halo keeps the physical marker high-contrast under projected light. */}
            <circle r={HALO_RADIUS} fill="white" />
            <circle r={TOKEN_RADIUS} fill={style.color} />
            <text
              textAnchor="middle"
              dominantBaseline="central"
              fontSize={7}
              fontWeight="bold"
              fill="#111"
              className="pointer-events-none select-none"
            >
              {style.letter}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

// RGBA per cell state. Fuel is a dim olive so the map reads as land.
const CELL_RGBA: Record<number, [number, number, number, number]> = {
  [Cell.Unburnable]: [40, 40, 44, 255],
  [Cell.Fuel]: [28, 38, 26, 255],
  [Cell.Burning]: [255, 110, 20, 255],
  [Cell.Burned]: [8, 6, 5, 255],
};
// Forecast ghost on unburned fuel: nearer horizon in orange, further in yellow.
const GHOST_RGB: [number, number, number][] = [
  [255, 120, 40],
  [250, 210, 80],
];
const GHOST_ALPHA = [0.55, 0.3];

function FireLayer({ grid, forecast }: { grid: Grid | null; forecast: ForecastGrids | null }) {
  const href = useMemo(() => (grid ? renderFire(grid, forecast) : null), [grid, forecast]);
  if (!grid || !href) return null;
  return (
    <image
      href={href}
      width={grid.width}
      height={grid.height}
      preserveAspectRatio="none"
      style={{ imageRendering: "pixelated" }}
      className="pointer-events-none"
    />
  );
}

function renderFire(grid: Grid, forecast: ForecastGrids | null): string | null {
  const { width, height, cells } = grid;
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;
  const img = ctx.createImageData(width, height);
  const px = img.data;
  const ghost = forecast && forecast.width === width && forecast.height === height ? forecast.horizons : [];
  for (let i = 0; i < cells.length; i++) {
    const c = cells[i];
    let [r, g, b] = CELL_RGBA[c] ?? CELL_RGBA[Cell.Fuel];
    if (c === Cell.Fuel) {
      // Draw the furthest horizon first so the nearer one sits on top.
      for (let h = ghost.length - 1; h >= 0; h--) {
        const a = (ghost[h][i] / 255) * (GHOST_ALPHA[h] ?? 0.3);
        const [gr, gg, gb] = GHOST_RGB[h] ?? GHOST_RGB[GHOST_RGB.length - 1];
        r += (gr - r) * a;
        g += (gg - g) * a;
        b += (gb - b) * a;
      }
    }
    px[i * 4] = r;
    px[i * 4 + 1] = g;
    px[i * 4 + 2] = b;
    px[i * 4 + 3] = 255;
  }
  ctx.putImageData(img, 0, 0);
  return canvas.toDataURL();
}

// Grid lines every 32 cells.
function GridLines({ width, height }: { width: number; height: number }) {
  const step = 32;
  const xs = Array.from({ length: Math.ceil(width / step) - 1 }, (_, i) => (i + 1) * step);
  const ys = Array.from({ length: Math.ceil(height / step) - 1 }, (_, i) => (i + 1) * step);
  return (
    <g stroke="#262626" strokeWidth={0.5} className="pointer-events-none">
      {xs.map((x) => (
        <line key={`x${x}`} x1={x} y1={0} x2={x} y2={height} />
      ))}
      {ys.map((y) => (
        <line key={`y${y}`} x1={0} y1={y} x2={width} y2={y} />
      ))}
    </g>
  );
}
