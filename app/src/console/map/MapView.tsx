// The console's map canvas (#130): the cartographic basemap in WebGL, with
// pan (drag) and zoom (wheel, pinch, buttons), and an SVG overlay in map
// coordinates on top. Overlay children get `k`, map cells per screen pixel,
// so they can size markers and text in pixels at any zoom.

import { useEffect, useImperativeHandle, useRef, useState, type ReactNode, type Ref } from "react";
import * as THREE from "three";
import type { BinaryFrame } from "../../shared/binary";
import type { ForecastGrids } from "../../shared/engine";
import type { ForecastEnvelope } from "../../shared/protocol";
import type { Scenario } from "../../shared/scenario";
import { createCartoMap, type CartoMap, type CartoStyle } from "../../render/carto";
import { mountViewport } from "../../render/viewport";

export interface View {
  cx: number; // map cell at the center of the screen
  cy: number;
  s: number; // screen pixels per cell
}

export interface MapHandle {
  zoomBy(f: number): void;
  fit(): void;
  /** Pan (and zoom in if far out) so a point is centered. */
  focus(x: number, y: number): void;
}

interface Props {
  scenario: Scenario;
  simGrid: BinaryFrame | null;
  forecast: ForecastGrids | null;
  /** The calibrated envelope's cutoffs (#12); null draws the plain 50% edges. */
  envelope?: ForecastEnvelope | null;
  style: CartoStyle;
  /** A click (not a drag) on the map itself, in map cells. */
  onClick?: (x: number, y: number) => void;
  onHover?: (p: { x: number; y: number } | null) => void;
  cursor?: string;
  children?: (k: number) => ReactNode;
  handle?: Ref<MapHandle>;
}

const DRAG_PX = 4;
const MAX_ZOOM = 14; // times the fitted scale

export default function MapView(props: Props) {
  const { scenario, simGrid, forecast, envelope = null, style } = props;
  const host = useRef<HTMLDivElement>(null);
  const svg = useRef<SVGSVGElement>(null);
  const carto = useRef<CartoMap | null>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [view, setView] = useState<View | null>(null);
  const viewRef = useRef<View | null>(null);
  viewRef.current = view;
  const anim = useRef(0);

  const fitView = (w: number, h: number): View => ({
    cx: scenario.width / 2,
    cy: scenario.height / 2,
    s: Math.min(w / scenario.width, h / scenario.height) * 0.94,
  });
  const fitScale = () => (size.w ? fitView(size.w, size.h).s : 1);

  function clamp(v: View): View {
    const fit = fitScale();
    const s = Math.min(Math.max(v.s, fit * 0.8), fit * MAX_ZOOM);
    // Keep some of the map on screen.
    const cx = Math.min(Math.max(v.cx, 0), scenario.width);
    const cy = Math.min(Math.max(v.cy, 0), scenario.height);
    return { cx, cy, s };
  }

  function animateTo(target: View) {
    cancelAnimationFrame(anim.current);
    const from = viewRef.current;
    if (!from) return setView(target);
    const t0 = performance.now();
    const step = (t: number) => {
      const p = Math.min(1, (t - t0) / 320);
      const e = 1 - Math.pow(1 - p, 3);
      setView({
        cx: from.cx + (target.cx - from.cx) * e,
        cy: from.cy + (target.cy - from.cy) * e,
        s: from.s * Math.pow(target.s / from.s, e),
      });
      if (p < 1) anim.current = requestAnimationFrame(step);
    };
    anim.current = requestAnimationFrame(step);
  }

  useImperativeHandle(props.handle, () => ({
    zoomBy(f) {
      const v = viewRef.current;
      if (v) animateTo(clamp({ ...v, s: v.s * f }));
    },
    fit() {
      if (size.w) animateTo(fitView(size.w, size.h));
    },
    focus(x, y) {
      const v = viewRef.current;
      if (!v) return;
      animateTo(clamp({ cx: x, cy: y, s: Math.max(v.s, fitScale() * 2.2) }));
    },
  }));

  // WebGL basemap: one quad in map cells (x right, -y down), ortho camera from the view.
  useEffect(() => {
    const { width, height } = scenario;
    const map = createCartoMap(scenario);
    carto.current = map;
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.Float32BufferAttribute([0, 0, 0, width, 0, 0, 0, -height, 0, width, -height, 0], 3));
    geometry.setAttribute("uv", new THREE.Float32BufferAttribute([0, 0, 1, 0, 0, 1, 1, 1], 2));
    geometry.setIndex([0, 2, 1, 1, 2, 3]);
    const scene = new THREE.Scene();
    scene.add(new THREE.Mesh(geometry, map.material));
    const camera = new THREE.OrthographicCamera(0, 1, 0, -1, -1, 1);
    let px = { w: 1, h: 1 };

    const viewport = mountViewport(
      host.current!,
      (w, h) => {
        px = { w, h };
        setSize({ w, h });
      },
      () => {
        const v = viewRef.current;
        if (!v) return;
        const hw = px.w / (2 * v.s);
        const hh = px.h / (2 * v.s);
        camera.left = v.cx - hw;
        camera.right = v.cx + hw;
        camera.top = -(v.cy - hh);
        camera.bottom = -(v.cy + hh);
        camera.updateProjectionMatrix();
        viewport.renderer.render(scene, camera);
      },
    );
    viewport.renderer.setClearColor(0xe7e9ed);
    return () => {
      viewport.dispose();
      geometry.dispose();
      map.dispose();
      carto.current = null;
    };
  }, [scenario]);

  // Fit once the size is known, and again for a new scenario.
  useEffect(() => {
    if (size.w && (!viewRef.current || viewRef.current.s === 0)) setView(fitView(size.w, size.h));
  }, [size.w, size.h]);
  useEffect(() => {
    if (size.w) setView(fitView(size.w, size.h));
  }, [scenario]);

  useEffect(() => carto.current?.setFire(simGrid), [simGrid, scenario]);
  useEffect(() => carto.current?.setForecast(forecast, envelope), [forecast, envelope, scenario]);
  useEffect(() => carto.current?.setStyle(style), [style.terrain, style.contours, style.forecast, style.dark, scenario]);

  // Wheel and trackpad: zoom about the cursor (pinch arrives as ctrl+wheel).
  useEffect(() => {
    const el = svg.current;
    if (!el) return;
    function onWheel(e: WheelEvent) {
      e.preventDefault();
      const v = viewRef.current;
      if (!v) return;
      cancelAnimationFrame(anim.current);
      const r = el!.getBoundingClientRect();
      const mx = v.cx + (e.clientX - r.left - r.width / 2) / v.s;
      const my = v.cy + (e.clientY - r.top - r.height / 2) / v.s;
      const next = clamp({ ...v, s: v.s * Math.exp(-e.deltaY * (e.ctrlKey ? 0.01 : 0.0018)) });
      // Keep the point under the cursor where it was.
      setView({
        s: next.s,
        cx: mx - (e.clientX - r.left - r.width / 2) / next.s,
        cy: my - (e.clientY - r.top - r.height / 2) / next.s,
      });
    }
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  });

  const drag = useRef<{ x: number; y: number; view: View; moved: boolean; id: number } | null>(null);

  function toMap(e: React.PointerEvent) {
    const v = viewRef.current!;
    const r = svg.current!.getBoundingClientRect();
    return { x: v.cx + (e.clientX - r.left - r.width / 2) / v.s, y: v.cy + (e.clientY - r.top - r.height / 2) / v.s };
  }

  const v = view;
  const viewBox = v && size.w ? `${v.cx - size.w / (2 * v.s)} ${v.cy - size.h / (2 * v.s)} ${size.w / v.s} ${size.h / v.s}` : "0 0 1 1";

  return (
    <div className="relative h-full w-full overflow-hidden">
      <div ref={host} className="absolute inset-0" />
      <svg
        ref={svg}
        viewBox={viewBox}
        preserveAspectRatio="none"
        className="absolute inset-0 h-full w-full touch-none"
        style={{ cursor: drag.current?.moved ? "grabbing" : (props.cursor ?? "grab") }}
        onPointerDown={(e) => {
          if (e.button !== 0 || !viewRef.current) return;
          cancelAnimationFrame(anim.current);
          drag.current = { x: e.clientX, y: e.clientY, view: viewRef.current, moved: false, id: e.pointerId };
          svg.current!.setPointerCapture(e.pointerId);
        }}
        onPointerMove={(e) => {
          if (viewRef.current) props.onHover?.(toMap(e));
          const d = drag.current;
          if (!d) return;
          const dx = e.clientX - d.x;
          const dy = e.clientY - d.y;
          if (!d.moved && Math.hypot(dx, dy) < DRAG_PX) return;
          d.moved = true;
          setView(clamp({ ...d.view, cx: d.view.cx - dx / d.view.s, cy: d.view.cy - dy / d.view.s }));
        }}
        onPointerUp={(e) => {
          const d = drag.current;
          drag.current = null;
          if (d && !d.moved) {
            const p = toMap(e);
            props.onClick?.(p.x, p.y);
          }
        }}
        onPointerLeave={() => props.onHover?.(null)}
        onDoubleClick={(e) => {
          const p = toMap(e as unknown as React.PointerEvent);
          const cur = viewRef.current;
          if (cur) animateTo(clamp({ cx: p.x, cy: p.y, s: cur.s * 2 }));
        }}
        onContextMenu={(e) => e.preventDefault()}
      >
        {v && props.children?.(1 / v.s)}
      </svg>
    </div>
  );
}
