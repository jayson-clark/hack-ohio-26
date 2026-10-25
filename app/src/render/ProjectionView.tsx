// Flat projection view: exactly what the projector emits, letterboxed to the
// map's aspect. Used full-screen by the projector window and as the console's
// top-down view.
//
// With a projector calibration (mapToProj) the view fills its whole frame and
// the vertex shader places the map through the homography, so it lands on the
// printed terrain. The map is a mesh with the print's height at each vertex, so
// with the projector lens known (lens) each point is offset for its height. The
// input overlay follows through the same matrix as a CSS matrix3d, flat, so
// clicks line up at the marker plane.

import { useEffect, useRef, useState, type ReactNode } from "react";
import * as THREE from "three";
import type { BinaryFrame } from "../shared/binary";
import type { ForecastGrids } from "../shared/engine";
import type { RouteInfo, Token } from "../shared/protocol";
import { elevationAt, modelZ, printWindow, type Scenario } from "../shared/scenario";
import type { PlaceType } from "../shared/virtualTokens";
import { apply, cssMatrix3d, invert, toPixels, type Mat3 } from "./homography";
import MapOverlay from "./MapOverlay";
import { createProjection, type Layers, type Projection } from "./projection";
import { useProjectionSync } from "./useProjection";
import { mountViewport } from "./viewport";

export interface ViewProps {
  scenario: Scenario;
  tokens: Token[];
  simGrid: BinaryFrame | null;
  forecast: ForecastGrids | null;
  routes: RouteInfo[];
  layers: Layers;
  /** What a click on empty map places; null places nothing (the operator console). */
  placeType: PlaceType | null;
  selectedId: string | null;
  onSelect?: (id: string | null) => void;
  onHover?: (p: { x: number; y: number } | null) => void;
}

interface CalibrationProps {
  /** Row-major map -> projector window (normalised); null letterboxes the map. */
  mapToProj?: Mat3 | null;
  /** The projector lens (Calibration.projector) for the height correction; null draws the map flat. */
  lens?: number[] | null;
  /** Draw the calibration test grid and corner crosses over the map. */
  testPattern?: boolean;
  /** Draw only the printed terrain (the projector), not the sim map around it. */
  printOnly?: boolean;
}

export default function ProjectionView(props: ViewProps & CalibrationProps & { showGlyphs?: boolean; children?: ReactNode }) {
  const { scenario, tokens, placeType, showGlyphs, onSelect, onHover, mapToProj = null, lens = null, testPattern = false, printOnly = false } = props;
  const win = printOnly ? printWindow(scenario) : { x0: 0, y0: 0, w: scenario.width, h: scenario.height };
  const frameRef = useRef<HTMLDivElement>(null);
  const hostRef = useRef<HTMLDivElement>(null);
  const projRef = useRef<Projection | null>(null);
  const [generation, setGeneration] = useState(0);
  const [frame, setFrame] = useState({ w: 1, h: 1 });

  useEffect(() => {
    const el = frameRef.current!;
    const observer = new ResizeObserver(() => setFrame({ w: el.clientWidth || 1, h: el.clientHeight || 1 }));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const { width, height } = scenario;
    const projection = createProjection(scenario, { draped: false });
    projRef.current = projection;

    // Map coords as world units: x right, -y down, so the camera frame is the
    // map. One vertex per cell corner of the window drawn, each with the
    // print's height above the corner markers' plane for the calibrated height
    // correction.
    const { x0, y0, w, h } = win;
    const geometry = new THREE.BufferGeometry();
    const markerTop = scenario.info.markers.marker_top_z_mm;
    const pos: number[] = [];
    const uv: number[] = [];
    const lift: number[] = [];
    for (let y = y0; y <= y0 + h; y++) {
      for (let x = x0; x <= x0 + w; x++) {
        pos.push(x, -y, 0);
        uv.push(x / width, y / height);
        lift.push(modelZ(scenario, elevationAt(scenario, x, y)) - markerTop);
      }
    }
    const index: number[] = [];
    for (let j = 0; j < h; j++) {
      for (let i = 0; i < w; i++) {
        const k = j * (w + 1) + i;
        index.push(k, k + w + 1, k + 1, k + 1, k + w + 1, k + w + 2);
      }
    }
    geometry.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
    geometry.setAttribute("uv", new THREE.Float32BufferAttribute(uv, 2));
    geometry.setAttribute("aHeight", new THREE.Float32BufferAttribute(lift, 1));
    geometry.setIndex(index);

    const scene = new THREE.Scene();
    scene.add(new THREE.Mesh(geometry, projection.material));
    const camera = new THREE.OrthographicCamera(x0, x0 + w, -y0, -(y0 + h), -1, 1);

    const viewport = mountViewport(
      hostRef.current!,
      () => {},
      (t) => {
        projection.update(t);
        viewport.renderer.render(scene, camera);
      },
    );
    setGeneration((g) => g + 1);

    return () => {
      viewport.dispose();
      geometry.dispose();
      projection.dispose();
      projRef.current = null;
    };
  }, [scenario, printOnly]);

  useProjectionSync(projRef, props, generation);
  useEffect(() => projRef.current?.setMapToProj(mapToProj), [mapToProj, generation]);
  useEffect(() => projRef.current?.setLens(mapToProj ? lens : null), [mapToProj, lens, generation]);
  useEffect(() => projRef.current?.setTestGrid(testPattern), [testPattern, generation]);

  const overlay = (toMap?: (clientX: number, clientY: number) => { x: number; y: number }) => (
    <>
      <MapOverlay
        map={scenario}
        tokens={tokens}
        placeType={placeType}
        showGlyphs={showGlyphs}
        onSelect={onSelect}
        onHover={onHover}
        toMap={toMap}
      />
      {/* Extra layers in map coordinates (the console's plan overlay), above the tokens. */}
      {props.children}
      {testPattern && <TestPattern scenario={scenario} />}
    </>
  );

  let content;
  if (mapToProj) {
    const px = toPixels(mapToProj, frame.w, frame.h);
    const inv = invert(px);
    const toMap = (clientX: number, clientY: number) => {
      const r = frameRef.current!.getBoundingClientRect();
      const [x, y] = apply(inv, clientX - r.left, clientY - r.top);
      return { x, y };
    };
    content = (
      <div
        className="absolute top-0 left-0"
        style={{
          width: scenario.width,
          height: scenario.height,
          transformOrigin: "0 0",
          transform: cssMatrix3d(px),
          // In map units, before the transform: nothing past the window,
          // except the test pattern's crosses on the corner markers outside it.
          clipPath: testPattern ? undefined : `inset(${win.y0}px ${scenario.width - win.x0 - win.w}px ${scenario.height - win.y0 - win.h}px ${win.x0}px)`,
        }}
      >
        {overlay(toMap)}
      </div>
    );
  } else {
    // The overlay fills its box with the whole map, so size the box so the
    // window fills the frame, and clip the rest.
    content = (
      <div className="absolute inset-0 overflow-hidden">
        <div
          className="absolute"
          style={{
            left: `${(-win.x0 / win.w) * 100}%`,
            top: `${(-win.y0 / win.h) * 100}%`,
            width: `${(scenario.width / win.w) * 100}%`,
            height: `${(scenario.height / win.h) * 100}%`,
          }}
        >
          {overlay()}
        </div>
      </div>
    );
  }

  // The host keeps its place in the tree either way, so the WebGL canvas survives.
  return (
    <div ref={frameRef} className="relative flex h-full w-full items-center justify-center [container-type:size]">
      <div
        className={mapToProj ? "absolute inset-0" : "relative"}
        style={
          mapToProj
            ? undefined
            : {
                aspectRatio: `${win.w} / ${win.h}`,
                width: `min(100cqw, 100cqh * ${win.w / win.h})`,
              }
        }
      >
        <div ref={hostRef} className="absolute inset-0" />
        {content}
      </div>
    </div>
  );
}

const TEST_COLOR = "#22d3ee";

/** Calibration check, in map cells: crosses that should sit on the printed
 * corner markers. They're on the marker plane, so the flat overlay is exact;
 * the grid and map border are in the shader, on the terrain. */
function TestPattern({ scenario }: { scenario: Scenario }) {
  const { width, height, info } = scenario;
  const markerHalf = (info.markers.marker_size_mm / info.grid.cell_size_mm) / 2;
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="pointer-events-none absolute inset-0 h-full w-full"
      style={{ overflow: "visible" }}
      fill="none"
      stroke={TEST_COLOR}
    >
      {info.markers.corners.map(({ corner, center_map: [cx, cy] }) => (
        <g key={corner} strokeWidth={0.8}>
          <rect x={cx - markerHalf} y={cy - markerHalf} width={markerHalf * 2} height={markerHalf * 2} />
          <line x1={cx - markerHalf * 1.6} y1={cy} x2={cx + markerHalf * 1.6} y2={cy} />
          <line x1={cx} y1={cy - markerHalf * 1.6} x2={cx} y2={cy + markerHalf * 1.6} />
        </g>
      ))}
    </svg>
  );
}
