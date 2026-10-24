// Projector calibration wizard (PLAN.md, Calibration). The engine runs it: the
// projector shows a pattern, the camera finds it, and the fit is reviewed on
// the table (test grid) before it's saved. Shift+C starts (or redoes) it.

import { useEffect } from "react";
import { calibrationStep, useEngine } from "../shared/engine";
import { Button, Kbd } from "../console/ui";

export default function CalibrationPanel() {
  const { calibration: cal, vision } = useEngine();

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      if (e.key === "C" && e.shiftKey) calibrationStep("start");
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  if (!cal) return null;
  const cameraOn = vision?.camera === "ok";
  const fit = cal.error_px !== null ? `fit ${cal.error_px.toFixed(1)} px` : null;

  return (
    <div className="space-y-2 border-t border-edge pt-2.5 text-xs">
      <div className="flex items-center justify-between">
        <span className="font-medium text-fg">Calibration</span>
        <span className={cal.phase === "calibrated" ? "text-emerald-300" : "text-fg-subtle"}>
          {
            {
              none: "Not calibrated",
              pattern: "Finding pattern…",
              review: "Check the table",
              calibrated: ["Calibrated", fit].filter(Boolean).join(" · "),
            }[cal.phase]
          }
        </span>
      </div>

      {cal.phase === "none" && (
        <p className="text-[11px] leading-relaxed text-fg-subtle">
          The projector letterboxes the map. Open it fullscreen on the projector, make sure the camera sees all four
          corner markers, then calibrate.
        </p>
      )}

      {cal.phase === "pattern" && (
        <div className="space-y-1.5">
          <Progress value={cal.frames / cal.frames_needed} />
          <p className="text-[11px] text-fg-subtle">
            {cal.corners_found} of {cal.corners_total} corners in view · frame {cal.frames} of {cal.frames_needed}
          </p>
        </div>
      )}

      {cal.phase === "review" && (
        <p className="text-[11px] leading-relaxed text-fg-subtle">
          The cyan crosses should sit on the four corner markers and the border on the map's edge.
          {fit && ` (${fit})`}
        </p>
      )}

      {cal.message && <p className="text-[11px] leading-relaxed text-amber-300">{cal.message}</p>}

      <div className="flex flex-wrap gap-1.5">
        {cal.phase === "review" ? (
          <>
            <Button variant="primary" className="flex-1" onClick={() => calibrationStep("save")}>
              Save
            </Button>
            <Button variant="secondary" onClick={() => calibrationStep("start")}>
              Redo
            </Button>
            <Button variant="secondary" onClick={() => calibrationStep("cancel")}>
              Cancel
            </Button>
          </>
        ) : cal.phase === "pattern" ? (
          <Button variant="secondary" className="flex-1" onClick={() => calibrationStep("cancel")}>
            Cancel
          </Button>
        ) : (
          <>
            <Button
              variant={cal.phase === "none" ? "primary" : "secondary"}
              className="flex-1"
              disabled={!cameraOn}
              title={cameraOn ? undefined : "Needs the camera (CAMERA in .env)"}
              onClick={() => calibrationStep("start")}
            >
              {cal.phase === "none" ? "Calibrate" : "Recalibrate"} <Kbd>⇧C</Kbd>
            </Button>
            {cal.phase === "calibrated" && (
              <>
                <Button variant="secondary" onClick={() => calibrationStep("check")}>
                  Test grid
                </Button>
                <Button variant="secondary" onClick={() => calibrationStep("clear")}>
                  Clear
                </Button>
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function Progress({ value }: { value: number }) {
  return (
    <div className="h-1.5 overflow-hidden rounded-full bg-surface-2">
      <div className="h-full bg-ember-400 transition-[width]" style={{ width: `${Math.min(1, value) * 100}%` }} />
    </div>
  );
}
