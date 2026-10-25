// The webcam as the engine sees it. Once the board is locked, the engine sends
// a top-down orthophoto: the frame rectified and cropped to the map grid, with
// terrain lean corrected, so it reads like overhead footage and lines up with
// the console map. Before the lock it's the raw frame with the vision overlay
// (markers, map outline, placed tokens) drawn in.

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
