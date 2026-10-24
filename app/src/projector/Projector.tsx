// Projector view: no UI chrome, just the map filling the screen. Phase 1
// replaces MapView here with the WebGL renderer, which also applies the
// calibration homography.

import { useEffect, useState } from "react";
import MapView from "../shared/MapView";
import type { TokenType } from "../shared/protocol";
import { TOKEN_TYPES } from "../shared/tokens";

export default function Projector() {
  // Virtual table mode with no UI: keys 1-4 choose what a click places.
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
    <div className="flex h-full cursor-crosshair items-center justify-center bg-black">
      <MapView placeType={placeType} className="max-h-full max-w-full" />
    </div>
  );
}
