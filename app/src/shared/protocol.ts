/* Generated from engine/protocol.py by `make types`. Do not edit by hand. */

export type EngineMessage =
  Hello | ScenarioState | Tokens | Routes | Events | Recommendations | VisionStatus | CommanderMessage;
export type TokenType = "crew" | "firebreak" | "water" | "bus";
export type TokenSource = "vision" | "virtual";
export type RouteStatus = "clear" | "risky" | "cut";
export type EventKind =
  "road_cut" | "route_changed" | "no_safe_route" | "town_threatened" | "town_safe" | "forecast_shift";
export type CameraState = "off" | "no_signal" | "ok";
export type CommanderKind = "briefing" | "answer";
export type ClientMessage =
  VirtualTokenAdd | VirtualTokenMove | VirtualTokenRemove | Ignite | Reset | SetWind | AcceptRecommendation;

/**
 * Not sent on the wire. Exists so the TS generator sees both unions.
 */
export interface Protocol {
  engine: EngineMessage;
  client: ClientMessage;
}
export interface Hello {
  type: "hello";
  protocol_version: number;
  scenario: string;
  map_width: number;
  map_height: number;
  sim_minutes_per_tick: number;
  forecast_horizons_min: number[];
}
/**
 * Sent once a second, and immediately after ignite, reset or set_wind.
 */
export interface ScenarioState {
  type: "scenario_state";
  tick: number;
  running: boolean;
  wind: WindState;
  burning_cells: number;
  burned_cells: number;
}
export interface WindState {
  speed_ms: number;
  from_deg: number;
}
export interface Tokens {
  type: "tokens";
  tokens: Token[];
}
export interface Token {
  id: string;
  token_type: TokenType;
  x: number;
  y: number;
  angle: number;
  source: TokenSource;
}
/**
 * Every town's evacuation route. Sent after each forecast, on reset, and on connect.
 */
export interface Routes {
  type: "routes";
  tick: number;
  routes: RouteInfo[];
}
export interface RouteInfo {
  town: string;
  safe_zone: string | null;
  points: number[][];
  length_m: number;
  eta_min: number;
  risk: number;
  status: RouteStatus;
  bus: string | null;
}
/**
 * Things worth telling the operator about, sent as they happen.
 */
export interface Events {
  type: "events";
  events: Event[];
}
export interface Event {
  kind: EventKind;
  tick: number;
  town: string | null;
  text: string;
}
/**
 * Best first. Sent every few seconds while a fire burns, and empty on reset.
 */
export interface Recommendations {
  type: "recommendations";
  tick: number;
  recommendations: Recommendation[];
}
export interface Recommendation {
  id: string;
  token_type: TokenType;
  x: number;
  y: number;
  benefit: number;
  acres_saved: number;
  saves: TownEffect[];
  worsens: TownEffect[];
  protects: TownShare[];
  text: string;
}
export interface TownEffect {
  town: string;
  hits: number;
  n: number;
}
export interface TownShare {
  town: string;
  share: number;
}
/**
 * Sent once a second, and on connect.
 */
export interface VisionStatus {
  type: "vision_status";
  camera: CameraState;
  source: string;
  fps: number;
  frame_width: number;
  frame_height: number;
  markers_seen: number;
  corners_seen: string[];
  board_found: boolean;
}
/**
 * Something the incident commander says. Short enough to speak aloud.
 */
export interface CommanderMessage {
  type: "commander_message";
  kind: CommanderKind;
  tick: number;
  text: string;
  grounded: boolean;
  event: EventKind | null;
}
export interface VirtualTokenAdd {
  type: "virtual_token_add";
  token_type: TokenType;
  x: number;
  y: number;
  angle: number;
}
export interface VirtualTokenMove {
  type: "virtual_token_move";
  id: string;
  x: number;
  y: number;
  angle: number | null;
}
export interface VirtualTokenRemove {
  type: "virtual_token_remove";
  id: string;
}
export interface Ignite {
  type: "ignite";
  x: number;
  y: number;
}
/**
 * Put the fire out and unburn the map. Tokens stay where they are.
 */
export interface Reset {
  type: "reset";
}
export interface SetWind {
  type: "set_wind";
  speed_ms: number;
  from_deg: number;
}
/**
 * Place the recommended token (as a virtual token) where it was recommended.
 */
export interface AcceptRecommendation {
  type: "accept_recommendation";
  id: string;
}
