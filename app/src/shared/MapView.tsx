// Map-grid view of the table, used by the console mini-map and (until the
// Phase 1 WebGL renderer lands) the projector. Draws in map coordinates via
// the SVG viewBox, so nothing here knows about screen or projector pixels.
//
// Virtual table mode: click empty map to add a token, drag a virtual token to
// move it, right-click it to remove it. These go through the same engine path
// real vision uses.

import { useRef } from "react";
import { send, useEngine } from "./engine";
import type { Token, TokenType } from "./protocol";
import { TOKEN_STYLE } from "./tokens";

const TOKEN_RADIUS = 6;
const HALO_RADIUS = 9;

interface Props {
  placeType: TokenType;
  showGrid?: boolean;
  className?: string;
}

export default function MapView({ placeType, showGrid = false, className }: Props) {
  const { hello, tokens } = useEngine();
  const size = hello?.map_size ?? 256;
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
    send({ type: "virtual_token_add", token_type: placeType, x, y, angle: 0 });
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
      viewBox={`0 0 ${size} ${size}`}
      className={className}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onContextMenu={(e) => e.preventDefault()}
    >
      <rect width={size} height={size} fill="#111" onPointerDown={onBackgroundDown} />
      {showGrid && <Grid size={size} />}
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

function Grid({ size }: { size: number }) {
  const step = size / 8;
  const lines = Array.from({ length: 7 }, (_, i) => (i + 1) * step);
  return (
    <g stroke="#262626" strokeWidth={0.5} className="pointer-events-none">
      {lines.map((p) => (
        <g key={p}>
          <line x1={p} y1={0} x2={p} y2={size} />
          <line x1={0} y1={p} x2={size} y2={p} />
        </g>
      ))}
    </g>
  );
}
