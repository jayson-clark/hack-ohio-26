// Plan mode's layer over the incident map (#123): the plan's draft orders,
// which can be placed, dragged and removed without touching the live fire,
// and what the plan changes: green where it keeps fire out by the horizon,
// red where it pushes fire in, faint orange for where the fire still goes.

import { useEffect, useRef } from "react";
import type { PlanState } from "../shared/engine";
import type { PlanOrderResult, TokenType } from "../shared/protocol";
import { aboutMinutes } from "../shared/places";
import { TOKEN_STYLE } from "../shared/tokens";
import type { MapSize } from "../shared/virtualTokens";
import type { DraftOrder } from "./plan";

interface Props {
  map: MapSize;
  drafts: DraftOrder[];
  /** What a click on empty map adds; null adds nothing. */
  tool: TokenType | null;
  grids: PlanState["grids"];
  /** The last result's orders, when they match the drafts one for one. */
  results: PlanOrderResult[] | null;
  crewReach: number;
  onAdd: (type: TokenType, x: number, y: number) => void;
  onMove: (id: string, x: number, y: number) => void;
  onRemove: (id: string) => void;
  onHover?: (p: { x: number; y: number } | null) => void;
}

export default function PlanOverlay(props: Props) {
  const { map, drafts, tool, grids, results, crewReach } = props;
  const svgRef = useRef<SVGSVGElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const dragging = useRef<string | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d")!;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (!grids || grids.width !== map.width || grids.height !== map.height) return;
    const img = ctx.createImageData(map.width, map.height);
    const { base, plan } = grids;
    for (let i = 0; i < base.length; i++) {
      const b = base[i] / 255;
      const p = plan[i] / 255;
      const o = i * 4;
      if (b - p > 0.1) {
        // Kept out of the fire by the plan.
        img.data.set([74, 222, 128, Math.round(Math.min(1, (b - p) * 1.2) * 190)], o);
      } else if (p - b > 0.1) {
        // Fire the plan pushes somewhere it wouldn't otherwise go.
        img.data.set([239, 68, 68, Math.round(Math.min(1, (p - b) * 1.2) * 190)], o);
      } else if (p > 0.05) {
        img.data.set([255, 138, 76, Math.round(p * 80)], o);
      }
    }
    ctx.putImageData(img, 0, 0);
  }, [grids, map.width, map.height]);

  function toMap(e: React.PointerEvent | React.MouseEvent) {
    const pt = new DOMPoint(e.clientX, e.clientY).matrixTransform(svgRef.current!.getScreenCTM()!.inverse());
    return {
      x: Math.min(Math.max(pt.x, 0), map.width),
      y: Math.min(Math.max(pt.y, 0), map.height),
    };
  }

  return (
    <>
      <canvas
        ref={canvasRef}
        width={map.width}
        height={map.height}
        className="pointer-events-none absolute inset-0 h-full w-full"
      />
      <svg
        ref={svgRef}
        viewBox={`0 0 ${map.width} ${map.height}`}
        preserveAspectRatio="none"
        className={`absolute inset-0 h-full w-full ${tool ? "cursor-crosshair" : ""}`}
        onPointerMove={(e) => {
          const p = toMap(e);
          props.onHover?.(p);
          if (dragging.current) props.onMove(dragging.current, p.x, p.y);
        }}
        onPointerUp={() => (dragging.current = null)}
        onPointerLeave={() => props.onHover?.(null)}
        onContextMenu={(e) => e.preventDefault()}
      >
        <rect
          width={map.width}
          height={map.height}
          fill="transparent"
          onPointerDown={(e) => {
            if (e.button !== 0 || !tool) return;
            const { x, y } = toMap(e);
            props.onAdd(tool, x, y);
          }}
        />
        {drafts.map((d, i) => {
          const r = results?.[i];
          const style = TOKEN_STYLE[d.token_type];
          const dead = r && !r.counted;
          return (
            <g
              key={d.id}
              transform={`translate(${d.x} ${d.y})`}
              className="cursor-grab active:cursor-grabbing"
              onPointerDown={(e) => {
                e.stopPropagation();
                if (e.button !== 0) return;
                dragging.current = d.id;
                svgRef.current!.setPointerCapture(e.pointerId);
              }}
              onContextMenu={(e) => {
                e.preventDefault();
                props.onRemove(d.id);
              }}
            >
              {d.token_type === "crew" && (
                <circle r={crewReach} fill="none" stroke={style.color} strokeOpacity={0.5} strokeWidth={0.5} strokeDasharray="1.5 1.5" />
              )}
              <circle r={5} fill="#0b0c0e" fillOpacity={0.85} stroke={dead ? "#ef4444" : style.color} strokeWidth={0.9} strokeDasharray="2 1" />
              <text
                textAnchor="middle"
                dominantBaseline="central"
                fontSize={5.5}
                fontWeight={700}
                fill={style.color}
                className="pointer-events-none select-none"
              >
                {i + 1}
              </text>
              {r && <EtaTag result={r} />}
            </g>
          );
        })}
      </svg>
    </>
  );
}

function EtaTag({ result }: { result: PlanOrderResult }) {
  const text = !result.counted ? "no unit free" : result.eta_min ? aboutMinutes(result.eta_min) : "now";
  const w = text.length * 2.3 + 3;
  return (
    <g transform="translate(7 -7)" className="pointer-events-none select-none">
      <rect width={w} height={5} rx={1.5} fill="#0b0c0e" opacity={0.85} />
      <text x={1.5} y={2.6} dominantBaseline="central" fontSize={3.6} fontWeight={600} fill={result.counted ? "#e8eaed" : "#f87171"}>
        {text}
      </text>
    </g>
  );
}
