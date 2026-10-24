// Transparent SVG over a flat projection view. Handles virtual table input in
// map coordinates (via the viewBox), and optionally draws token glyphs for the
// console. The projector window keeps it invisible: the shader draws halos.
//
// Click empty map to add a token, drag a virtual token to move it, right-click
// it to remove it.

import { useMemo, useRef } from "react";
import { UNIT_STATUS, unitFor } from "../shared/dispatch";
import { useEngine } from "../shared/engine";
import type { Token, UnitInfo } from "../shared/protocol";
import { formatSimMinutes } from "../shared/round";
import { HALO_RADIUS, TOKEN_RADIUS, TOKEN_STYLE } from "../shared/tokens";
import { createMover, place, removeToken, type MapSize, type PlaceType } from "../shared/virtualTokens";

interface Props {
  map: MapSize;
  tokens: Token[];
  placeType: PlaceType;
  showGlyphs?: boolean;
  onSelect?: (id: string | null) => void;
  onHover?: (p: { x: number; y: number } | null) => void;
  /** Screen -> map, for a calibrated projector: a CSS matrix3d has no usable getScreenCTM. */
  toMap?: (clientX: number, clientY: number) => { x: number; y: number };
}

export default function MapOverlay({
  map,
  tokens,
  placeType,
  showGlyphs = false,
  onSelect,
  onHover,
  toMap: screenToMap,
}: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  const dragging = useRef<string | null>(null);
  const move = useMemo(() => createMover(map), [map]);
  const { units } = useEngine();

  function toMap(e: React.PointerEvent | React.MouseEvent) {
    if (screenToMap) return screenToMap(e.clientX, e.clientY);
    const svg = svgRef.current!;
    const pt = new DOMPoint(e.clientX, e.clientY).matrixTransform(svg.getScreenCTM()!.inverse());
    return { x: pt.x, y: pt.y };
  }

  function onBackgroundDown(e: React.PointerEvent) {
    if (e.button !== 0) return;
    const { x, y } = toMap(e);
    place(placeType, x, y, map);
    onSelect?.(null);
  }

  function onTokenDown(e: React.PointerEvent, token: Token) {
    e.stopPropagation();
    if (e.button !== 0) return;
    onSelect?.(token.id);
    if (token.source !== "virtual") return;
    dragging.current = token.id;
    svgRef.current!.setPointerCapture(e.pointerId);
  }

  function onPointerMove(e: React.PointerEvent) {
    const p = toMap(e);
    onHover?.(p);
    if (dragging.current) move(dragging.current, p.x, p.y);
  }

  function onTokenContextMenu(e: React.MouseEvent, token: Token) {
    e.preventDefault();
    if (token.source === "virtual") removeToken(token.id);
  }

  return (
    <svg
      ref={svgRef}
      viewBox={`0 0 ${map.width} ${map.height}`}
      preserveAspectRatio="none"
      className="absolute inset-0 h-full w-full"
      onPointerMove={onPointerMove}
      onPointerUp={() => (dragging.current = null)}
      onPointerLeave={() => onHover?.(null)}
      onContextMenu={(e) => e.preventDefault()}
    >
      <rect width={map.width} height={map.height} fill="transparent" onPointerDown={onBackgroundDown} />
      {tokens.map((t) => (
        <g
          key={t.id}
          transform={`translate(${t.x} ${t.y})`}
          className={t.source === "virtual" ? "cursor-grab active:cursor-grabbing" : "cursor-pointer"}
          onPointerDown={(e) => onTokenDown(e, t)}
          onContextMenu={(e) => onTokenContextMenu(e, t)}
        >
          <circle r={HALO_RADIUS + 1.6} fill="transparent" />
          {showGlyphs && (
            <>
              <circle r={TOKEN_RADIUS} fill="#0b0c0e" opacity={0.85} />
              <text
                textAnchor="middle"
                dominantBaseline="central"
                fontSize={7}
                fontWeight={700}
                fill={TOKEN_STYLE[t.token_type].color}
                className="pointer-events-none select-none"
              >
                {TOKEN_STYLE[t.token_type].letter}
              </text>
              <OrderTag unit={unitFor(t, units)} />
            </>
          )}
        </g>
      ))}
    </svg>
  );
}

/** A small tag beside an order token (#109) while its unit isn't on scene:
 * the arrival time, or why it can't come. Console only: on the projector the
 * table would need the calibration transform, which this overlay doesn't have. */
function OrderTag({ unit }: { unit: UnitInfo | undefined }) {
  if (!unit || unit.status === "working" || unit.status === "available") return null;
  const text =
    unit.status === "en_route"
      ? unit.eta_min != null
        ? formatSimMinutes(unit.eta_min)
        : "en route"
      : UNIT_STATUS[unit.status].label.toLowerCase();
  const w = text.length * 2.3 + 3;
  return (
    <g transform={`translate(${HALO_RADIUS + 3} ${-HALO_RADIUS})`} className="pointer-events-none select-none">
      <rect width={w} height={5} rx={1.5} fill="#0b0c0e" opacity={0.85} />
      <text x={1.5} y={2.6} dominantBaseline="central" fontSize={3.6} fontWeight={600} fill={UNIT_STATUS[unit.status].color}>
        {text}
      </text>
    </g>
  );
}
