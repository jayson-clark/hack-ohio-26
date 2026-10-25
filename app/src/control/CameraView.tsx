// The webcam as the engine sees it: the drone's view of the incident. Once the
// board is locked the engine sends a top-down orthophoto, the frame rectified
// and cropped to the map grid with terrain lean corrected
// (VisionStatus.feed_rectified). Then the operational layers the projector no
// longer paints on the table (#198) are drawn over it here, in map cells:
// forecast, routes, towns, stations, units, orders and recommendations.
// Before the lock it's the raw frame with the engine's vision overlay.

import { useEffect, useRef, useState } from "react";
import type { BinaryFrame } from "../shared/binary";
import { Cell, useEngine, type ForecastGrids } from "../shared/engine";
import type { VisionStatus } from "../shared/protocol";
import type { Scenario } from "../shared/scenario";
import { useTowns } from "../console/model";
import { OrdersLayer, PlacesLayer, RecsLayer, RoutesLayer, StationsLayer, TownsLayer, UnitsLayer } from "../console/map/layers";
import { ToggleGroup } from "../console/ui";

const CORNERS = ["NW", "NE", "SE", "SW"] as const;
const noop = () => {};

interface Overlays {
  forecast: boolean;
  routes: boolean;
  towns: boolean;
  resources: boolean;
}

const OVERLAY_LABELS: Record<keyof Overlays, string> = {
  forecast: "Forecast",
  routes: "Routes",
  towns: "Towns",
  resources: "Units",
};

export default function CameraView({
  frame,
  vision,
  scenario,
}: {
  frame: BinaryFrame | null;
  vision: VisionStatus | null;
  scenario: Scenario | null;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [overlays, setOverlays] = useState<Overlays>({ forecast: true, routes: true, towns: true, resources: true });

  useEffect(() => {
    if (!frame) return;
    const next = URL.createObjectURL(new Blob([frame.payload as Uint8Array<ArrayBuffer>], { type: "image/jpeg" }));
    setUrl(next);
    return () => URL.revokeObjectURL(next);
  }, [frame]);

  const on = vision && vision.camera !== "off";
  const rectified = !!(vision?.feed_rectified && scenario);
  return (
    <div className="relative flex h-full items-center justify-center px-6 pt-16 pb-14">
      {on && url && vision.camera === "ok" ? (
        rectified ? (
          <RectifiedFeed url={url} scenario={scenario!} overlays={overlays} />
        ) : (
          <img src={url} alt="Camera feed" className="max-h-full max-w-full rounded-md object-contain" />
        )
      ) : (
        <div className="max-w-sm text-center text-sm text-fg-subtle">
          {!vision ? (
            "Waiting for the engine…"
          ) : !on ? (
            <>
              No camera. Set <code className="font-mono text-fg-muted">CAMERA=0</code> in{" "}
              <code className="font-mono text-fg-muted">.env</code> and restart the engine. Virtual tokens still work.
            </>
          ) : (
            <>
              Can't read camera <code className="font-mono text-fg-muted">{vision.source}</code>. Retrying…
            </>
          )}
        </div>
      )}
      {rectified && (
        <div className="absolute right-3 top-3 z-10">
          <ToggleGroup
            items={(Object.keys(OVERLAY_LABELS) as (keyof Overlays)[]).map((k) => ({ key: k, label: OVERLAY_LABELS[k], on: overlays[k] }))}
            onToggle={(k) => setOverlays((o) => ({ ...o, [k]: !o[k] }))}
          />
        </div>
      )}
    </div>
  );
}

/** The orthophoto in a box of the map's aspect, with the map layers over it. */
function RectifiedFeed({ url, scenario, overlays }: { url: string; scenario: Scenario; overlays: Overlays }) {
  const { routes, units, tokens, recommendations, hello, forecast, simGrid } = useEngine();
  const towns = useTowns(scenario);
  const box = useRef<HTMLDivElement>(null);
  const [px, setPx] = useState(1);
  const { width: W, height: H } = scenario;

  useEffect(() => {
    const el = box.current!;
    const ro = new ResizeObserver(() => setPx(el.clientWidth || 1));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const k = W / px; // map cells per screen pixel, for the layers' pixel sizes
  const reach = hello?.crew_radius ?? 14;
  return (
    <div className="flex h-full w-full items-center justify-center [container-type:size]">
      <div
        ref={box}
        className="relative overflow-hidden rounded-md"
        style={{ aspectRatio: `${W} / ${H}`, width: `min(100cqw, 100cqh * ${W / H})` }}
      >
        <img src={url} alt="Camera feed, top-down" className="absolute inset-0 h-full w-full object-fill" />
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="pointer-events-none absolute inset-0 h-full w-full">
          {overlays.forecast && <ForecastLayer scenario={scenario} forecast={forecast} simGrid={simGrid} />}
          {overlays.routes && <RoutesLayer routes={routes} k={k} highlight={null} />}
          {overlays.towns && <PlacesLayer scenario={scenario} k={k} />}
          {overlays.resources && <StationsLayer stations={hello?.stations ?? []} k={k} />}
          {overlays.towns && <TownsLayer towns={towns} k={k} selected={null} onSelect={noop} />}
          <RecsLayer recs={recommendations} k={k} reach={reach} selected={null} onSelect={noop} />
          {overlays.resources && <UnitsLayer units={units} k={k} />}
          <OrdersLayer tokens={tokens} k={k} reach={reach} selected={null} onSelect={noop} />
        </svg>
      </div>
    </div>
  );
}

// Forecast colors, matching the console map's legend: nearer horizon orange
// over the further one in yellow. Only on ground that isn't already burning.
const NEAR = [245, 130, 50];
const FAR = [250, 205, 110];

/** P(burned) at the first two forecast horizons as a translucent fill. */
function ForecastLayer({ scenario, forecast, simGrid }: { scenario: Scenario; forecast: ForecastGrids | null; simGrid: BinaryFrame | null }) {
  const [href, setHref] = useState<string | null>(null);
  const { width: W, height: H } = scenario;

  useEffect(() => {
    if (!forecast || forecast.width !== W || forecast.height !== H || forecast.horizons.length === 0) return setHref(null);
    const c = document.createElement("canvas");
    c.width = W;
    c.height = H;
    const ctx = c.getContext("2d")!;
    const img = ctx.createImageData(W, H);
    const near = forecast.horizons[0];
    const far = forecast.horizons[1] ?? near;
    const cells = simGrid && simGrid.width === W && simGrid.height === H ? simGrid.payload : null;
    for (let i = 0; i < W * H; i++) {
      if (cells && (cells[i] === Cell.Burning || cells[i] === Cell.Burned)) continue;
      const pn = near[i] / 255;
      const pf = far[i] / 255;
      if (pf < 0.1) continue;
      const [r, g, b] = pn >= 0.1 ? NEAR : FAR;
      img.data.set([r, g, b, Math.round(Math.min(1, Math.max(pn, pf)) * 150)], i * 4);
    }
    ctx.putImageData(img, 0, 0);
    setHref(c.toDataURL());
  }, [forecast, simGrid, W, H]);

  return href ? <image href={href} x={0} y={0} width={W} height={H} preserveAspectRatio="none" style={{ imageRendering: "auto" }} /> : null;
}

/** One-line vision health for the viewport's bottom bar. */
export function VisionReadout({ vision }: { vision: VisionStatus | null }) {
  if (!vision || vision.camera === "off") return <span>Camera off</span>;
  if (vision.camera === "no_signal") return <span className="text-warn">No signal · {vision.source}</span>;
  return (
    <span className="flex items-center gap-3">
      <span>
        {vision.frame_width}×{vision.frame_height} · {vision.fps.toFixed(0)} fps · {vision.markers_seen} markers
      </span>
      <span className="flex items-center gap-1">
        {CORNERS.map((c) => (
          <span
            key={c}
            className={`rounded px-1 ${
              vision.corners_seen.includes(c) ? "bg-ok-soft text-ok" : "bg-surface-2 text-fg-subtle"
            }`}
          >
            {c}
          </span>
        ))}
      </span>
      <span className={vision.board_found ? "text-ok" : "text-warn"}>
        {vision.board_found ? "Board locked" : "Show all four corners"}
      </span>
    </span>
  );
}
