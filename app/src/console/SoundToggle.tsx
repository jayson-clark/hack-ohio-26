// Header switch for sound effects (#50), and the hook that feeds them from the
// engine: crackle from the fire, cues from new events and the round ending.

import { useEffect, useRef, useState } from "react";
import { Cell, useEngine } from "../shared/engine";
import type { Event } from "../shared/protocol";
import { playEvent, playRoundEnd, setFireLevel, setSoundEnabled, soundPreference } from "../shared/sound";
import { SoundIcon } from "./icons";

export default function SoundToggle() {
  // Remembered per browser, but audio can only start from a click, so a saved
  // "on" shows as off until clicked once.
  const [on, setOn] = useState(false);
  const remembered = useRef(soundPreference());
  useSoundFeed();

  return (
    <button
      title={on ? "Sound on (fire, alerts)" : remembered.current ? "Click to turn sound back on" : "Sound off"}
      aria-pressed={on}
      onClick={() => {
        setSoundEnabled(!on);
        remembered.current = !on;
        setOn(!on);
      }}
      className={`flex h-7 w-7 items-center justify-center rounded-lg border border-edge transition-colors ${
        on ? "bg-surface-3 text-fg" : "bg-surface-1 text-fg-subtle hover:text-fg"
      }`}
    >
      <SoundIcon on={on} />
    </button>
  );
}

function useSoundFeed() {
  const { simGrid, events, score } = useEngine();

  useEffect(() => {
    if (!simGrid) return;
    let burning = 0;
    for (const c of simGrid.payload) if (c === Cell.Burning) burning++;
    setFireLevel(burning);
  }, [simGrid]);

  // New events only: the store keeps the last 50, so track the last one seen.
  const lastSeen = useRef<Event | undefined>(events[events.length - 1]);
  useEffect(() => {
    const idx = lastSeen.current ? events.lastIndexOf(lastSeen.current) : -1;
    const fresh = idx >= 0 ? events.slice(idx + 1) : events.slice(-1);
    lastSeen.current = events[events.length - 1];
    // One cue per batch is plenty; several at once would just be noise.
    const loudest = fresh.find((e) => ["town_threatened", "no_safe_route", "road_cut"].includes(e.kind)) ?? fresh[0];
    if (loudest) playEvent(loudest.kind);
  }, [events]);

  const phase = score?.phase;
  const prevPhase = useRef(phase);
  useEffect(() => {
    if (prevPhase.current === "running" && phase === "ended") playRoundEnd();
    prevPhase.current = phase;
  }, [phase]);
}
