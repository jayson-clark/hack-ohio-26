/* Generated from engine/protocol.py by `make types`. Do not edit by hand. */

export type EngineMessage = Hello | ScenarioState | Tokens;
export type TokenType = "crew" | "firebreak" | "water" | "bus";
export type TokenSource = "vision" | "virtual";
export type ClientMessage = VirtualTokenAdd | VirtualTokenMove | VirtualTokenRemove | Ignite | Reset | SetWind;

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
