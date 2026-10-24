// Builds the projection material for a scenario and keeps its uniforms in
// sync with engine state. One instance per view (projector, console, table).

import * as THREE from "three";
import type { BinaryFrame } from "../shared/binary";
import type { ForecastGrids } from "../shared/engine";
import type { Recommendation, RouteInfo, StationInfo, Token, UnitInfo } from "../shared/protocol";
import type { Scenario } from "../shared/scenario";
import { HALO_RADIUS, TOKEN_STYLE, TOKEN_TYPES } from "../shared/tokens";
import { drawLabels } from "./labels";
import { createRoutesCanvas, drawRoutes, setRecReach } from "./routes";
import { MAX_TOKENS, fragmentShader, vertexShader } from "./shaders";

export interface Layers {
  tint: boolean;
  contours: boolean;
  labels: boolean;
  grid: boolean;
  routes: boolean;
  forecast: boolean;
}

export const DEFAULT_LAYERS: Layers = {
  tint: true,
  contours: true,
  labels: true,
  grid: false,
  routes: true,
  forecast: true,
};

// sim_grid cell states, in PLAN.md order. Switch to the generated enum once
// the sim defines it in protocol.py.
const CELL_BURNING = 2;
const CELL_BURNED = 3;

/** Display-space RGB from a hex color (no color management; see shaders.ts). */
function rgb(hex: string): THREE.Vector3 {
  const n = parseInt(hex.slice(1), 16);
  return new THREE.Vector3(((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255);
}

/** Separable 5-tap box blur, in place (edges clamp). */
function blur(a: Float32Array, tmp: Float32Array, w: number, h: number) {
  const R = 2;
  const norm = 1 / (2 * R + 1);
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      let sum = 0;
      for (let k = -R; k <= R; k++) sum += a[y * w + Math.min(w - 1, Math.max(0, x + k))];
      tmp[y * w + x] = sum * norm;
    }
  }
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      let sum = 0;
      for (let k = -R; k <= R; k++) sum += tmp[Math.min(h - 1, Math.max(0, y + k)) * w + x];
      a[y * w + x] = sum * norm;
    }
  }
}

export interface Projection {
  material: THREE.ShaderMaterial;
  setTokens(tokens: Token[], selectedId: string | null): void;
  setCrewReach(cells: number): void;
  setLayers(layers: Layers): void;
  setFire(frame: BinaryFrame | null): void;
  setForecast(forecast: ForecastGrids | null): void;
  setRoutes(routes: RouteInfo[]): void;
  setRecommendations(recs: Recommendation[]): void;
  setDispatch(stations: StationInfo[], units: UnitInfo[]): void;
  setThreatened(towns: string[]): void;
  /** Projector calibration (row-major map -> projector), or null to letterbox. Flat views only. */
  setMapToProj(h: number[] | null): void;
  update(timeSec: number): void;
  dispose(): void;
}

export function createProjection(s: Scenario, opts: { draped: boolean }): Projection {
  const { width, height, info } = s;
  const range = Math.max(info.elevation_m.max - info.elevation_m.min, 1e-6);

  // Normalized heights as a half-float texture: linear filtering works
  // everywhere (float32 filtering is optional in WebGL2).
  const half = new Uint16Array(width * height);
  for (let i = 0; i < half.length; i++) {
    half[i] = THREE.DataUtils.toHalfFloat((s.heights[i] - info.elevation_m.min) / range);
  }
  const heightTex = new THREE.DataTexture(half, width, height, THREE.RedFormat, THREE.HalfFloatType);
  heightTex.magFilter = heightTex.minFilter = THREE.LinearFilter;
  heightTex.needsUpdate = true;

  const labelsTex = new THREE.CanvasTexture(drawLabels(s));
  labelsTex.flipY = false;
  labelsTex.generateMipmaps = true;
  labelsTex.minFilter = THREE.LinearMipmapLinearFilter;
  labelsTex.anisotropy = 4;

  const routesCanvas = createRoutesCanvas(s);
  let lastRoutes: RouteInfo[] = [];
  let lastRecs: Recommendation[] = [];
  let lastStations: StationInfo[] = [];
  let lastUnits: UnitInfo[] = [];
  let lastThreatened: string[] = [];
  const routesTex = new THREE.CanvasTexture(routesCanvas);
  routesTex.flipY = false;
  routesTex.generateMipmaps = true;
  routesTex.minFilter = THREE.LinearMipmapLinearFilter;
  routesTex.anisotropy = 4;

  const fireData = new Uint8Array(width * height * 4);
  const fireTex = new THREE.DataTexture(fireData, width, height, THREE.RGBAFormat);
  fireTex.magFilter = fireTex.minFilter = THREE.LinearFilter;
  fireTex.needsUpdate = true;

  const burning = new Float32Array(width * height);
  const burned = new Float32Array(width * height);
  const scratch = new Float32Array(width * height);
  const forecastBuf = new Float32Array(width * height);

  const tokenData = Array.from({ length: MAX_TOKENS }, () => new THREE.Vector4());

  const material = new THREE.ShaderMaterial({
    vertexShader,
    fragmentShader,
    defines: opts.draped ? { DRAPED: "" } : {},
    uniforms: {
      uHeight: { value: heightTex },
      uLabels: { value: labelsTex },
      uRoutes: { value: routesTex },
      uShowRoutes: { value: 1 },
      uShowForecast: { value: 1 },
      uFire: { value: fireTex },
      uGrid: { value: new THREE.Vector2(width, height) },
      uCellM: { value: info.grid.cell_size_m },
      uElevMin: { value: info.elevation_m.min },
      uElevRange: { value: range },
      uTime: { value: 0 },
      uHasFire: { value: 0 },
      uLayers: { value: new THREE.Vector4(1, 1, 1, 0) },
      uTokens: { value: tokenData },
      uTokenCount: { value: 0 },
      uTokenColors: { value: TOKEN_TYPES.map((t) => rgb(TOKEN_STYLE[t].color)) },
      uHalo: { value: HALO_RADIUS },
      uCrewReach: { value: 14 },
      uRing: { value: HALO_RADIUS + 1.6 },
      uMapToProj: { value: new THREE.Matrix3() },
      uCalibrated: { value: 0 },
      uProjector: { value: new THREE.Vector3(0, 1500, 0) },
      uAmbient: { value: 0.07 },
      uTiles: {
        value: new THREE.Vector2(
          Math.max(1, ...info.tiles.map((t) => t.col + 1)),
          Math.max(1, ...info.tiles.map((t) => t.row + 1)),
        ),
      },
    },
  });
  const u = material.uniforms;

  return {
    material,

    setCrewReach(cells) {
      u.uCrewReach.value = cells;
      setRecReach(cells);
      drawRoutes(routesCanvas, s, lastRoutes, lastRecs, lastThreatened, lastStations, lastUnits);
      routesTex.needsUpdate = true;
    },

    setTokens(tokens, selectedId) {
      const n = Math.min(tokens.length, MAX_TOKENS);
      for (let i = 0; i < n; i++) {
        const t = tokens[i];
        tokenData[i].set(t.x, t.y, TOKEN_TYPES.indexOf(t.token_type), t.id === selectedId ? 1 : 0);
      }
      u.uTokenCount.value = n;
    },

    setLayers(l) {
      (u.uLayers.value as THREE.Vector4).set(+l.tint, +l.contours, +l.labels, +l.grid);
      u.uShowRoutes.value = +l.routes;
      u.uShowForecast.value = +l.forecast;
    },

    setFire(frame) {
      if (!frame || frame.width !== width || frame.height !== height) {
        u.uHasFire.value = 0;
        return;
      }
      const cells = frame.payload;
      for (let i = 0; i < cells.length; i++) {
        burning[i] = cells[i] === CELL_BURNING ? 1 : 0;
        burned[i] = cells[i] === CELL_BURNED ? 1 : 0;
      }
      // Soften the hard per-cell masks so the shader's threshold finds a smooth front.
      blur(burning, scratch, width, height);
      blur(burned, scratch, width, height);
      for (let i = 0; i < cells.length; i++) {
        fireData[i * 4] = Math.min(255, burning[i] * 340);
        fireData[i * 4 + 1] = Math.min(255, burned[i] * 300);
      }
      fireTex.needsUpdate = true;
      u.uHasFire.value = 1;
    },

    // P(burned by horizon) into b (nearest) and a (next); unused channels stay 0.
    setForecast(forecast) {
      const ok = forecast && forecast.width === width && forecast.height === height;
      for (let h = 0; h < 2; h++) {
        const grid = ok ? forecast.horizons[h] : undefined;
        // Smoothed like the fire masks: the shader draws the 50% and 90%
        // contours from these, and the raw cell grid gives stair-stepped lines.
        for (let i = 0; i < width * height; i++) forecastBuf[i] = grid ? grid[i] : 0;
        if (grid) blur(forecastBuf, scratch, width, height);
        for (let i = 0; i < width * height; i++) fireData[i * 4 + 2 + h] = forecastBuf[i];
      }
      fireTex.needsUpdate = true;
    },

    // Routes and recommendation markers share one canvas, so each redraws both.
    setRoutes(routes) {
      lastRoutes = routes;
      drawRoutes(routesCanvas, s, lastRoutes, lastRecs, lastThreatened, lastStations, lastUnits);
      routesTex.needsUpdate = true;
    },

    setRecommendations(recs) {
      lastRecs = recs;
      drawRoutes(routesCanvas, s, lastRoutes, lastRecs, lastThreatened, lastStations, lastUnits);
      routesTex.needsUpdate = true;
    },

    setDispatch(stations, units) {
      lastStations = stations;
      lastUnits = units;
      drawRoutes(routesCanvas, s, lastRoutes, lastRecs, lastThreatened, lastStations, lastUnits);
      routesTex.needsUpdate = true;
    },

    setThreatened(towns) {
      lastThreatened = towns;
      drawRoutes(routesCanvas, s, lastRoutes, lastRecs, lastThreatened, lastStations, lastUnits);
      routesTex.needsUpdate = true;
    },

    setMapToProj(h) {
      if (h) (u.uMapToProj.value as THREE.Matrix3).set(h[0], h[1], h[2], h[3], h[4], h[5], h[6], h[7], h[8]);
      u.uCalibrated.value = h ? 1 : 0;
    },

    update(timeSec) {
      u.uTime.value = timeSec;
    },

    dispose() {
      heightTex.dispose();
      labelsTex.dispose();
      routesTex.dispose();
      fireTex.dispose();
      material.dispose();
    },
  };
}
