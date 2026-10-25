// Virtual table: the 3D-printed terrain on a table, with the projection
// shader draped over it and token pucks sitting on the surface. Lets anyone
// see (and play) the physical setup without the hardware.
//
// Left-drag orbits, right-drag pans, scroll zooms. Click the terrain to place
// a token, drag a puck to move it, right-click a puck to remove it.

import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import type { Token } from "../shared/protocol";
import { inMap } from "../shared/scenario";
import { createMover, place, removeToken } from "../shared/virtualTokens";
import { makeBoard, makePuck, restingHeight, terrainGeometry, wallGeometry } from "./models";
import { createProjection, type Projection } from "./projection";
import type { ViewProps } from "./ProjectionView";
import { useProjectionSync } from "./useProjection";
import { mountViewport } from "./viewport";

export type CameraPreset = "oblique" | "top" | "low";

export type CameraCommand =
  | { seq: number; kind: "preset"; preset: CameraPreset }
  | { seq: number; kind: "focus"; x: number; y: number };

const CLICK_SLOP_PX = 5;
const LIFT_MM = 6;

interface SceneApi {
  syncTokens(tokens: Token[]): void;
  command(cmd: CameraCommand): void;
}

export default function TableView(props: ViewProps & { camera: CameraCommand | null }) {
  const { scenario, tokens, camera } = props;
  const hostRef = useRef<HTMLDivElement>(null);
  const projRef = useRef<Projection | null>(null);
  const apiRef = useRef<SceneApi | null>(null);
  const [generation, setGeneration] = useState(0);

  // Latest props for event handlers inside the Three.js setup.
  const live = useRef(props);
  live.current = props;

  useEffect(() => {
    const s = scenario;
    const board = makeBoard(s);
    const span = Math.max(board.widthMm, board.heightMm);
    const projection = createProjection(s, { draped: true });
    projRef.current = projection;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color("#0a0b0d");
    scene.add(new THREE.HemisphereLight("#c8d0dc", "#202024", 0.55));
    const key = new THREE.DirectionalLight("#ffffff", 0.7);
    key.position.set(-0.6, 1, 0.8).multiplyScalar(span);
    scene.add(key);

    const terrain = new THREE.Mesh(terrainGeometry(s, board), projection.material);
    const pla = new THREE.MeshStandardMaterial({ color: "#d4d4cf", roughness: 0.9, side: THREE.DoubleSide });
    const walls = new THREE.Mesh(wallGeometry(s, board), pla);
    const table = new THREE.Mesh(
      new THREE.PlaneGeometry(span * 8, span * 8),
      new THREE.MeshStandardMaterial({ color: "#141518", roughness: 0.95 }),
    );
    table.rotation.x = -Math.PI / 2;
    table.position.y = -0.01;
    const pucks = new THREE.Group();
    scene.add(terrain, walls, table, pucks);

    const cam = new THREE.PerspectiveCamera(35, 1, 5, span * 20);
    const presetPose = (p: CameraPreset) => {
      const target = new THREE.Vector3(0, board.maxZ * 0.3, 0);
      const pos =
        p === "top"
          ? new THREE.Vector3(0, span * 2.1, 0.001)
          : p === "low"
            ? new THREE.Vector3(-span * 0.62, span * 0.28, span * 0.72)
            : new THREE.Vector3(0, span * 1.2, span * 1.42);
      return { pos, target };
    };
    const initial = presetPose("oblique");
    cam.position.copy(initial.pos);

    const viewport = mountViewport(
      hostRef.current!,
      (w, h) => {
        cam.aspect = w / h;
        cam.updateProjectionMatrix();
      },
      (t) => {
        stepTween();
        controls.update();
        projection.update(t);
        viewport.renderer.render(scene, cam);
      },
    );
    const el = viewport.renderer.domElement;

    // --- Picking ---------------------------------------------------------

    const raycaster = new THREE.Raycaster();
    const ndc = new THREE.Vector2();

    function rayFrom(e: PointerEvent) {
      const rect = el.getBoundingClientRect();
      ndc.set(((e.clientX - rect.left) / rect.width) * 2 - 1, -((e.clientY - rect.top) / rect.height) * 2 + 1);
      raycaster.setFromCamera(ndc, cam);
      return raycaster.ray;
    }

    function pickPuck(e: PointerEvent): string | null {
      rayFrom(e);
      const hit = raycaster.intersectObjects(pucks.children, false)[0];
      return (hit?.object.userData.tokenId as string | undefined) ?? null;
    }

    /** March the ray against the heightfield: cheap and exact enough for a cursor. */
    function pickMap(e: PointerEvent): { x: number; y: number } | null {
      const ray = rayFrom(e);
      if (ray.direction.y >= 0) return null;
      const top = board.maxZ + 1;
      let t = ray.origin.y > top ? (ray.origin.y - top) / -ray.direction.y : 0;
      const tEnd = ray.origin.y / -ray.direction.y;
      const step = s.info.grid.cell_size_mm * 0.5;
      const p = new THREE.Vector3();
      let prev = t;
      for (; t <= tEnd; t += step) {
        ray.at(t, p);
        const m = board.toMap(p.x, p.z);
        if (inMap(s, m.x, m.y) && p.y <= board.surfaceAt(m.x, m.y)) {
          // Refine between the last point above and this one below.
          let lo = prev;
          let hi = t;
          for (let k = 0; k < 8; k++) {
            const mid = (lo + hi) / 2;
            ray.at(mid, p);
            const mm = board.toMap(p.x, p.z);
            if (p.y <= board.surfaceAt(mm.x, mm.y)) hi = mid;
            else lo = mid;
          }
          ray.at(hi, p);
          return board.toMap(p.x, p.z);
        }
        prev = t;
      }
      return null;
    }

    // --- Input -------------------------------------------------------------
    // Registered before OrbitControls so grabbing a puck can stop the orbit.

    const move = createMover(s);
    let down: { x: number; y: number; button: number; tokenId: string | null } | null = null;
    let dragging: string | null = null;

    const onPointerDown = (e: PointerEvent) => {
      const tokenId = pickPuck(e);
      down = { x: e.clientX, y: e.clientY, button: e.button, tokenId };
      if (e.button !== 0 || !tokenId) return;
      live.current.onSelect?.(tokenId);
      const token = live.current.tokens.find((t) => t.id === tokenId);
      if (token?.source !== "virtual") return;
      dragging = tokenId;
      el.setPointerCapture(e.pointerId);
      e.stopImmediatePropagation();
      el.style.cursor = "grabbing";
    };

    const onPointerMove = (e: PointerEvent) => {
      const m = pickMap(e);
      live.current.onHover?.(m);
      if (dragging) {
        if (m) move(dragging, m.x, m.y);
        return;
      }
      if (e.buttons === 0) el.style.cursor = pickPuck(e) ? "grab" : m ? "crosshair" : "default";
    };

    const onPointerUp = (e: PointerEvent) => {
      if (dragging) {
        dragging = null;
        el.style.cursor = "grab";
        syncTokens(live.current.tokens);
        return;
      }
      const d = down;
      down = null;
      if (!d || Math.hypot(e.clientX - d.x, e.clientY - d.y) > CLICK_SLOP_PX) return;
      if (d.button === 0 && !d.tokenId) {
        const m = pickMap(e);
        if (m) {
          if (live.current.placeType) place(live.current.placeType, m.x, m.y, s);
          live.current.onSelect?.(null);
        }
      } else if (d.button === 2 && d.tokenId) {
        const token = live.current.tokens.find((t) => t.id === d.tokenId);
        if (token?.source === "virtual") removeToken(token.id);
      }
    };

    const onLeave = () => live.current.onHover?.(null);
    const onContextMenu = (e: Event) => e.preventDefault();

    el.addEventListener("pointerdown", onPointerDown);
    el.addEventListener("pointermove", onPointerMove);
    el.addEventListener("pointerup", onPointerUp);
    el.addEventListener("pointerleave", onLeave);
    el.addEventListener("contextmenu", onContextMenu);

    const controls = new OrbitControls(cam, el);
    controls.target.copy(initial.target);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.minDistance = span * 0.15;
    controls.maxDistance = span * 3;
    controls.maxPolarAngle = Math.PI * 0.47;
    controls.screenSpacePanning = false;
    controls.zoomToCursor = true;

    // --- Camera moves ----------------------------------------------------

    let tween: { from: { pos: THREE.Vector3; target: THREE.Vector3 }; to: typeof initial; start: number } | null =
      null;
    const TWEEN_MS = 700;

    function flyTo(to: { pos: THREE.Vector3; target: THREE.Vector3 }) {
      tween = { from: { pos: cam.position.clone(), target: controls.target.clone() }, to, start: performance.now() };
    }

    function stepTween() {
      if (!tween) return;
      const k = Math.min((performance.now() - tween.start) / TWEEN_MS, 1);
      const e = 1 - Math.pow(1 - k, 3);
      cam.position.lerpVectors(tween.from.pos, tween.to.pos, e);
      controls.target.lerpVectors(tween.from.target, tween.to.target, e);
      if (k >= 1) tween = null;
    }

    // --- Pucks -------------------------------------------------------------

    const meshes = new Map<string, THREE.Mesh>();

    function syncTokens(list: Token[]) {
      const seen = new Set<string>();
      for (const t of list) {
        seen.add(t.id);
        let mesh = meshes.get(t.id);
        if (mesh && mesh.userData.tokenType !== t.token_type) {
          pucks.remove(mesh);
          mesh.geometry.dispose();
          mesh = undefined;
        }
        if (!mesh) {
          mesh = makePuck(s, t.token_type);
          mesh.userData = { tokenId: t.id, tokenType: t.token_type };
          meshes.set(t.id, mesh);
          pucks.add(mesh);
        }
        const { bx, bz } = board.toBoard(t.x, t.y);
        mesh.position.set(bx, restingHeight(board, t.x, t.y) + (dragging === t.id ? LIFT_MM : 0), bz);
        mesh.rotation.y = -t.angle;
      }
      for (const [id, mesh] of meshes) {
        if (!seen.has(id)) {
          pucks.remove(mesh);
          mesh.geometry.dispose();
          meshes.delete(id);
        }
      }
    }

    apiRef.current = {
      syncTokens,
      command(cmd) {
        if (cmd.kind === "preset") {
          flyTo(presetPose(cmd.preset));
          return;
        }
        const { bx, bz } = board.toBoard(cmd.x, cmd.y);
        const target = new THREE.Vector3(bx, board.surfaceAt(cmd.x, cmd.y), bz);
        const offset = cam.position.clone().sub(controls.target).setLength(span * 0.55);
        flyTo({ pos: target.clone().add(offset), target });
      },
    };
    syncTokens(live.current.tokens);
    setGeneration((g) => g + 1);

    return () => {
      apiRef.current = null;
      controls.dispose();
      el.removeEventListener("pointerdown", onPointerDown);
      el.removeEventListener("pointermove", onPointerMove);
      el.removeEventListener("pointerup", onPointerUp);
      el.removeEventListener("pointerleave", onLeave);
      el.removeEventListener("contextmenu", onContextMenu);
      viewport.dispose();
      scene.traverse((o) => {
        if (o instanceof THREE.Mesh) o.geometry.dispose();
      });
      pla.dispose();
      projection.dispose();
      projRef.current = null;
    };
  }, [scenario]);

  useProjectionSync(projRef, props, generation);
  useEffect(() => apiRef.current?.syncTokens(tokens), [tokens, generation]);
  useEffect(() => {
    if (camera) apiRef.current?.command(camera);
  }, [camera]);

  return <div ref={hostRef} className="h-full w-full" />;
}
