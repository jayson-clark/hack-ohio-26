// The console's map material (#130): a quiet cartographic basemap, not the
// projector's glowing art. Light hillshaded terrain with faint contours, the
// burned area in warm gray, active fire in red-orange with a crisp perimeter,
// and the forecast as two translucent bands (likely fire by the first and
// second horizon) with their edges drawn. Everything else on the map (towns,
// routes, units, labels) is vector overlay, so it stays sharp at any zoom.

import * as THREE from "three";
import type { BinaryFrame } from "../shared/binary";
import type { ForecastGrids } from "../shared/engine";
import type { Scenario } from "../shared/scenario";
import { blur } from "./projection";

const CELL_BURNING = 2;
const CELL_BURNED = 3;

export interface CartoStyle {
  terrain: boolean; // hillshade and elevation tint
  contours: boolean;
  forecast: boolean;
  dark: boolean; // night palette for the dark UI (#143)
}

export interface CartoMap {
  material: THREE.ShaderMaterial;
  setFire(frame: BinaryFrame | null): void;
  setForecast(forecast: ForecastGrids | null): void;
  setStyle(style: CartoStyle): void;
  dispose(): void;
}

const vertexShader = /* glsl */ `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;

const fragmentShader = /* glsl */ `
precision highp float;
varying vec2 vUv;

uniform sampler2D uHeight;
uniform sampler2D uFire; // r burning, g burned, b/a P(burned) at the two horizons
uniform vec2 uGrid;
uniform float uCellM;
uniform float uElevMin;
uniform float uElevRange;
uniform float uTerrain;
uniform float uContours;
uniform float uForecast;
uniform float uHasFire;
uniform float uDark;

float isoLines(float v, float px) {
  float d = abs(fract(v - 0.5) - 0.5) / max(fwidth(v), 1e-5);
  return 1.0 - smoothstep(px * 0.5, px * 0.5 + 1.0, d);
}

float edge(float v, float level, float px) {
  return 1.0 - smoothstep(0.0, max(fwidth(v) * px, 1e-4), abs(v - level));
}

vec3 terrain(vec2 uv) {
  float h = texture2D(uHeight, uv).r;
  vec2 t = 1.0 / uGrid;
  float hl = texture2D(uHeight, uv - vec2(t.x, 0.0)).r;
  float hr = texture2D(uHeight, uv + vec2(t.x, 0.0)).r;
  float hn = texture2D(uHeight, uv - vec2(0.0, t.y)).r;
  float hs = texture2D(uHeight, uv + vec2(0.0, t.y)).r;
  float k = uElevRange / (2.0 * uCellM) * 2.2;
  vec3 n = normalize(vec3(-(hr - hl) * k, -(hs - hn) * k, 1.0));
  float shade = clamp(dot(n, normalize(vec3(-0.5, -0.55, 0.67))), 0.0, 1.0);

  vec3 paper = mix(vec3(0.957, 0.953, 0.937), vec3(0.090, 0.102, 0.122), uDark);
  vec3 low = mix(vec3(0.874, 0.906, 0.851), vec3(0.106, 0.137, 0.125), uDark);   // valley sage
  vec3 high = mix(vec3(0.945, 0.925, 0.878), vec3(0.184, 0.180, 0.165), uDark);  // ridge sand
  vec3 base = mix(low, high, smoothstep(0.0, 1.0, h));
  vec3 col = mix(paper, base * (0.78 + 0.3 * shade), uTerrain);

  float elev = uElevMin + h * uElevRange;
  // Light lines on the dark map, and fainter: they stand out more there.
  vec3 ink = vec3(uDark);
  float c = uContours * (1.0 - 0.55 * uDark);
  col = mix(col, ink, 0.07 * isoLines(elev / 50.0, 1.0) * c);
  col = mix(col, ink, 0.15 * isoLines(elev / 250.0, 1.2) * c);
  return col;
}

void main() {
  vec3 col = terrain(vUv);
  if (uHasFire > 0.5) {
    vec4 f = texture2D(uFire, vUv);
    float out_ = 1.0 - clamp(f.r + f.g, 0.0, 1.0);
    if (uForecast > 0.5) {
      // Likely fire (half the simulations or more) by each horizon, far first.
      col = mix(col, vec3(0.98, 0.78, 0.33), smoothstep(0.42, 0.58, f.a) * 0.32 * out_);
      col = mix(col, vec3(0.97, 0.55, 0.24), smoothstep(0.42, 0.58, f.b) * 0.36 * out_);
      col = mix(col, vec3(0.80, 0.52, 0.06), edge(f.a, 0.5, 1.2) * 0.9 * out_);
      col = mix(col, vec3(0.80, 0.33, 0.07), edge(f.b, 0.5, 1.5) * 0.95 * out_);
    }
    float burned = smoothstep(0.35, 0.6, f.g);
    col = mix(col, mix(vec3(0.43, 0.38, 0.36), vec3(0.24, 0.21, 0.20), uDark), burned * 0.6);
    float burning = smoothstep(0.28, 0.55, f.r);
    col = mix(col, vec3(0.91, 0.27, 0.11), burning * 0.95);
    col = mix(col, vec3(0.55, 0.1, 0.04), edge(f.r + f.g, 0.42, 1.6) * 0.9);
  }
  gl_FragColor = vec4(col, 1.0);
}
`;

export function createCartoMap(s: Scenario): CartoMap {
  const { width, height, info } = s;
  const range = Math.max(info.elevation_m.max - info.elevation_m.min, 1e-6);

  const half = new Uint16Array(width * height);
  for (let i = 0; i < half.length; i++) {
    half[i] = THREE.DataUtils.toHalfFloat((s.heights[i] - info.elevation_m.min) / range);
  }
  const heightTex = new THREE.DataTexture(half, width, height, THREE.RedFormat, THREE.HalfFloatType);
  heightTex.magFilter = heightTex.minFilter = THREE.LinearFilter;
  heightTex.needsUpdate = true;

  const fireData = new Uint8Array(width * height * 4);
  const fireTex = new THREE.DataTexture(fireData, width, height, THREE.RGBAFormat);
  fireTex.magFilter = fireTex.minFilter = THREE.LinearFilter;
  fireTex.needsUpdate = true;

  const a = new Float32Array(width * height);
  const b = new Float32Array(width * height);
  const scratch = new Float32Array(width * height);

  const material = new THREE.ShaderMaterial({
    vertexShader,
    fragmentShader,
    uniforms: {
      uHeight: { value: heightTex },
      uFire: { value: fireTex },
      uGrid: { value: new THREE.Vector2(width, height) },
      uCellM: { value: info.grid.cell_size_m },
      uElevMin: { value: info.elevation_m.min },
      uElevRange: { value: range },
      uTerrain: { value: 1 },
      uContours: { value: 1 },
      uForecast: { value: 1 },
      uHasFire: { value: 0 },
      uDark: { value: 0 },
    },
  });
  const u = material.uniforms;

  return {
    material,

    setFire(frame) {
      if (!frame || frame.width !== width || frame.height !== height) {
        u.uHasFire.value = 0;
        return;
      }
      const cells = frame.payload;
      for (let i = 0; i < cells.length; i++) {
        a[i] = cells[i] === CELL_BURNING ? 1 : 0;
        b[i] = cells[i] === CELL_BURNED ? 1 : 0;
      }
      // Soften the per-cell masks so the shader draws a smooth perimeter.
      blur(a, scratch, width, height);
      blur(b, scratch, width, height);
      for (let i = 0; i < cells.length; i++) {
        fireData[i * 4] = Math.min(255, a[i] * 340);
        fireData[i * 4 + 1] = Math.min(255, b[i] * 300);
      }
      fireTex.needsUpdate = true;
      u.uHasFire.value = 1;
    },

    setForecast(forecast) {
      const ok = forecast && forecast.width === width && forecast.height === height;
      for (let h = 0; h < 2; h++) {
        const grid = ok ? forecast.horizons[h] : undefined;
        for (let i = 0; i < width * height; i++) a[i] = grid ? grid[i] : 0;
        if (grid) blur(a, scratch, width, height);
        for (let i = 0; i < width * height; i++) fireData[i * 4 + 2 + h] = a[i];
      }
      fireTex.needsUpdate = true;
    },

    setStyle(style) {
      u.uTerrain.value = +style.terrain;
      u.uContours.value = +style.contours;
      u.uForecast.value = +style.forecast;
      u.uDark.value = +style.dark;
    },

    dispose() {
      heightTex.dispose();
      fireTex.dispose();
      material.dispose();
    },
  };
}
