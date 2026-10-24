// WebSocket connection to the Python engine. Every window opens its own
// connection; the engine holds all state, so windows can reload freely.

import { useSyncExternalStore } from "react";
import { BinaryType, parseBinaryFrame, type BinaryFrame } from "./binary";
import type { ClientMessage, EngineMessage, Hello, ScenarioState, Token } from "./protocol";

const ENGINE_URL = import.meta.env.VITE_ENGINE_URL ?? "ws://localhost:8765";
const RECONNECT_MS = 1000;

export interface EngineState {
  status: "connecting" | "open" | "closed";
  hello: Hello | null;
  scenario: ScenarioState | null;
  tokens: Token[];
  /** Latest sim_grid frame (cell states), once the sim sends them. */
  simGrid: BinaryFrame | null;
}

let state: EngineState = { status: "connecting", hello: null, scenario: null, tokens: [], simGrid: null };
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
      const frame = parseBinaryFrame(ev.data as ArrayBuffer);
      if (frame.type === BinaryType.SimGrid) setState({ simGrid: frame });
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
