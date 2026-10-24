// Projector view: no UI chrome, just the projection filling the screen.
// Clicks still place virtual tokens; keys 1-4 choose what a click places.

import { useEffect, useState } from "react";
import { useEngine } from "../shared/engine";
import type { TokenType } from "../shared/protocol";
import { useScenario } from "../shared/scenario";
import { TOKEN_TYPES } from "../shared/tokens";
import { DEFAULT_LAYERS } from "../render/projection";
import ProjectionView from "../render/ProjectionView";

export default function Projector() {
  const { tokens, simGrid, forecast } = useEngine();
  const { scenario, error } = useScenario();
  const [placeType, setPlaceType] = useState<TokenType>("crew");

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const index = Number(e.key) - 1;
      if (index >= 0 && index < TOKEN_TYPES.length) setPlaceType(TOKEN_TYPES[index]);
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
    <div className="h-full cursor-crosshair bg-black">
      {scenario ? (
        <ProjectionView
          scenario={scenario}
          tokens={tokens}
          simGrid={simGrid}
          forecast={forecast}
          layers={DEFAULT_LAYERS}
          placeType={placeType}
          selectedId={null}
        />
      ) : (
        error && <p className="p-6 font-mono text-sm text-red-400">{error}</p>
      )}
    </div>
  );
}
