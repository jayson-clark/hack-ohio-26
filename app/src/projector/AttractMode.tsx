// Attract mode (#48; PLAN.md demo script step 1): when the table has sat idle,
// the projector shows topo-lit terrain with towns glowing and wind drifting
// across it, to draw people in. It ends the moment anything happens.
//
// Drawn on a 2D canvas in map coordinates, placed exactly like ProjectionView
// (letterboxed, or through the projector calibration), so the glows land on
// the towns.

import { useEffect, useRef, useState, type CSSProperties } from "react";
import { Cell, useEngine } from "../shared/engine";
import type { Scenario } from "../shared/scenario";
import { cssMatrix3d, toPixels, type Mat3 } from "../render/homography";

const IDLE_MS = 30_000;
const PARTICLES = 260;
const FORCED = new URLSearchParams(window.location.search).get("attract") === "1";
const WARP_SCALE = 4; // element px per map cell when calibrated, so the canvas stays sharp

/** True once the table has been quiet for IDLE_MS: no tokens, nothing burning, no round. */
export function useAttract(): boolean {
  const { tokens, simGrid, score } = useEngine();
  const burning = !!simGrid && simGrid.payload.includes(Cell.Burning);
  const quiet = tokens.length === 0 && !burning && score?.phase !== "running";
  const [idle, setIdle] = useState(false);
  const [poke, setPoke] = useState(0);

  useEffect(() => {
    const bump = () => setPoke((p) => p + 1);
    window.addEventListener("pointerdown", bump);
    window.addEventListener("keydown", bump);
    return () => {
      window.removeEventListener("pointerdown", bump);
      window.removeEventListener("keydown", bump);
    };
  }, []);

  useEffect(() => {
    setIdle(false);
    if (!quiet) return;
    const t = window.setTimeout(() => setIdle(true), IDLE_MS);
    return () => clearTimeout(t);
  }, [quiet, poke]);

  return FORCED || idle;
}

export default function AttractMode({ scenario, mapToProj = null }: { scenario: Scenario; mapToProj?: Mat3 | null }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const frameRef = useRef<HTMLDivElement>(null);
  const [frame, setFrame] = useState({ w: 1, h: 1 });
  const { scenario: state } = useEngine();
  // Read by the animation loop without restarting it.
  const wind = useRef({ speed: 8, from: 45 });
  if (state) wind.current = { speed: state.wind.speed_ms, from: state.wind.from_deg };

  useEffect(() => {
    const canvas = canvasRef.current!;
    const ctx = canvas.getContext("2d")!;
    const { width: W, height: H, towns } = scenario;
    const parts = Array.from({ length: PARTICLES }, () => ({ x: Math.random() * W, y: Math.random() * H, age: Math.random() }));
    let raf = 0;
    let last = performance.now();

    function frame(now: number) {
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      const rect = canvas.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio, 2);
      if (canvas.width !== Math.round(rect.width * dpr)) {
        canvas.width = Math.round(rect.width * dpr);
        canvas.height = Math.round(rect.height * dpr);
      }
      const k = canvas.width / W; // canvas px per map cell
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.setTransform(k, 0, 0, k, 0, 0);
      const t = now / 1000;

      // Towns breathe slowly, bigger towns brighter, each on its own phase.
      towns.forEach((town, i) => {
        const pulse = 0.5 + 0.5 * Math.sin(t * 1.4 + i * 1.7);
        const r = town.radius * (0.9 + 0.25 * pulse);
        const g = ctx.createRadialGradient(town.x, town.y, 0, town.x, town.y, r);
        const a = 0.3 + 0.35 * pulse * Math.min(1, Math.log10(town.population) / 4);
        g.addColorStop(0, `rgba(255, 196, 120, ${a})`);
        g.addColorStop(1, "rgba(255, 150, 80, 0)");
        ctx.fillStyle = g;
        ctx.beginPath();
        ctx.arc(town.x, town.y, r, 0, Math.PI * 2);
        ctx.fill();
      });

      // Wind streaks, blowing toward from_deg + 180 (clockwise from north, -y).
      const to = ((wind.current.from + 180) * Math.PI) / 180;
      const speed = 4 + wind.current.speed * 1.6; // cells per second
      const dx = Math.sin(to) * speed;
      const dy = -Math.cos(to) * speed;
      ctx.lineCap = "round";
      ctx.lineWidth = 0.45;
      for (const p of parts) {
        p.x += dx * dt;
        p.y += dy * dt;
        p.age += dt * 0.35;
        if (p.age > 1 || p.x < -4 || p.x > W + 4 || p.y < -4 || p.y > H + 4) {
          p.x = Math.random() * W;
          p.y = Math.random() * H;
          p.age = 0;
        }
        const fade = Math.sin(Math.PI * p.age);
        ctx.strokeStyle = `rgba(225, 240, 255, ${0.5 * fade})`;
        ctx.beginPath();
        ctx.moveTo(p.x, p.y);
        ctx.lineTo(p.x - dx * 0.35, p.y - dy * 0.35);
        ctx.stroke();
      }
      raf = requestAnimationFrame(frame);
    }
    raf = requestAnimationFrame(frame);
    return () => cancelAnimationFrame(raf);
  }, [scenario]);

  useEffect(() => {
    const el = frameRef.current!;
    const ro = new ResizeObserver(() => setFrame({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  let box: CSSProperties = {
    aspectRatio: `${scenario.width} / ${scenario.height}`,
    width: `min(100cqw, 100cqh * ${scenario.width / scenario.height})`,
  };
  if (mapToProj) {
    // Map-shaped (scaled up) and warped onto the table, like ProjectionView's overlay.
    const s = WARP_SCALE;
    const [a, b, c, d, e, f, g, i, k] = toPixels(mapToProj, frame.w, frame.h);
    box = {
      position: "absolute",
      left: 0,
      top: 0,
      width: scenario.width * s,
      height: scenario.height * s,
      transformOrigin: "0 0",
      transform: cssMatrix3d([a / s, b / s, c, d / s, e / s, f, g / s, i / s, k]),
    };
  }

  return (
    <div ref={frameRef} className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center [container-type:size]">
      <div className="relative" style={box}>
        <canvas ref={canvasRef} className="absolute inset-0 h-full w-full" />
        {/* Near-black pill: projects as near-darkness, so the title reads over any terrain. */}
        <div className="absolute inset-x-0 bottom-[6%] flex justify-center">
          <div className="rounded-2xl bg-black/80 px-8 py-3 text-center">
            <div className="text-3xl font-semibold tracking-[0.3em] text-white/90">FIRELINE</div>
            <div className="mt-1 text-lg text-white/60">Place a crew on the map to begin</div>
          </div>
        </div>
      </div>
    </div>
  );
}
