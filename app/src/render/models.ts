// Geometry for the virtual table: the printed terrain block and token pucks,
// all in millimetres. The table stands in for the world the operator sees,
// not the hardware, so it leaves out the ArUco corner holders and marker
// patterns the physical build uses for calibration. Axes: x east, y up, z south,
// origin at the board's center on the table surface.

import * as THREE from "three";
import { elevationAt, modelZ, type Scenario } from "../shared/scenario";
import type { TokenType } from "../shared/protocol";
import { TOKEN_RADIUS, TOKEN_STYLE } from "../shared/tokens";

export const PUCK_HEIGHT_MM = 7;

export interface Board {
  widthMm: number;
  heightMm: number;
  /** Map coords (cells) to board position (mm), y on the table. */
  toBoard(x: number, y: number): { bx: number; bz: number };
  /** Board position (mm) to map coords (cells). */
  toMap(bx: number, bz: number): { x: number; y: number };
  /** Printed surface height at a map position, mm. */
  surfaceAt(x: number, y: number): number;
  maxZ: number;
}

export function makeBoard(s: Scenario): Board {
  const { width_mm: widthMm, height_mm: heightMm } = s.info.model;
  return {
    widthMm,
    heightMm,
    toBoard: (x, y) => ({ bx: (x / s.width - 0.5) * widthMm, bz: (y / s.height - 0.5) * heightMm }),
    toMap: (bx, bz) => ({ x: (bx / widthMm + 0.5) * s.width, y: (bz / heightMm + 0.5) * s.height }),
    surfaceAt: (x, y) => modelZ(s, elevationAt(s, x, y)),
    maxZ: modelZ(s, s.info.elevation_m.max),
  };
}

/** Terrain top surface: one vertex per cell corner, uv = (col/W, row/H). */
export function terrainGeometry(s: Scenario, board: Board): THREE.BufferGeometry {
  const cols = s.width + 1;
  const rows = s.height + 1;
  const pos = new Float32Array(cols * rows * 3);
  const uv = new Float32Array(cols * rows * 2);
  for (let j = 0; j < rows; j++) {
    for (let i = 0; i < cols; i++) {
      const k = j * cols + i;
      const { bx, bz } = board.toBoard(i, j);
      pos.set([bx, board.surfaceAt(i, j), bz], k * 3);
      uv.set([i / s.width, j / s.height], k * 2);
    }
  }
  const index: number[] = [];
  for (let j = 0; j < s.height; j++) {
    for (let i = 0; i < s.width; i++) {
      const a = j * cols + i;
      const b = a + 1;
      const c = a + cols;
      const d = c + 1;
      index.push(a, c, b, b, c, d);
    }
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  geo.setAttribute("uv", new THREE.BufferAttribute(uv, 2));
  geo.setIndex(index);
  geo.computeVertexNormals();
  return geo;
}

/** The four side walls of the printed block, down to the table. */
export function wallGeometry(s: Scenario, board: Board): THREE.BufferGeometry {
  const pos: number[] = [];
  const edge = (pts: [number, number][]) => {
    for (let k = 0; k < pts.length - 1; k++) {
      const [x0, y0] = pts[k];
      const [x1, y1] = pts[k + 1];
      const p0 = board.toBoard(x0, y0);
      const p1 = board.toBoard(x1, y1);
      const h0 = board.surfaceAt(x0, y0);
      const h1 = board.surfaceAt(x1, y1);
      pos.push(p0.bx, 0, p0.bz, p1.bx, 0, p1.bz, p0.bx, h0, p0.bz);
      pos.push(p1.bx, 0, p1.bz, p1.bx, h1, p1.bz, p0.bx, h0, p0.bz);
    }
  };
  const xs = Array.from({ length: s.width + 1 }, (_, i) => i);
  const ys = Array.from({ length: s.height + 1 }, (_, j) => j);
  edge(xs.map((i) => [i, 0]));
  edge(xs.map((i) => [i, s.height]));
  edge(ys.map((j) => [0, j]));
  edge(ys.map((j) => [s.width, j]));
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  geo.computeVertexNormals();
  return geo;
}

// --- Token pucks -----------------------------------------------------------

const puckMaterials = new Map<TokenType, THREE.Material[]>();

function materialsFor(type: TokenType): THREE.Material[] {
  let mats = puckMaterials.get(type);
  if (!mats) {
    const side = new THREE.MeshStandardMaterial({ color: TOKEN_STYLE[type].color, roughness: 0.55 });
    const top = new THREE.MeshStandardMaterial({ color: TOKEN_STYLE[type].color, roughness: 0.4 });
    mats = [side, top, side];
    puckMaterials.set(type, mats);
  }
  return mats;
}

export function makePuck(s: Scenario, type: TokenType): THREE.Mesh {
  const r = TOKEN_RADIUS * s.info.grid.cell_size_mm;
  const geo = new THREE.CylinderGeometry(r, r, PUCK_HEIGHT_MM, 48);
  geo.translate(0, PUCK_HEIGHT_MM / 2, 0);
  return new THREE.Mesh(geo, materialsFor(type));
}

/** A puck rests on the highest point under its footprint. */
export function restingHeight(board: Board, x: number, y: number): number {
  let h = board.surfaceAt(x, y);
  for (let k = 0; k < 8; k++) {
    const a = (k / 8) * Math.PI * 2;
    h = Math.max(h, board.surfaceAt(x + Math.cos(a) * TOKEN_RADIUS, y + Math.sin(a) * TOKEN_RADIUS));
  }
  return h;
}
