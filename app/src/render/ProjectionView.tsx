// Flat projection view: exactly what the projector emits, letterboxed to the
// map's aspect. Used full-screen by the projector window and as the console's
// top-down view.
//
// TODO(calibration): apply H_map→proj in the vertex shader here.

import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import type { BinaryFrame } from "../shared/binary";
import type { Token, TokenType } from "../shared/protocol";
import type { Scenario } from "../shared/scenario";
import MapOverlay from "./MapOverlay";
import { createProjection, type Layers, type Projection } from "./projection";
import { useProjectionSync } from "./useProjection";
import { mountViewport } from "./viewport";

export interface ViewProps {
  scenario: Scenario;
  tokens: Token[];
  simGrid: BinaryFrame | null;
  layers: Layers;
  placeType: TokenType;
  selectedId: string | null;
  onSelect?: (id: string | null) => void;
  onHover?: (p: { x: number; y: number } | null) => void;
}

export default function ProjectionView(props: ViewProps & { showGlyphs?: boolean }) {
  const { scenario, tokens, placeType, showGlyphs, onSelect, onHover } = props;
  const hostRef = useRef<HTMLDivElement>(null);
  const projRef = useRef<Projection | null>(null);
  const [generation, setGeneration] = useState(0);

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

  return (
    <div className="flex h-full w-full items-center justify-center [container-type:size]">
      <div
        className="relative"
        style={{
          aspectRatio: `${scenario.width} / ${scenario.height}`,
          width: `min(100cqw, 100cqh * ${scenario.width / scenario.height})`,
        }}
      >
        <div ref={hostRef} className="absolute inset-0" />
        <MapOverlay
          map={scenario}
          tokens={tokens}
          placeType={placeType}
          showGlyphs={showGlyphs}
          onSelect={onSelect}
          onHover={onHover}
        />
      </div>
    </div>
  );
}
