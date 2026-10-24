// WebSocket connection to the Python engine. Every window opens its own
// connection; the engine holds all state, so windows can reload freely.

import { useSyncExternalStore } from "react";
import { BinaryType, parseBinaryFrame, type BinaryFrame } from "./binary";
import { interrupt, speak } from "./speech";
import type {
  ClientMessage,
  CommanderMessage,
  EngineMessage,
  EvacClock,
  Event,
  Hello,
  Recommendation,
  RouteInfo,
  UnitInfo,
  ScenarioState,
  Score,
  Token,
  Transcript,
  VisionStatus,
  VoiceMode,
} from "./protocol";

const ENGINE_URL = import.meta.env.VITE_ENGINE_URL ?? "ws://localhost:8765";
const RECONNECT_MS = 1000;
// How many recent events (road cuts, reroutes) the store keeps for the event log.
const MAX_EVENTS = 50;
// How much of the commander transcript the store keeps.
const MAX_TRANSCRIPT = 40;

// Cell states in a sim_grid frame (sim.fire in the engine).
export const Cell = { Unburnable: 0, Fuel: 1, Burning: 2, Burned: 3 } as const;

export interface ForecastGrids {
  tick: number; // sim tick the forecast started from
  width: number;
  height: number;
  // One width*height grid per Hello.forecast_horizons_min entry, in order:
  // P(burned by that horizon) scaled to 0-255.
  horizons: Uint8Array[];
}

export interface EngineState {
  status: "connecting" | "open" | "closed";
  hello: Hello | null;
  scenario: ScenarioState | null;
  tokens: Token[];
  /** Latest sim_grid frame (cell states), once the sim sends them. */
  simGrid: BinaryFrame | null;
  /** Latest forecast_grid frame, split into one grid per horizon. */
  forecast: ForecastGrids | null;
  /** Every town's evacuation route, replanned after each forecast. */
  routes: RouteInfo[];
  /** When each town has to be ordered out (#121), most urgent first. */
  evacClock: EvacClock | null;
  /** Fire units (#104): where each is, and its route and ETA while en route. */
  units: UnitInfo[];
  /** Recent events, oldest first. Cleared on reconnect. */
  events: Event[];
  /** Crew placement recommendations, best first (cards and markers: #45). */
  recommendations: Recommendation[];
  /** Camera and marker detection health (camera "off" in virtual table mode). */
  vision: VisionStatus | null;
  /** Latest camera_frame (a JPEG with the vision overlay), while a camera is on. */
  cameraFrame: BinaryFrame | null;
  /** Round phase, resource limits and score (scoreboard: #47). */
  score: Score | null;
  /** What the commander has said (briefings and answers), oldest first. For #29. */
  transcript: CommanderMessage[];
  /** How the commander speaks (off by default); remembered per browser. */
  voiceMode: VoiceMode;
  /** Push-to-talk: held down now, and what it heard last time (cleared when pressed again). */
  listening: boolean;
  heard: Transcript | null;
}

let state: EngineState = {
  status: "connecting",
  hello: null,
  scenario: null,
  tokens: [],
  simGrid: null,
  forecast: null,
  routes: [],
  evacClock: null,
  units: [],
  events: [],
  recommendations: [],
  vision: null,
  cameraFrame: null,
  score: null,
  transcript: [],
  voiceMode: loadVoiceMode(),
  listening: false,
  heard: null,
};
const listeners = new Set<() => void>();
let ws: WebSocket | null = null;
let started = false;

function setState(patch: Partial<EngineState>) {
  state = { ...state, ...patch };
  listeners.forEach((l) => l());
}

function handleMessage(msg: EngineMessage) {
  switch (msg.type) {
    case "hello":
      // A different scenario (load_scenario, #57) means everything tied to the
      // old map is stale: grids are a different size and the towns differ.
      if (state.hello && state.hello.scenario !== msg.scenario) {
        setState({
          hello: msg,
          simGrid: null,
          forecast: null,
          routes: [],
          evacClock: null,
          units: [],
          events: [],
          recommendations: [],
          transcript: [],
          score: null,
        });
      } else {
        setState({ hello: msg });
      }
      break;
    case "scenario_state":
      setState({ scenario: msg });
      break;
    case "tokens":
      setState({ tokens: msg.tokens });
      break;
    case "units":
      setState({ units: msg.units });
      break;
    case "routes":
      setState({ routes: msg.routes });
      break;
    case "evac_clock":
      setState({ evacClock: msg });
      break;
    case "recommendations":
      setState({ recommendations: msg.recommendations });
      break;
    case "transcript":
      setState({ heard: msg });
      break;
    case "commander_speech":
      if (state.voiceMode === "console") speak(msg);
      break;
    case "commander_message":
      setState({ transcript: [...state.transcript, msg].slice(-MAX_TRANSCRIPT) });
      break;
    case "events":
      setState({ events: [...state.events, ...msg.events].slice(-MAX_EVENTS) });
      break;
    case "vision_status":
      setState({ vision: msg });
      break;
    case "score":
      setState({ score: msg });
      break;
  }
}

function handleBinary(buf: ArrayBuffer) {
  const frame = parseBinaryFrame(buf);
  switch (frame.type) {
    case BinaryType.SimGrid:
      setState({ simGrid: frame });
      break;
    case BinaryType.ForecastGrid: {
      const { tick, width, height, payload } = frame;
      const cells = width * height;
      const n = Math.floor(payload.length / cells);
      const horizons = Array.from({ length: n }, (_, i) => payload.subarray(i * cells, (i + 1) * cells));
      setState({ forecast: { tick, width, height, horizons } });
      break;
    }
    case BinaryType.CameraFrame:
      setState({ cameraFrame: frame });
      break;
  }
}

function connect() {
  setState({ status: "connecting" });
  const socket = new WebSocket(ENGINE_URL);
  socket.binaryType = "arraybuffer";
  ws = socket;

  socket.onopen = () => {
    setState({ status: "open", events: [] });
    send({ type: "set_voice", mode: state.voiceMode });
  };
  socket.onclose = () => {
    ws = null;
    setState({ status: "closed" });
    setTimeout(connect, RECONNECT_MS);
  };
  socket.onmessage = (ev) => {
    if (typeof ev.data === "string") {
      handleMessage(JSON.parse(ev.data) as EngineMessage);
    } else {
      handleBinary(ev.data as ArrayBuffer);
    }
  };
}

export function send(msg: ClientMessage) {
  if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
}

const VOICE_KEY = "firewatch.voiceMode";

function loadVoiceMode(): VoiceMode {
  try {
    const v = localStorage.getItem(VOICE_KEY);
    if (v === "console" || v === "mac") return v;
  } catch {
    // storage can be blocked; voice just starts off
  }
  return "off";
}

/** Turn the commander's voice off, on in this console, or on through the Mac's `say`. */
export function setVoiceMode(mode: VoiceMode) {
  try {
    localStorage.setItem(VOICE_KEY, mode);
  } catch {
    // not remembered, but still applied
  }
  setState({ voiceMode: mode });
  send({ type: "set_voice", mode });
}

/** Push-to-talk down: the commander stops talking and the engine starts recording. */
export function pttStart() {
  if (state.listening) return;
  interrupt();
  setState({ listening: true, heard: null });
  send({ type: "ptt_start" });
}

/** Push-to-talk up: the engine transcribes, sends a transcript, and asks the commander. */
export function pttStop() {
  if (!state.listening) return;
  setState({ listening: false });
  send({ type: "ptt_stop" });
}

/** Ask the incident commander a question; the answer arrives as a commander_message. */
export function askCommander(text: string) {
  const q = text.trim();
  if (q) send({ type: "commander_query", text: q.slice(0, 500) });
}

/** Order a town out (or take the order back). */
export function orderEvacuation(town: string, ordered: boolean) {
  send({ type: "order_evacuation", town, ordered });
}

/** Place a recommended crew where the engine suggested it. */
export function acceptRecommendation(id: string) {
  send({ type: "accept_recommendation", id });
}

function subscribe(listener: () => void) {
  if (!started) {
    started = true;
    connect();
  }
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useEngine(): EngineState {
  return useSyncExternalStore(subscribe, () => state);
}
