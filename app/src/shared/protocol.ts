/* Generated from engine/protocol.py by `make types`. Do not edit by hand. */

export type EngineMessage =
  | Hello
  | ScenarioState
  | Tokens
  | Routes
  | Events
  | Recommendations
  | VisionStatus
  | Score
  | CommanderMessage
  | CommanderSpeech
  | Transcript
  | Units
  | EvacClock;
export type TokenType = "crew" | "firebreak" | "water" | "bus";
export type TokenSource = "vision" | "virtual";
export type RouteStatus = "clear" | "risky" | "cut";
export type EventKind =
  | "road_cut"
  | "route_changed"
  | "no_safe_route"
  | "town_threatened"
  | "town_safe"
  | "forecast_shift"
  | "round_ended"
  | "unit_arrived"
  | "unit_blocked"
  | "tankers_grounded"
  | "evacuate_now";
export type RecAction = "place" | "move";
export type CameraState = "off" | "no_signal" | "ok";
export type RoundPhase = "sandbox" | "running" | "ended";
export type EndReason = "time" | "contained" | "stopped";
export type CommanderKind = "briefing" | "answer";
export type UnitStatus = "available" | "en_route" | "working" | "blocked" | "grounded";
export type EvacStatus = "watch" | "order_soon" | "order_now" | "late" | "evacuating" | "clear" | "trapped";
export type ClientMessage =
  | VirtualTokenAdd
  | VirtualTokenMove
  | VirtualTokenRemove
  | Ignite
  | Reset
  | LoadScenario
  | SetWind
  | AcceptRecommendation
  | StartRound
  | EndRound
  | SetRunning
  | SetSpeed
  | StepOnce
  | CommanderQuery
  | OrderEvacuation
  | SetVoice
  | PttStart
  | PttStop;
export type VoiceMode = "off" | "console" | "mac";

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
  crew_radius: number;
  map_width: number;
  map_height: number;
  sim_minutes_per_tick: number;
  forecast_horizons_min: number[];
  speech_to_text: boolean;
  stations: StationInfo[];
}
export interface StationInfo {
  name: string;
  x: number;
  y: number;
  kind: string;
}
/**
 * Sent once a second, and immediately after ignite, reset, set_wind,
 * set_running and set_speed.
 */
export interface ScenarioState {
  type: "scenario_state";
  tick: number;
  running: boolean;
  paused: boolean;
  speed: number;
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
  action: RecAction;
  x: number;
  y: number;
  move_token: string | null;
  from_x: number | null;
  from_y: number | null;
  auto: boolean;
  benefit: number;
  benefit_lo: number;
  benefit_hi: number;
  confidence: string;
  station: string | null;
  eta_min: number | null;
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
  lo: number;
  hi: number;
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
 * The game layer's state. Sent once a second, immediately when the round
 * starts or ends, and when a token goes over or back under its limit.
 */
export interface Score {
  type: "score";
  tick: number;
  phase: RoundPhase;
  end_reason: EndReason | null;
  elapsed_min: number;
  duration_min: number;
  resources: ResourceUse[];
  inactive_tokens: string[];
  water_cooldowns: WaterCooldown[];
  people_total: number;
  people_evacuated: number;
  structures_total: number;
  structures_lost: number;
  acres_burned: number;
  towns: TownScore[];
}
export interface ResourceUse {
  token_type: TokenType;
  limit: number | null;
  used: number;
}
export interface WaterCooldown {
  id: string;
  ready_in_min: number;
}
export interface TownScore {
  name: string;
  population: number;
  evacuated: number;
  structures: number;
  structures_lost: number;
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
/**
 * Text for the console to speak (voice mode "console"). An answer
 * streams as several of these with the same `utterance`, one per sentence;
 * a briefing is one. Already rewritten for speech ("Highway 70").
 */
export interface CommanderSpeech {
  type: "commander_speech";
  utterance: string;
  kind: CommanderKind;
  text: string;
  urgent: boolean;
}
/**
 * What push-to-talk heard. A non-empty text is also asked of the commander.
 */
export interface Transcript {
  type: "transcript";
  text: string;
  error: string | null;
}
/**
 * Every fire unit (#104). Sent when one changes status, and a few times
 * a second while any is en route, so the map can draw them driving in.
 */
export interface Units {
  type: "units";
  tick: number;
  units: UnitInfo[];
}
export interface UnitInfo {
  id: string;
  station: string;
  token_type: TokenType;
  status: UnitStatus;
  token_id: string | null;
  x: number;
  y: number;
  eta_min: number | null;
  path: number[][];
}
/**
 * When each town has to be ordered out (#121): fire arrival from a long
 * forecast against the time to empty the town through shared exits. Sent
 * when that forecast lands, on an order, and on connect.
 */
export interface EvacClock {
  type: "evac_clock";
  tick: number;
  forecast_tick: number | null;
  horizon_min: number;
  towns: TownEvac[];
}
export interface TownEvac {
  town: string;
  status: EvacStatus;
  ordered_tick: number | null;
  people: number;
  vehicles: number;
  mobilize_min: number;
  clearance_min: number | null;
  last_car_out_tick: number | null;
  order_by_tick: number | null;
  order_by_bound: boolean;
  fire_tick: number | null;
  reach: number;
  n: number;
  p_safe: number;
  p_safe_lo: number;
  p_safe_hi: number;
  p_safe_bound: boolean;
  exits: EvacExit[];
  shares_with: string[];
}
export interface EvacExit {
  safe_zone: string;
  share: number;
  bottleneck_vph: number;
  drive_min: number;
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
 * Put the fire out and unburn the map. Tokens stay where they are. Also
 * abandons any round and returns to the sandbox.
 */
export interface Reset {
  type: "reset";
}
/**
 * Switch to another scenario under assets/scenarios/. The engine rebuilds
 * the fire, layers, routing and game from it, returns to the sandbox, and
 * re-sends hello (the map size can change, so the UI must re-read terrain).
 */
export interface LoadScenario {
  type: "load_scenario";
  scenario: string;
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
/**
 * Reset the map and start a timed, limited round, igniting at the
 * scenario's ignition point if it has one.
 */
export interface StartRound {
  type: "start_round";
}
/**
 * End the running round now, freezing the fire and the score.
 */
export interface EndRound {
  type: "end_round";
}
/**
 * Pause (false) or resume (true) the fire. A paused round's clock stops too.
 */
export interface SetRunning {
  type: "set_running";
  running: boolean;
}
/**
 * How many sim steps run per engine tick; fractions spread steps out.
 */
export interface SetSpeed {
  type: "set_speed";
  speed: number;
}
/**
 * Advance the fire one tick while paused (ignored while running).
 */
export interface StepOnce {
  type: "step_once";
}
/**
 * A question for the incident commander, typed or transcribed. A new
 * question cancels one still being answered.
 */
export interface CommanderQuery {
  type: "commander_query";
  text: string;
}
/**
 * Order a town out (or take the order back).
 */
export interface OrderEvacuation {
  type: "order_evacuation";
  town: string;
  ordered: boolean;
}
/**
 * How the commander speaks. Off by default; the console sends its saved choice on connect.
 */
export interface SetVoice {
  type: "set_voice";
  mode: VoiceMode;
}
/**
 * Push-to-talk pressed: the engine starts recording and the commander stops talking.
 */
export interface PttStart {
  type: "ptt_start";
}
/**
 * Push-to-talk released: the engine transcribes and asks the commander.
 */
export interface PttStop {
  type: "ptt_stop";
}
