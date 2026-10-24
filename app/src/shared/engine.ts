// WebSocket connection to the Python engine. Every window opens its own
// connection; the engine holds all state, so windows can reload freely.

import { useSyncExternalStore } from "react";
import { BinaryType, parseBinaryFrame } from "./binary";
import type { ClientMessage, EngineMessage, Hello, ScenarioState, Token } from "./protocol";

const ENGINE_URL = import.meta.env.VITE_ENGINE_URL ?? "ws://localhost:8765";
const RECONNECT_MS = 1000;

// Cell states in a sim_grid frame (sim.fire in the engine).
export const Cell = { Unburnable: 0, Fuel: 1, Burning: 2, Burned: 3 } as const;

export interface Grid {
  tick: number;
  width: number;
  height: number;
  cells: Uint8Array; // width * height, row-major, row 0 = north
}

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
  simGrid: Grid | null;
  forecast: ForecastGrids | null;
}

let state: EngineState = {
  status: "connecting",
  hello: null,
  scenario: null,
  tokens: [],
  simGrid: null,
  forecast: null,
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
      setState({ hello: msg });
      break;
    case "scenario_state":
      setState({ scenario: msg });
      break;
    case "tokens":
      setState({ tokens: msg.tokens });
      break;
  }
}

function handleBinary(buf: ArrayBuffer) {
  const frame = parseBinaryFrame(buf);
  const { tick, width, height, payload } = frame;
  const cells = width * height;
  switch (frame.type) {
    case BinaryType.SimGrid:
      setState({ simGrid: { tick, width, height, cells: payload } });
      break;
    case BinaryType.ForecastGrid: {
      const n = Math.floor(payload.length / cells);
      const horizons = Array.from({ length: n }, (_, i) => payload.subarray(i * cells, (i + 1) * cells));
      setState({ forecast: { tick, width, height, horizons } });
      break;
    }
  }
}

function connect() {
  setState({ status: "connecting" });
  const socket = new WebSocket(ENGINE_URL);
  socket.binaryType = "arraybuffer";
  ws = socket;

  socket.onopen = () => setState({ status: "open" });
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
