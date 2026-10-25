// WebSocket connection to the Python engine. Every window opens its own
// connection; the engine holds all state, so windows can reload freely.

import { useSyncExternalStore } from "react";
import { BinaryType, parseBinaryFrame, type BinaryFrame } from "./binary";
import type {
  Calibration,
  CalibrationAction,
  ClientMessage,
  CommanderMessage,
  EngineMessage,
  EvacClock,
  Draft,
  ForecastEnvelope,
  Event,
  Hello,
  PlanOrder,
  PlanResult,
  Recommendation,
  RouteInfo,
  UnitInfo,
  ScenarioState,
  Score,
  Situation,
  Token,
  VisionStatus,
  WindState,
  Incident,
  TokenType,
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

/** A plan's answer (#123) and its PLAN_GRID: P(burned by the horizon) without and with the plan, 0-255. */
export interface PlanState {
  /** The id of the newest evaluate_plan this window sent, or 0 before any. */
  pending: number;
  result: PlanResult | null;
  grids: { id: number; width: number; height: number; base: Uint8Array; plan: Uint8Array } | null;
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
  /** The calibrated burn envelope's cutoffs and running miss rates (#12). */
  envelope: ForecastEnvelope | null;
  /** Drafted dispatch orders and evacuation alerts awaiting the operator (#132). */
  dispatchDrafts: Draft[];
  /** Fire units (#104): where each is, and its route and ETA while en route. */
  units: UnitInfo[];
  /** Separate fires on the map (#179), oldest first. */
  incidents: Incident[];
  /** Recent events, oldest first. Cleared on reconnect. */
  events: Event[];
  /** Crew placement recommendations, best first (cards and markers: #45). */
  recommendations: Recommendation[];
  /** Camera and marker detection health (camera "off" in virtual table mode). */
  vision: VisionStatus | null;
  /** Projector calibration: the wizard's phase and the map -> projector matrix. */
  calibration: Calibration | null;
  /** Latest camera_frame (a JPEG with the vision overlay), while a camera is on. */
  cameraFrame: BinaryFrame | null;
  /** The town board (#122): how soon fire could reach each town, after each forecast. */
  situation: Situation | null;
  /** This window's plan what-if (#123). */
  plan: PlanState;
  /** Round phase, resource limits and score (scoreboard: #47). */
  score: Score | null;
  /** What the commander has said (briefings and answers), oldest first. For #29. */
  transcript: CommanderMessage[];
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
  envelope: null,
  dispatchDrafts: [],
  units: [],
  incidents: [],
  events: [],
  recommendations: [],
  vision: null,
  calibration: null,
  cameraFrame: null,
  situation: null,
  plan: { pending: 0, result: null, grids: null },
  score: null,
  transcript: [],
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
          envelope: null,
          dispatchDrafts: [],
          units: [],
          incidents: [],
          events: [],
          recommendations: [],
          transcript: [],
          score: null,
          situation: null,
          plan: { pending: 0, result: null, grids: null },
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
    case "incidents":
      setState({ incidents: msg.incidents });
      break;
    case "routes":
      setState({ routes: msg.routes });
      break;
    case "evac_clock":
      setState({ evacClock: msg });
      break;
    case "drafts":
      setState({ dispatchDrafts: msg.drafts });
      break;
    case "forecast_envelope":
      setState({ envelope: msg });
      break;
    case "recommendations":
      setState({ recommendations: msg.recommendations });
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
      // The fire's clock going back means a reset or a new round: the last
      // fire's briefings and events no longer apply.
      if (state.score && msg.tick < state.score.tick) setState({ score: msg, transcript: [], events: [] });
      else setState({ score: msg });
      break;
    case "calibration":
      setState({ calibration: msg });
      break;
    case "situation":
      setState({ situation: msg });
      break;
    case "plan_result":
      // Plans are broadcast to every window; keep only the one this window asked for.
      if (msg.id === state.plan.pending) setState({ plan: { ...state.plan, result: msg } });
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
    case BinaryType.PlanGrid: {
      // The header's tick is the plan id it belongs to.
      if (frame.tick !== state.plan.pending) break;
      const { width, height, payload } = frame;
      const cells = width * height;
      const grids = {
        id: frame.tick,
        width,
        height,
        base: payload.slice(0, cells),
        plan: payload.slice(cells, 2 * cells),
      };
      setState({ plan: { ...state.plan, grids } });
      break;
    }
  }
}

function connect() {
  setState({ status: "connecting" });
  const socket = new WebSocket(ENGINE_URL);
  socket.binaryType = "arraybuffer";
  ws = socket;

  socket.onopen = () => {
    setState({ status: "open", events: [] });
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

/** Ask the incident commander a question; the answer arrives as a commander_message. */
export function askCommander(text: string) {
  const q = text.trim();
  if (q) send({ type: "commander_query", text: q.slice(0, 500) });
}

/** Drive the projector calibration wizard (start, save, check, cancel, clear). */
export function calibrationStep(action: CalibrationAction) {
  send({ type: "calibration_step", action });
}

/** Order a town out (or take the order back). */
export function orderEvacuation(town: string, ordered: boolean) {
  send({ type: "order_evacuation", town, ordered });
}

/** Send, dismiss or edit a drafted order or alert (#132). Nothing goes out for real. */
export function draftAction(id: string, action: "send" | "dismiss" | "edit", text?: string) {
  send({ type: "draft_action", id, action, text: text ?? null });
}

/** Ask the engine to draft a situation briefing (#132). */
export function requestBriefing() {
  send({ type: "request_briefing" });
}

// Plan ids only need to be unique per window and session; start somewhere
// random so two consoles rarely pick the same one.
let planSeq = Math.floor(Math.random() * 1e6);

/** Run a set of orders (and an assumed wind) against doing nothing (#123). The
 * answer lands in `plan`; an older answer still on its way is ignored. */
export function evaluatePlan(orders: PlanOrder[], wind: WindState | null, horizonMin: number) {
  const id = ++planSeq;
  setState({ plan: { ...state.plan, pending: id } });
  send({ type: "evaluate_plan", id, orders, wind, horizon_min: horizonMin });
}

/** Forget the plan's answer (the plan was cleared or dispatched). */
export function clearPlan() {
  setState({ plan: { pending: 0, result: null, grids: null } });
}

/** Place a recommended crew where the engine suggested it. */
export function acceptRecommendation(id: string) {
  send({ type: "accept_recommendation", id });
}

/** Send a fresh crew to take over a tiring crew order (#178). */
export function relieveOrder(tokenId: string) {
  send({ type: "relieve_order", token_id: tokenId });
}

/** Ask for one more unit from outside the map (#178), within the round's budget. */
export function requestMutualAid(tokenType: TokenType) {
  send({ type: "request_mutual_aid", token_type: tokenType });
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
