// Projector view: no UI chrome, just the projection filling the screen.
// Clicks still place virtual tokens; keys 1-4 choose what a click places, and
// I makes the next clicks light fires (no console needed at the table).

import { useEffect, useState } from "react";
import { useEngine } from "../shared/engine";
import { useEngineScenario } from "../shared/scenario";
import { TOKEN_TYPES } from "../shared/tokens";
import type { PlaceType } from "../shared/virtualTokens";
import { DEFAULT_LAYERS } from "../render/projection";
import ProjectionView from "../render/ProjectionView";
import { RoundSummaryProjected } from "../control/RoundSummary";
import AttractMode, { useAttract } from "./AttractMode";

export default function Projector() {
  const { tokens, simGrid, forecast, routes, score } = useEngine();
  const { scenario, error } = useEngineScenario();
  const [placeType, setPlaceType] = useState<PlaceType>("crew");
  const attract = useAttract();

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const index = Number(e.key) - 1;
      if (index >= 0 && index < TOKEN_TYPES.length) setPlaceType(TOKEN_TYPES[index]);
      if (e.key === "i") setPlaceType("ignite");
      // Browser fallback: F toggles fullscreen (Tauri opens it fullscreen already).
      if (e.key === "f") {
        if (document.fullscreenElement) document.exitFullscreen();
        else document.documentElement.requestFullscreen();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    // Ignite mode shows only as a different cursor: anything drawn here would
    // land on the table.
    <div className={`relative h-full bg-black ${placeType === "ignite" ? "cursor-cell" : "cursor-crosshair"}`}>
      {scenario ? (
        <ProjectionView
          scenario={scenario}
          tokens={tokens}
          simGrid={simGrid}
          forecast={forecast}
          routes={routes}
          layers={DEFAULT_LAYERS}
          placeType={placeType}
          selectedId={null}
        />
      ) : (
        error && <p className="p-6 font-mono text-sm text-red-400">{error}</p>
      )}
      {scenario && attract && <AttractMode scenario={scenario} />}
      <RoundSummaryProjected score={score} />
    </div>
  );
}
