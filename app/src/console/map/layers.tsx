// Vector layers over the console map (#130), in map cells. Every size is
// given in screen pixels times `k` (cells per pixel), so symbols and text
// stay the same size at any zoom, and strokes don't scale.

import { useEffect, useRef, useState, type ReactNode } from "react";
import type { Recommendation, RouteInfo, StationInfo, Token, TokenType, UnitInfo } from "../../shared/protocol";
import { aboutMinutes } from "../../shared/places";
import type { Scenario } from "../../shared/scenario";
import { Icon } from "../icons";
import { ORDER_COLOR, ORDER_ICON, type TownView } from "../model";
import { TONE } from "../ui";

const NS = { vectorEffect: "non-scaling-stroke" as const };
const HALO = { paintOrder: "stroke" as const, stroke: "var(--color-panel)", strokeLinejoin: "round" as const };

/** Text with a halo in the panel color, sized in pixels. */
function MapText(props: {
  x: number;
  y: number;
  k: number;
  size?: number;
  weight?: number;
  color?: string;
  anchor?: "start" | "middle" | "end";
  children: ReactNode;
}) {
  const size = props.size ?? 12;
  return (
    <text
      x={props.x}
      y={props.y}
      fontSize={size * props.k}
      fontWeight={props.weight ?? 500}
      fill={props.color ?? "var(--color-ink)"}
      textAnchor={props.anchor ?? "start"}
      dominantBaseline="central"
      strokeWidth={3.5 * props.k}
      style={HALO}
      className="pointer-events-none select-none"
    >
      {props.children}
    </text>
  );
}

/** An icon from the console set, centered at (x, y), `px` pixels across. */
function MapIcon({ name, x, y, k, px, color }: { name: Parameters<typeof Icon>[0]["name"]; x: number; y: number; k: number; px: number; color: string }) {
  return (
    <g transform={`translate(${x - (px * k) / 2} ${y - (px * k) / 2}) scale(${(px * k) / 24})`} className="pointer-events-none" color={color}>
      <Icon name={name} size={24} strokeWidth={2} />
    </g>
  );
}

export function PlacesLayer({ scenario, k }: { scenario: Scenario; k: number }) {
  const towns = new Set(scenario.towns.map((t) => t.name));
  return (
    <g>
      {scenario.info.places
        .filter((p) => !towns.has(p.name) && !/origin/i.test(p.name))
        .map((p) => (
          <g key={p.name}>
            <circle cx={p.map[0]} cy={p.map[1]} r={2 * k} fill="var(--color-ink-3)" />
            <MapText x={p.map[0] + 5 * k} y={p.map[1]} k={k} size={11} weight={400} color="var(--color-ink-3)">
              {p.name}
            </MapText>
          </g>
        ))}
    </g>
  );
}

export function RoutesLayer({ routes, k, highlight }: { routes: RouteInfo[]; k: number; highlight: string | null }) {
  const color = { clear: TONE.ok.hex, risky: "var(--color-risky)", cut: TONE.crit.hex };
  const towns = routes.filter((r) => !r.bus && r.points.length > 1);
  const pts = (r: RouteInfo) => r.points.map((p) => p.join(",")).join(" ");
  return (
    <g className="pointer-events-none" fill="none" strokeLinecap="round" strokeLinejoin="round">
      {towns.map((r) => (
        <polyline key={`c${r.town}`} points={pts(r)} stroke="var(--color-panel)" strokeWidth={r.town === highlight ? 7 : 5} {...NS} />
      ))}
      {towns.map((r) => (
        <polyline
          key={r.town}
          points={pts(r)}
          stroke={color[r.status]}
          strokeWidth={r.town === highlight ? 4 : 2.5}
          strokeDasharray={r.status === "cut" ? "6 5" : undefined}
          opacity={highlight && r.town !== highlight ? 0.45 : 0.95}
          {...NS}
        />
      ))}
      {towns.map((r) => {
        const end = r.points[r.points.length - 1];
        return r.safe_zone && r.status !== "cut" ? (
          <g key={`e${r.town}`}>
            <circle cx={end[0]} cy={end[1]} r={4 * k} fill="var(--color-panel)" stroke={color[r.status]} strokeWidth={2} {...NS} />
          </g>
        ) : null;
      })}
    </g>
  );
}

export function TownsLayer({
  towns,
  k,
  selected,
  onSelect,
}: {
  towns: TownView[];
  k: number;
  selected: string | null;
  onSelect: (name: string) => void;
}) {
  return (
    <g>
      {towns.map((t) => {
        const tone = TONE[t.tone];
        const active = t.tone === "crit" || t.tone === "warn";
        const sel = t.name === selected;
        const pick = (e: React.PointerEvent) => {
          e.stopPropagation();
          onSelect(t.name);
        };
        return (
          <g key={t.name} className="cursor-pointer" onPointerDown={pick}>
            <circle
              cx={t.x}
              cy={t.y}
              r={t.radius}
              fill={active ? tone.hex : "var(--color-ink-2)"}
              fillOpacity={active ? 0.06 : 0.03}
              stroke={sel ? "var(--color-accent)" : active ? tone.hex : "var(--color-line-strong)"}
              strokeWidth={sel ? 2.5 : 1.25}
              strokeDasharray={active || sel ? undefined : "3 3"}
              {...NS}
            />
            <rect
              x={t.x - 4.5 * k}
              y={t.y - 4.5 * k}
              width={9 * k}
              height={9 * k}
              rx={2 * k}
              fill="var(--color-panel)"
              stroke={active ? tone.hex : "var(--color-ink-2)"}
              strokeWidth={2}
              {...NS}
            />
            <MapText x={t.x + 9 * k} y={t.y - (t.eta ? 6 : 0) * k} k={k} size={13} weight={600}>
              {t.name}
            </MapText>
            {t.eta && (
              <MapText x={t.x + 9 * k} y={t.y + 9 * k} k={k} size={11} weight={600} color={active ? tone.hex : "var(--color-ink-2)"}>
                {t.eta}
              </MapText>
            )}
          </g>
        );
      })}
    </g>
  );
}

export function StationsLayer({ stations, k }: { stations: StationInfo[]; k: number }) {
  return (
    <g>
      {stations.map((s) => (
        <g key={s.name}>
          <title>{s.name}</title>
          <rect x={s.x - 6.5 * k} y={s.y - 6.5 * k} width={13 * k} height={13 * k} rx={3 * k} fill="var(--color-panel)" fillOpacity={0.9} stroke="var(--color-line-strong)" strokeWidth={1} {...NS} />
          <MapIcon name={s.kind === "air" ? "air" : "home"} x={s.x} y={s.y} k={k} px={9} color="var(--color-ink-3)" />
        </g>
      ))}
    </g>
  );
}

export function UnitsLayer({ units, k }: { units: UnitInfo[]; k: number }) {
  const moving = units.filter((u) => u.status === "en_route" || u.status === "blocked" || u.status === "grounded");
  // A working crew's cut line (#99, #159): a fuel break along the wind that
  // grows from the crew while it works, so the operator can see what the
  // fire is bending around.
  const lines = units.filter((u) => u.status === "working" && u.line.length === 2);
  return (
    <g className="pointer-events-none">
      {lines.map((u) => (
        <g key={`l${u.id}`}>
          <line x1={u.line[0][0]} y1={u.line[0][1]} x2={u.line[1][0]} y2={u.line[1][1]} stroke="var(--color-panel)" strokeWidth={5} strokeLinecap="round" {...NS} />
          <line x1={u.line[0][0]} y1={u.line[0][1]} x2={u.line[1][0]} y2={u.line[1][1]} stroke={ORDER_COLOR[u.token_type]} strokeWidth={3} strokeLinecap="round" {...NS}>
            <title>{`${u.id}: cut line`}</title>
          </line>
        </g>
      ))}
      {moving.map((u) =>
        u.path.length > 1 ? (
          <polyline
            key={`p${u.id}`}
            points={u.path.map((p) => p.join(",")).join(" ")}
            fill="none"
            stroke={ORDER_COLOR[u.token_type]}
            strokeOpacity={0.55}
            strokeWidth={1.5}
            strokeDasharray="4 4"
            {...NS}
          />
        ) : null,
      )}
      {moving.map((u) => (
        <g key={u.id}>
          <circle cx={u.x} cy={u.y} r={6 * k} fill={ORDER_COLOR[u.token_type]} stroke="var(--color-panel)" strokeWidth={2} {...NS} />
          {u.eta_min != null && (
            <MapText x={u.x + 9 * k} y={u.y} k={k} size={11} weight={600} color={ORDER_COLOR[u.token_type]}>
              {aboutMinutes(u.eta_min)}
            </MapText>
          )}
        </g>
      ))}
    </g>
  );
}

export function OrdersLayer({
  tokens,
  k,
  reach,
  selected,
  onSelect,
}: {
  tokens: Token[];
  k: number;
  reach: number;
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  return (
    <g>
      {tokens.map((t) => {
        const c = ORDER_COLOR[t.token_type];
        const sel = t.id === selected;
        return (
          <g
            key={t.id}
            className="cursor-pointer"
            onPointerDown={(e) => {
              e.stopPropagation();
              onSelect(t.id);
            }}
          >
            {t.token_type === "crew" && (
              <circle cx={t.x} cy={t.y} r={reach} fill={c} fillOpacity={0.06} stroke={c} strokeOpacity={0.5} strokeWidth={1} strokeDasharray="3 3" {...NS} />
            )}
            {sel && <circle cx={t.x} cy={t.y} r={17 * k} fill="none" stroke="var(--color-accent)" strokeWidth={2} {...NS} />}
            <rect x={t.x - 11 * k} y={t.y - 11 * k} width={22 * k} height={22 * k} rx={6 * k} fill="var(--color-panel)" stroke={c} strokeWidth={2} {...NS} />
            <MapIcon name={ORDER_ICON[t.token_type]} x={t.x} y={t.y} k={k} px={13} color={c} />
          </g>
        );
      })}
    </g>
  );
}

export function RecsLayer({
  recs,
  k,
  reach,
  selected,
  onSelect,
}: {
  recs: Recommendation[];
  k: number;
  reach: number;
  selected: string | null;
  onSelect: (r: Recommendation) => void;
}) {
  return (
    <g>
      {recs.map((r, i) => {
        const sel = r.id === selected;
        return (
          <g
            key={r.id}
            className="cursor-pointer"
            onPointerDown={(e) => {
              e.stopPropagation();
              onSelect(r);
            }}
          >
            <circle cx={r.x} cy={r.y} r={reach} fill="var(--color-accent)" fillOpacity={sel ? 0.1 : 0.04} stroke="var(--color-accent)" strokeWidth={sel ? 2 : 1.25} strokeDasharray="5 4" {...NS} />
            {r.action === "move" && r.from_x != null && r.from_y != null && (
              <line x1={r.from_x} y1={r.from_y} x2={r.x} y2={r.y} stroke="var(--color-accent)" strokeWidth={1.5} strokeDasharray="2 3" {...NS} />
            )}
            <circle cx={r.x} cy={r.y} r={10 * k} fill="var(--color-panel)" stroke="var(--color-accent)" strokeWidth={2} {...NS} />
            <MapText x={r.x} y={r.y} k={k} size={11} weight={700} color="var(--color-accent)" anchor="middle">
              {i + 1}
            </MapText>
          </g>
        );
      })}
    </g>
  );
}

const FOCUS_MS = 2400;

export function FocusPulse({ focus, k }: { focus: { seq: number; x: number; y: number } | null; k: number }) {
  const [shown, setShown] = useState(focus);
  useEffect(() => {
    if (!focus) return;
    setShown(focus);
    const t = window.setTimeout(() => setShown(null), FOCUS_MS);
    return () => clearTimeout(t);
  }, [focus]);
  if (!shown) return null;
  return (
    <circle key={shown.seq} cx={shown.x} cy={shown.y} r={14 * k} fill="none" stroke="var(--color-accent)" strokeWidth={2} {...NS} className="pointer-events-none">
      <animate attributeName="r" values={`${40 * k};${14 * k};${20 * k};${14 * k}`} dur="1.1s" repeatCount="2" />
      <animate attributeName="opacity" values="0;1;0.8;0" dur="1.1s" repeatCount="2" />
    </circle>
  );
}

/** Plan mode (#123): what the plan changes, and its draggable draft orders. */
export function PlanLayer({
  scenario,
  k,
  grids,
  drafts,
  results,
  reach,
  onMove,
  onRemove,
}: {
  scenario: Scenario;
  k: number;
  grids: { width: number; height: number; base: Uint8Array; plan: Uint8Array } | null;
  drafts: { id: string; token_type: TokenType; x: number; y: number }[];
  results: { counted: boolean; eta_min: number | null }[] | null;
  reach: number;
  onMove: (id: string, x: number, y: number) => void;
  onRemove: (id: string) => void;
}) {
  const [href, setHref] = useState<string | null>(null);
  const dragging = useRef<string | null>(null);

  useEffect(() => {
    if (!grids || grids.width !== scenario.width || grids.height !== scenario.height) return setHref(null);
    const c = document.createElement("canvas");
    c.width = grids.width;
    c.height = grids.height;
    const ctx = c.getContext("2d")!;
    const img = ctx.createImageData(grids.width, grids.height);
    for (let i = 0; i < grids.base.length; i++) {
      const d = (grids.base[i] - grids.plan[i]) / 255;
      const o = i * 4;
      if (d > 0.1) img.data.set([18, 183, 106, Math.round(Math.min(1, d * 1.3) * 170)], o);
      else if (d < -0.1) img.data.set([217, 45, 32, Math.round(Math.min(1, -d * 1.3) * 170)], o);
    }
    ctx.putImageData(img, 0, 0);
    setHref(c.toDataURL());
  }, [grids, scenario.width, scenario.height]);

  function toMap(e: React.PointerEvent<SVGGElement>) {
    const svg = (e.currentTarget as SVGGElement).ownerSVGElement!;
    const p = new DOMPoint(e.clientX, e.clientY).matrixTransform(svg.getScreenCTM()!.inverse());
    return { x: Math.min(Math.max(p.x, 0), scenario.width), y: Math.min(Math.max(p.y, 0), scenario.height) };
  }

  return (
    <g>
      {href && <image href={href} x={0} y={0} width={scenario.width} height={scenario.height} preserveAspectRatio="none" className="pointer-events-none" />}
      {drafts.map((d, i) => {
        const c = ORDER_COLOR[d.token_type];
        const r = results?.[i];
        const dead = r && !r.counted;
        return (
          <g
            key={d.id}
            className="cursor-move"
            onPointerDown={(e) => {
              e.stopPropagation();
              if (e.button !== 0) return;
              dragging.current = d.id;
              e.currentTarget.setPointerCapture(e.pointerId);
            }}
            onPointerMove={(e) => {
              if (dragging.current === d.id) {
                const p = toMap(e);
                onMove(d.id, p.x, p.y);
              }
            }}
            onPointerUp={() => (dragging.current = null)}
            onContextMenu={(e) => {
              e.preventDefault();
              e.stopPropagation();
              onRemove(d.id);
            }}
          >
            {d.token_type === "crew" && (
              <circle cx={d.x} cy={d.y} r={reach} fill="none" stroke={c} strokeOpacity={0.6} strokeWidth={1.25} strokeDasharray="5 4" {...NS} />
            )}
            <rect
              x={d.x - 11 * k}
              y={d.y - 11 * k}
              width={22 * k}
              height={22 * k}
              rx={6 * k}
              fill="var(--color-panel)"
              stroke={dead ? TONE.crit.hex : c}
              strokeWidth={2}
              strokeDasharray="4 2.5"
              {...NS}
            />
            <MapText x={d.x} y={d.y} k={k} size={11} weight={700} color={c} anchor="middle">
              {i + 1}
            </MapText>
            {r && (
              <MapText x={d.x + 15 * k} y={d.y} k={k} size={11} weight={600} color={dead ? TONE.crit.hex : "var(--color-ink-2)"}>
                {dead ? "No unit free" : r.eta_min ? aboutMinutes(r.eta_min) : "now"}
              </MapText>
            )}
          </g>
        );
      })}
    </g>
  );
}
