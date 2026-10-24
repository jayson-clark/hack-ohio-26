/* Generated from engine/protocol.py by `make types`. Do not edit by hand. */

export type EngineMessage = Hello | ScenarioState | Tokens;
export type TokenType = "crew" | "firebreak" | "water" | "bus";
export type TokenSource = "vision" | "virtual";
export type ClientMessage = VirtualTokenAdd | VirtualTokenMove | VirtualTokenRemove;

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
  map_size: number;
}
export interface ScenarioState {
  type: "scenario_state";
  tick: number;
  running: boolean;
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
