// The webcam as the engine sees it: camera_frame JPEGs with the vision
// overlay (markers, map outline, placed tokens) already drawn in by the engine.

import { useEffect, useState } from "react";
import type { BinaryFrame } from "../shared/binary";
import type { VisionStatus } from "../shared/protocol";

const CORNERS = ["NW", "NE", "SE", "SW"] as const;

export default function CameraView({ frame, vision }: { frame: BinaryFrame | null; vision: VisionStatus | null }) {
  const [url, setUrl] = useState<string | null>(null);

  useEffect(() => {
    if (!frame) return;
    const next = URL.createObjectURL(new Blob([frame.payload as Uint8Array<ArrayBuffer>], { type: "image/jpeg" }));
    setUrl(next);
    return () => URL.revokeObjectURL(next);
  }, [frame]);

  const on = vision && vision.camera !== "off";
  return (
    <div className="flex h-full items-center justify-center px-6 pt-16 pb-14">
      {on && url && vision.camera === "ok" ? (
        <img src={url} alt="Camera feed" className="max-h-full max-w-full rounded-md object-contain" />
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
    </div>
  );
}

/** One-line vision health for the viewport's bottom bar. */
export function VisionReadout({ vision }: { vision: VisionStatus | null }) {
  if (!vision || vision.camera === "off") return <span>Camera off</span>;
  if (vision.camera === "no_signal") return <span className="text-amber-300">No signal · {vision.source}</span>;
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
              vision.corners_seen.includes(c) ? "bg-emerald-500/15 text-emerald-300" : "bg-surface-2 text-fg-subtle"
            }`}
          >
            {c}
          </span>
        ))}
      </span>
      <span className={vision.board_found ? "text-emerald-300" : "text-amber-300"}>
        {vision.board_found ? "Board locked" : "Show all four corners"}
      </span>
    </span>
  );
}
