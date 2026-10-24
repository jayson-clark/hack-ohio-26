// Sound design (#50): fire crackle that swells with the burning area, radio
// chirps for urgent events, a soft blip for reroutes, and a chime when a round
// ends. Everything is synthesized with Web Audio, so there are no asset files.
//
// Only the console makes sound (one window, like speech in #40), it's off by
// default, and it ducks while the commander is speaking in the browser
// (speechSynthesis.speaking), so effects never talk over a briefing.

import type { EventKind } from "./protocol";

let ctx: AudioContext | null = null;
let master: GainNode | null = null;
let crackle: GainNode | null = null;
let enabled = false;
let target = 0; // crackle level from the fire, before ducking

const STORAGE_KEY = "firewatch.sound";

export function soundPreference(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === "on";
  } catch {
    return false;
  }
}

/** Turn sound on or off. Must first be turned on from a click: browsers only
 * let audio start after a user gesture. */
export function setSoundEnabled(on: boolean) {
  enabled = on;
  try {
    localStorage.setItem(STORAGE_KEY, on ? "on" : "off");
  } catch {
    // Private windows can refuse storage; the toggle still works this session.
  }
  if (on) start();
  if (master && ctx) master.gain.setTargetAtTime(on ? 0.6 : 0, ctx.currentTime, 0.1);
}

function start() {
  if (ctx) {
    void ctx.resume();
    return;
  }
  ctx = new AudioContext();
  master = ctx.createGain();
  master.gain.value = 0;
  master.connect(ctx.destination);

  // Crackle: sparse random pops through a bandpass, looped. Pops rather than
  // smooth noise, so it reads as burning wood, not static.
  const seconds = 2;
  const buf = ctx.createBuffer(1, ctx.sampleRate * seconds, ctx.sampleRate);
  const data = buf.getChannelData(0);
  for (let i = 0; i < data.length; i++) {
    const pop = Math.random() < 0.0025 ? (Math.random() * 2 - 1) * 0.9 : 0;
    data[i] = pop + (Math.random() * 2 - 1) * 0.04;
  }
  const src = ctx.createBufferSource();
  src.buffer = buf;
  src.loop = true;
  const band = ctx.createBiquadFilter();
  band.type = "bandpass";
  band.frequency.value = 1800;
  band.Q.value = 0.6;
  crackle = ctx.createGain();
  crackle.gain.value = 0;
  src.connect(band).connect(crackle).connect(master);
  src.start();

  // Duck under speech, checked a few times a second.
  window.setInterval(() => {
    if (!ctx || !crackle) return;
    const duck = "speechSynthesis" in window && window.speechSynthesis.speaking ? 0.3 : 1;
    crackle.gain.setTargetAtTime(target * duck, ctx.currentTime, 0.4);
  }, 250);
}

/** Crackle level from the burning cell count. Square root, so a big fire is
 * louder than a small one without drowning everything. */
export function setFireLevel(burningCells: number) {
  target = Math.min(0.9, Math.sqrt(burningCells) / 45);
}

function tone(freq: number, at: number, dur: number, gain: number, type: OscillatorType = "sine") {
  if (!ctx || !master || !enabled) return;
  const osc = ctx.createOscillator();
  const g = ctx.createGain();
  osc.type = type;
  osc.frequency.value = freq;
  const t = ctx.currentTime + at;
  g.gain.setValueAtTime(0, t);
  g.gain.linearRampToValueAtTime(gain, t + 0.01);
  g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
  osc.connect(g).connect(master);
  osc.start(t);
  osc.stop(t + dur + 0.05);
}

function staticBurst(at: number, dur: number) {
  if (!ctx || !master || !enabled) return;
  const buf = ctx.createBuffer(1, Math.ceil(ctx.sampleRate * dur), ctx.sampleRate);
  const d = buf.getChannelData(0);
  for (let i = 0; i < d.length; i++) d[i] = (Math.random() * 2 - 1) * 0.25;
  const src = ctx.createBufferSource();
  src.buffer = buf;
  const band = ctx.createBiquadFilter();
  band.type = "bandpass";
  band.frequency.value = 2500;
  src.connect(band).connect(master);
  src.start(ctx.currentTime + at);
}

/** A cue for an engine event: a radio key-up and two-tone chirp for urgent ones. */
export function playEvent(kind: EventKind) {
  switch (kind) {
    case "town_threatened":
    case "no_safe_route":
    case "road_cut":
      staticBurst(0, 0.12);
      tone(880, 0.12, 0.14, 0.18, "square");
      tone(660, 0.28, 0.18, 0.18, "square");
      break;
    case "route_changed":
      tone(1200, 0, 0.12, 0.12);
      break;
    default:
      break; // town_safe, forecast_shift: the log is enough
  }
}

/** Round over: a short falling three-note chime. */
export function playRoundEnd() {
  [784, 659, 523].forEach((f, i) => tone(f, i * 0.18, 0.5, 0.2, "triangle"));
}
