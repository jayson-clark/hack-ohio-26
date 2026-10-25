// Flat projection view: exactly what the projector emits, letterboxed to the
// map's aspect. Used full-screen by the projector window and as the console's
// top-down view.
//
// With a projector calibration (mapToProj) the view fills its whole frame and
// the vertex shader places the map through the homography, so it lands on the
// printed terrain. The input overlay follows through the same matrix as a CSS
// matrix3d, so clicks and the test grid line up with the picture.

import { useEffect, useRef, useState, type ReactNode } from "react";
import * as THREE from "three";
import type { BinaryFrame } from "../shared/binary";
import type { ForecastGrids } from "../shared/engine";
import type { RouteInfo, Token } from "../shared/protocol";
import type { Scenario } from "../shared/scenario";
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
  /** Draw the calibration test grid and corner crosses over the map. */
  testPattern?: boolean;
}

export default function ProjectionView(props: ViewProps & CalibrationProps & { showGlyphs?: boolean; children?: ReactNode }) {
  const { scenario, tokens, placeType, showGlyphs, onSelect, onHover, mapToProj = null, testPattern = false } = props;
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

    // Map coords as world units: x right, -y down, so the camera frame is the map.
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute(
      "position",
      new THREE.Float32BufferAttribute([0, 0, 0, width, 0, 0, 0, -height, 0, width, -height, 0], 3),
    );
    geometry.setAttribute("uv", new THREE.Float32BufferAttribute([0, 0, 1, 0, 0, 1, 1, 1], 2));
    geometry.setIndex([0, 2, 1, 1, 2, 3]);

    const scene = new THREE.Scene();
    scene.add(new THREE.Mesh(geometry, projection.material));
    const camera = new THREE.OrthographicCamera(0, width, 0, -height, -1, 1);

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
  }, [scenario]);

  useProjectionSync(projRef, props, generation);
  useEffect(() => projRef.current?.setMapToProj(mapToProj), [mapToProj, generation]);

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
        }}
      >
        {overlay(toMap)}
      </div>
    );
  } else {
    content = overlay();
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
                aspectRatio: `${scenario.width} / ${scenario.height}`,
                width: `min(100cqw, 100cqh * ${scenario.width / scenario.height})`,
              }
        }
      >
        <div ref={hostRef} className="absolute inset-0" />
        {content}
      </div>
    </div>
  );
}

const TEST_GRID_CELLS = 16;
const TEST_COLOR = "#22d3ee";

/** Calibration check, in map cells: grid, map border, and crosses that should
 * sit on the printed corner markers. */
function TestPattern({ scenario }: { scenario: Scenario }) {
  const { width, height, info } = scenario;
  const markerHalf = (info.markers.marker_size_mm / info.grid.cell_size_mm) / 2;
  const xs = Array.from({ length: Math.floor(width / TEST_GRID_CELLS) + 1 }, (_, i) => i * TEST_GRID_CELLS);
  const ys = Array.from({ length: Math.floor(height / TEST_GRID_CELLS) + 1 }, (_, i) => i * TEST_GRID_CELLS);
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="pointer-events-none absolute inset-0 h-full w-full"
      style={{ overflow: "visible" }}
      fill="none"
      stroke={TEST_COLOR}
    >
      {xs.map((x) => (
        <line key={`x${x}`} x1={x} y1={0} x2={x} y2={height} strokeWidth={0.35} />
      ))}
      {ys.map((y) => (
        <line key={`y${y}`} x1={0} y1={y} x2={width} y2={y} strokeWidth={0.35} />
      ))}
      <rect width={width} height={height} strokeWidth={1.2} />
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
