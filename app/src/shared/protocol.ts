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
  | Units
  | EvacClock
  | Situation
  | PlanResult
  | Calibration
  | ForecastEnvelope
  | Drafts
  | Incidents;
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
  | "evacuate_now"
  | "draft_sent";
export type RecAction = "place" | "move" | "relieve";
export type CameraState = "off" | "no_signal" | "ok";
export type RoundPhase = "sandbox" | "running" | "ended";
export type EndReason = "time" | "contained" | "stopped";
export type CommanderKind = "briefing" | "answer";
export type UnitStatus = "available" | "en_route" | "working" | "blocked" | "grounded" | "reloading" | "resting";
export type EvacStatus = "watch" | "order_soon" | "order_now" | "late" | "evacuating" | "clear" | "trapped";
export type CalibrationPhase = "none" | "pattern" | "review" | "calibrated";
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
  | DraftAction
  | RequestBriefing
  | CalibrationStep
  | EvaluatePlan
  | RequestMutualAid
  | RelieveOrder;
export type CalibrationAction = "start" | "save" | "check" | "cancel" | "clear";

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
  fire_arrival_min: number | null;
  act_by_min: number | null;
  acres_saved: number;
  acres_saved_lo: number;
  acres_saved_hi: number;
  saves: TownEffect[];
  worsens: TownEffect[];
  protects: TownShare[];
  text: string;
  incident: string | null;
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
  mutual_aid: MutualAid | null;
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
 * Crews requested from outside the map (#178), against the round's budget.
 */
export interface MutualAid {
  used: number;
  limit: number | null;
  pending: number;
}
/**
 * Something the incident commander says: an answer or a briefing, about two sentences.
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
  line: number[][];
  fatigue: number;
  ready_in_min: number | null;
  incident: string | null;
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
/**
 * The operator's town board: how soon the fire could reach each town.
 * Sent after each Monte Carlo forecast (never from the emulator), on reset,
 * and on connect.
 */
export interface Situation {
  type: "situation";
  tick: number;
  forecast_tick: number | null;
  towns: TownThreat[];
}
export interface TownThreat {
  town: string;
  population: number;
  structures: number;
  fire_inside: boolean;
  within_30: KofN | null;
  within_60: KofN | null;
  median_min: number | null;
  soonest_min: number | null;
  eta_lo_min: number | null;
  eta_hi_min: number | null;
  route_status: RouteStatus | null;
  exit: string | null;
  drive_min: number | null;
  incident: string | null;
}
/**
 * How many of the forecast's simulations something happened in, with a
 * 90% interval on the true chance (sampling uncertainty, #11).
 */
export interface KofN {
  k: number;
  n: number;
  lo: number;
  hi: number;
}
/**
 * The answer to an evaluate_plan: the plan against doing nothing, on
 * paired simulations under the same assumed wind. Broadcast; a console
 * keeps only the id it asked for.
 */
export interface PlanResult {
  type: "plan_result";
  id: number;
  tick: number;
  n: number;
  horizon_min: number;
  wind: WindState;
  orders: PlanOrderResult[];
  acres_base: number;
  acres_plan: number;
  acres_saved: number;
  acres_saved_lo: number;
  acres_saved_hi: number;
  people_base: number;
  people_plan: number;
  towns: PlanTown[];
  error: string | null;
}
export interface PlanOrderResult {
  token_type: TokenType;
  x: number;
  y: number;
  station: string | null;
  eta_min: number | null;
  counted: boolean;
}
export interface PlanTown {
  town: string;
  base: KofN;
  plan: KofN;
  saves: number;
  worsens: number;
  base_median_min: number | null;
  plan_median_min: number | null;
}
/**
 * Projector calibration (PLAN.md, Calibration; engine/vision/projector.py).
 * Sent on connect, on every calibration_step, while the pattern is being
 * found, and when the engine follows a moved board.
 */
export interface Calibration {
  type: "calibration";
  phase: CalibrationPhase;
  map_to_proj: number[] | null;
  projector: number[] | null;
  pattern: string | null;
  corners_found: number;
  corners_total: number;
  frames: number;
  frames_needed: number;
  error_px: number | null;
  message: string | null;
}
/**
 * The calibrated burn envelope (#12): per forecast horizon, the
 * probability cutoff and margin that the online conformal update has
 * settled on, so that at most `target_miss` of newly burning ground falls
 * outside it in the long run. The UI draws {P >= threshold} grown by
 * margin_cells. Also the running miss rates, to show the promise is kept.
 */
export interface ForecastEnvelope {
  type: "forecast_envelope";
  horizons_min: number[];
  threshold: number[];
  margin_cells: number[];
  target_miss: number;
  miss_recent: (number | null)[];
  miss_overall: (number | null)[];
  scored: number[];
}
export interface Drafts {
  type: "drafts";
  tick: number;
  drafts: Draft[];
}
/**
 * A drafted dispatch order, evacuation alert or briefing (#132). Nothing
 * is delivered anywhere: the operator approves, edits or dismisses it.
 */
export interface Draft {
  id: string;
  kind: "unit_order" | "evac_alert" | "briefing";
  subject: string;
  status: "draft" | "sent" | "dismissed";
  text: string;
  text_es: string | null;
  source: "template" | "llm" | "operator";
  grounded: boolean;
  tick: number;
  sent_tick: number | null;
}
/**
 * Every incident so far (#179). Sent when one starts, merges or goes out,
 * and with the score while any burns.
 */
export interface Incidents {
  type: "incidents";
  tick: number;
  incidents: Incident[];
}
/**
 * One fire on a map that can hold several (#179). Each ignition opens one,
 * named after the nearest place; when two burn into each other, the older
 * id survives.
 */
export interface Incident {
  id: string;
  name: string;
  acres: number;
  growth_ac_h: number;
  x: number;
  y: number;
  started_tick: number;
  active: boolean;
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
 * A question for the incident commander, typed in the console. A new
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
 * Send, dismiss or edit a draft (#132). `text` is the edited text.
 */
export interface DraftAction {
  type: "draft_action";
  id: string;
  action: "send" | "dismiss" | "edit";
  text: string | null;
}
/**
 * Draft a situation briefing now (#132).
 */
export interface RequestBriefing {
  type: "request_briefing";
}
export interface CalibrationStep {
  type: "calibration_step";
  action: CalibrationAction;
}
/**
 * Try a set of orders, and optionally a different wind, from the fire as
 * it is now, without changing anything. Answered by a plan_result (and a
 * PLAN_GRID frame). A newer plan replaces one still running.
 */
export interface EvaluatePlan {
  type: "evaluate_plan";
  id: number;
  orders: PlanOrder[];
  wind: WindState | null;
  horizon_min: number;
}
export interface PlanOrder {
  token_type: TokenType;
  x: number;
  y: number;
}
/**
 * Ask for one more unit of this type from outside the map (#178). It
 * arrives at a staging point after a delay, if the round's budget allows.
 */
export interface RequestMutualAid {
  type: "request_mutual_aid";
  token_type: TokenType;
}
/**
 * Send a fresh unit to take over a crew order (#178). The tired crew keeps
 * working until the fresh one arrives, then goes back to rest.
 */
export interface RelieveOrder {
  type: "relieve_order";
  token_id: string;
}
