// Scenario terrain, loaded straight from assets/scenarios/<name>/ (the same
// files the engine and the 3D print come from). Vite bundles them, so this
// works in the browser, in `tauri dev`, and in a built app.

import { useEffect, useState } from "react";
import { parseNpy } from "./npy";

/** The parts of terrain.json the UI uses. Written by tools/dem_to_assets.py. */
export interface TerrainInfo {
  name: string;
  bounds: { south: number; west: number; north: number; east: number };
  grid: { width: number; height: number; cell_size_m: number; cell_size_mm: number };
  elevation_m: { min: number; max: number };
  model: {
    width_mm: number;
    height_mm: number;
    base_mm: number;
    relief_mm: number;
    m_per_mm: number;
    vertical_exaggeration: number;
  };
  markers: {
    marker_size_mm: number;
    marker_top_z_mm: number;
    corners: { corner: string; center_mm: [number, number]; center_map: [number, number] }[];
  };
  tiles: { row: number; col: number; origin_mm: [number, number]; size_mm: [number, number] }[];
  places: { name: string; lat: number; lon: number; map: [number, number] }[];
}

/** towns.json, written by tools/osm_to_layers.py: what the game scores and routing evacuates. */
export interface Town {
  name: string;
  x: number;
  y: number;
  radius: number; // cells: the disk the score counts as the town
  population: number;
  structures: number;
}

export interface Scenario {
  info: TerrainInfo;
  /** Empty for a scenario without a road layer. */
  towns: Town[];
  width: number;
  height: number;
  /** Elevation in meters, row-major, row 0 = north. */
  heights: Float32Array;
}

const terrainFiles = import.meta.glob<TerrainInfo>("../../../assets/scenarios/*/terrain.json", {
  eager: true,
  import: "default",
});
const townFiles = import.meta.glob<{ towns: Town[] }>("../../../assets/scenarios/*/towns.json", {
  eager: true,
  import: "default",
});
const heightmapUrls = import.meta.glob<string>("../../../assets/scenarios/*/heightmap.npy", {
  eager: true,
  query: "?url",
  import: "default",
});

function scenarioName(path: string) {
  const parts = path.split("/");
  return parts[parts.length - 2];
}

export const SCENARIOS: string[] = Object.keys(terrainFiles).map(scenarioName).sort();

// ?scenario=<name> picks one; otherwise the env default, then the first found.
export const DEFAULT_SCENARIO =
  new URLSearchParams(window.location.search).get("scenario") ??
  import.meta.env.VITE_SCENARIO ??
  (SCENARIOS.includes("paradise") ? "paradise" : SCENARIOS[0]);

const cache = new Map<string, Promise<Scenario>>();

export function loadScenario(name: string): Promise<Scenario> {
  let promise = cache.get(name);
  if (!promise) {
    promise = (async () => {
      const infoPath = Object.keys(terrainFiles).find((p) => scenarioName(p) === name);
      const urlPath = Object.keys(heightmapUrls).find((p) => scenarioName(p) === name);
      if (!infoPath || !urlPath) throw new Error(`scenario "${name}" not found in assets/scenarios`);
      const info = terrainFiles[infoPath];
      const res = await fetch(heightmapUrls[urlPath]);
      if (!res.ok) throw new Error(`heightmap: HTTP ${res.status}`);
      const npy = parseNpy(await res.arrayBuffer());
      const [height, width] = npy.shape;
      if (width !== info.grid.width || height !== info.grid.height) {
        throw new Error(`heightmap is ${width}×${height}, terrain.json says ${info.grid.width}×${info.grid.height}`);
      }
      const townsPath = Object.keys(townFiles).find((p) => scenarioName(p) === name);
      const towns = townsPath ? townFiles[townsPath].towns : [];
      return { info, towns, width, height, heights: npy.data };
    })();
    cache.set(name, promise);
  }
  return promise;
}

export function useScenario(name: string = DEFAULT_SCENARIO): { scenario: Scenario | null; error: string | null } {
  const [scenario, setScenario] = useState<Scenario | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    loadScenario(name).then(
      (s) => live && setScenario(s),
      (e) => live && setError(String(e)),
    );
    return () => {
      live = false;
    };
  }, [name]);
  return { scenario, error };
}

// --- Map-coordinate helpers ------------------------------------------------
// Map coords are in cells, origin top-left (north-west), cell centers at +0.5.

/** Bilinear elevation in meters at a map position. */
export function elevationAt(s: Scenario, x: number, y: number): number {
  const fx = Math.min(Math.max(x - 0.5, 0), s.width - 1);
  const fy = Math.min(Math.max(y - 0.5, 0), s.height - 1);
  const x0 = Math.floor(fx);
  const y0 = Math.floor(fy);
  const x1 = Math.min(x0 + 1, s.width - 1);
  const y1 = Math.min(y0 + 1, s.height - 1);
  const tx = fx - x0;
  const ty = fy - y0;
  const h = s.heights;
  const w = s.width;
  const top = h[y0 * w + x0] * (1 - tx) + h[y0 * w + x1] * tx;
  const bottom = h[y1 * w + x0] * (1 - tx) + h[y1 * w + x1] * tx;
  return top * (1 - ty) + bottom * ty;
}

/** Height of the printed surface above the table, in mm (matches dem_to_assets.py). */
export function modelZ(s: Scenario, elevation: number): number {
  const { model, elevation_m } = s.info;
  return model.base_mm + ((elevation - elevation_m.min) * model.vertical_exaggeration) / model.m_per_mm;
}

/** Approximate lat/lon (linear over the small region). */
export function latLonAt(s: Scenario, x: number, y: number): { lat: number; lon: number } {
  const b = s.info.bounds;
  return {
    lat: b.north - (y / s.height) * (b.north - b.south),
    lon: b.west + (x / s.width) * (b.east - b.west),
  };
}

export function inMap(s: Scenario, x: number, y: number): boolean {
  return x >= 0 && y >= 0 && x <= s.width && y <= s.height;
}
