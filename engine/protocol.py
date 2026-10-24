"""WebSocket protocol shared by the engine and the UI.

This file is the source of truth. After changing it, regenerate the TS types
with `make types` and commit both in the same commit (see AGENTS.md).

JSON messages are discriminated on `type`. Binary frames start with the
12-byte header described by BINARY_HEADER (mirrored by hand in
app/src/shared/binary.ts), followed by a payload:

- SIM_GRID: width*height uint8 cell states, row-major, row 0 = north, every
  tick. Values are sim.fire's UNBURNABLE=0, FUEL=1, BURNING=2, BURNED=3.
- FORECAST_GRID: one width*height uint8 grid per forecast horizon, stacked in
  the order of Hello.forecast_horizons_min (so the payload is
  len(horizons)*width*height bytes). Each byte is P(burned by that horizon)
  scaled to 0-255. `tick` is the sim tick the forecast started from. Sent
  whenever a forecast finishes (a few per second), and once, all zero, on
  reset.
- CAMERA_FRAME: one JPEG of the webcam with the vision overlay drawn on it
  (markers, map outline, placed tokens), for the console's camera view.
  width/height are the JPEG's size and `tick` counts feed frames. A few per
  second, only while the engine has a camera (CAMERA in .env).

All positions are in map-grid coordinates, in cell units (floats allowed):
x runs from 0 to the map width, y from 0 to the map height, origin at the
top-left (north-west) of the map. The map isn't square; Hello carries its size.
"""

import struct
from enum import IntEnum, StrEnum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

PROTOCOL_VERSION = 17


# --- Binary frames ---------------------------------------------------------

class BinaryType(IntEnum):
    SIM_GRID = 1
    FORECAST_GRID = 2
    CAMERA_FRAME = 3


# type: u8, 3 pad bytes, tick: u32, width: u16, height: u16 (little-endian)
BINARY_HEADER = struct.Struct("<B3xIHH")


def pack_binary(kind: BinaryType, tick: int, width: int, height: int, payload: bytes) -> bytes:
    return BINARY_HEADER.pack(kind, tick, width, height) + payload


# --- Shared types ----------------------------------------------------------

class Model(BaseModel):
    # Fields with defaults are always present on the wire, so mark them
    # required in the generated TS types.
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)


class TokenType(StrEnum):
    CREW = "crew"
    FIREBREAK = "firebreak"
    WATER = "water"
    BUS = "bus"


class TokenSource(StrEnum):
    VISION = "vision"
    VIRTUAL = "virtual"


class Token(Model):
    id: str
    token_type: TokenType
    x: float
    y: float
    angle: float = 0.0  # radians, clockwise from +x
    source: TokenSource


# --- Engine -> UI ----------------------------------------------------------

class Hello(Model):
    type: Literal["hello"] = "hello"
    protocol_version: int = PROTOCOL_VERSION
    scenario: str
    crew_radius: float  # cells: a crew's reach (sim.effects.CREW_RADIUS), for drawing it
    map_width: int
    map_height: int
    sim_minutes_per_tick: float
    forecast_horizons_min: list[float]  # order of the grids in a FORECAST_GRID frame
    speech_to_text: bool  # push-to-talk works (the engine has the voice extra installed)
    stations: list["StationInfo"]  # where fire units come from (#104); air bases may be off the map


class WindState(Model):
    speed_ms: float
    # Meteorological: where the wind blows FROM, degrees clockwise from north
    # (map up). 270 is a west wind, pushing fire east (+x).
    from_deg: float


class ScenarioState(Model):
    """Sent once a second, and immediately after ignite, reset, set_wind,
    set_running and set_speed."""

    type: Literal["scenario_state"] = "scenario_state"
    tick: int
    running: bool  # false while paused, and once a round has ended
    paused: bool
    speed: float  # sim steps per engine tick (1 = SIM_MINUTES_PER_TICK sim-minutes every 0.1 s)
    wind: WindState
    burning_cells: int
    burned_cells: int


class Tokens(Model):
    type: Literal["tokens"] = "tokens"
    tokens: list[Token]


class RouteStatus(StrEnum):
    CLEAR = "clear"
    RISKY = "risky"  # some edge is fairly likely to burn before the bus passes
    CUT = "cut"  # no safe zone is reachable


class RouteInfo(Model):
    town: str
    safe_zone: str | None  # None when the route is cut
    points: list[list[float]]  # [x, y] polyline in map coords, town first
    length_m: float
    eta_min: float  # drive time in sim minutes
    risk: float  # max P(an edge burns by the time the bus reaches it), 0..1
    status: RouteStatus
    bus: str | None  # token id when this is a bus token's route; then `town` is "Bus <id>"


class Routes(Model):
    """Every town's evacuation route. Sent after each forecast, on reset, and on connect."""

    type: Literal["routes"] = "routes"
    tick: int  # sim tick the routes were planned at
    routes: list[RouteInfo]


class EventKind(StrEnum):
    ROAD_CUT = "road_cut"  # fire reached a road on a town's current route
    ROUTE_CHANGED = "route_changed"  # a town was rerouted to another way out
    NO_SAFE_ROUTE = "no_safe_route"  # a town has no reachable safe zone
    TOWN_THREATENED = "town_threatened"  # most simulations have fire in the town within 30 min
    TOWN_SAFE = "town_safe"  # a threatened town has dropped out of the fire's 30-min path
    FORECAST_SHIFT = "forecast_shift"  # the next hour's likely burn area moved a lot
    ROUND_ENDED = "round_ended"  # with the final score
    UNIT_ARRIVED = "unit_arrived"  # a dispatched crew, dozer or tanker reached its token
    UNIT_BLOCKED = "unit_blocked"  # burning roads keep a ground unit from getting through
    TANKERS_GROUNDED = "tankers_grounded"  # too windy to fly


class Event(Model):
    kind: EventKind
    tick: int
    town: str | None
    text: str  # one plain sentence, ready for an event log or a briefing


class Events(Model):
    """Things worth telling the operator about, sent as they happen."""

    type: Literal["events"] = "events"
    events: list[Event]


class TownEffect(Model):
    town: str
    hits: int  # rollouts in which the placement changes whether fire reaches the town
    n: int  # rollouts run
    lo: float  # 90% interval on hits / n (sampling uncertainty, #11), 0..1
    hi: float


class TownShare(Model):
    town: str
    share: float  # mean drop in the fraction of the town that burns by T+60, 0..1


class RecAction(StrEnum):
    PLACE = "place"  # put a new token here
    MOVE = "move"  # every token of the type is placed: move `move_token` here instead (#77)


class Recommendation(Model):
    id: str  # pass back in accept_recommendation
    token_type: TokenType
    action: RecAction
    x: float  # map coords: where to place it, or where to move it to
    y: float
    move_token: str | None  # for a move, the token to pick up
    from_x: float | None  # for a move, where that token is now
    from_y: float | None
    # Accept can do it: true for placing, and for moving a virtual token. A
    # physical token has to be moved by hand, so its card is advice only.
    auto: bool
    benefit: float  # mean person-equivalents spared per rollout (the ranking score)
    benefit_lo: float  # 90% interval on benefit; only placements with benefit_lo > 0 are sent (#11)
    benefit_hi: float
    confidence: str  # how firmly to state it: "high" or "moderate"
    station: str | None  # which station's unit would go (#104)
    eta_min: float | None  # and how long it takes to get there, sim minutes
    acres_saved: float  # mean acres the placement keeps from burning by T+60
    saves: list[TownEffect]  # without it the fire reaches the town; with it, it doesn't
    worsens: list[TownEffect]  # the reverse: the placement deflects fire onto the town
    protects: list[TownShare]  # towns where less burns with it, biggest drop first
    text: str  # one sentence for a card or a briefing


class StationInfo(Model):
    name: str
    x: float  # map coords; an air base can be off the map
    y: float
    kind: str  # "ground" (engines, crews, dozers by road) or "air" (tankers)


class UnitStatus(StrEnum):
    AVAILABLE = "available"
    EN_ROUTE = "en_route"
    WORKING = "working"
    BLOCKED = "blocked"  # no open road gets there; retrying
    GROUNDED = "grounded"  # tankers can't fly in this wind; retrying


class UnitInfo(Model):
    id: str  # e.g. "Jarbo Gap Station 36 crew"
    station: str
    token_type: TokenType
    status: UnitStatus
    token_id: str | None  # the token (order) it's assigned to
    x: float  # where it is now, map coords
    y: float
    eta_min: float | None  # sim minutes until it arrives, while en route
    path: list[list[float]]  # its route, origin to target, while en route


class Units(Model):
    """Every fire unit (#104). Sent when one changes status, and a few times
    a second while any is en route, so the map can draw them driving in."""

    type: Literal["units"] = "units"
    tick: int
    units: list[UnitInfo]


class Recommendations(Model):
    """Best first. Sent every few seconds while a fire burns, and empty on reset."""

    type: Literal["recommendations"] = "recommendations"
    tick: int
    recommendations: list[Recommendation]


class CameraState(StrEnum):
    OFF = "off"  # no CAMERA configured: virtual table only
    NO_SIGNAL = "no_signal"  # configured, but can't open or read it
    OK = "ok"


class VisionStatus(Model):
    """Sent once a second, and on connect."""

    type: Literal["vision_status"] = "vision_status"
    camera: CameraState
    source: str  # the CAMERA setting: an index or a file path
    fps: float
    frame_width: int
    frame_height: int
    markers_seen: int  # ArUco markers detected in the latest frame, any ID
    corners_seen: list[str]  # corner markers ("NW", "NE", "SE", "SW") in the latest frame
    # A camera->map homography has been solved (all four corners seen at
    # once). It is kept while corners are covered, so tokens still track.
    board_found: bool


class RoundPhase(StrEnum):
    SANDBOX = "sandbox"  # free play: no limits, no timer
    RUNNING = "running"
    ENDED = "ended"  # the fire is frozen and the score is final


class EndReason(StrEnum):
    TIME = "time"  # the round timer ran out
    CONTAINED = "contained"  # nothing is burning any more
    STOPPED = "stopped"  # the operator ended it


class ResourceUse(Model):
    token_type: TokenType
    limit: int | None  # None = unlimited (always, in the sandbox)
    used: int  # tokens of this type that are taking effect


class WaterCooldown(Model):
    id: str  # water token id
    ready_in_min: float  # sim minutes until it can drop again (0 = ready once moved)


class TownScore(Model):
    name: str
    population: int
    evacuated: int
    structures: int
    structures_lost: int


class Score(Model):
    """The game layer's state. Sent once a second, immediately when the round
    starts or ends, and when a token goes over or back under its limit."""

    type: Literal["score"] = "score"
    tick: int
    phase: RoundPhase
    end_reason: EndReason | None
    elapsed_min: float  # sim minutes since the round started (0 in the sandbox)
    duration_min: float
    resources: list[ResourceUse]
    inactive_tokens: list[str]  # ids over their type's limit, which do nothing
    water_cooldowns: list[WaterCooldown]
    people_total: int
    people_evacuated: int
    structures_total: int
    structures_lost: int
    acres_burned: float
    towns: list[TownScore]


class CommanderKind(StrEnum):
    BRIEFING = "briefing"  # unprompted, from an event
    ANSWER = "answer"  # a reply to commander_query


class CommanderMessage(Model):
    """Something the incident commander says. Short enough to speak aloud."""

    type: Literal["commander_message"] = "commander_message"
    kind: CommanderKind
    tick: int
    text: str
    # Every number in `text` came from a simulation tool (always true for
    # templated briefings; checked for LLM answers).
    grounded: bool
    event: EventKind | None  # what triggered a briefing


class Transcript(Model):
    """What push-to-talk heard. A non-empty text is also asked of the commander."""

    type: Literal["transcript"] = "transcript"
    text: str
    error: str | None  # why there's no text: not installed, no mic, didn't catch that


class CommanderSpeech(Model):
    """Text for the console to speak (voice mode "console"). An answer
    streams as several of these with the same `utterance`, one per sentence;
    a briefing is one. Already rewritten for speech ("Highway 70")."""

    type: Literal["commander_speech"] = "commander_speech"
    utterance: str  # sentences with the same id belong to one answer or briefing
    kind: CommanderKind
    text: str
    urgent: bool  # a briefing worth a radio tone first (threatened town, no way out)


EngineMessage = Annotated[
    Union[Hello, ScenarioState, Tokens, Routes, Events, Recommendations, VisionStatus, Score, CommanderMessage,
          CommanderSpeech, Transcript, Units],
    Field(discriminator="type"),
]


# --- UI -> engine ----------------------------------------------------------

class VirtualTokenAdd(Model):
    type: Literal["virtual_token_add"] = "virtual_token_add"
    token_type: TokenType
    x: float
    y: float
    angle: float = 0.0


class VirtualTokenMove(Model):
    type: Literal["virtual_token_move"] = "virtual_token_move"
    id: str
    x: float
    y: float
    angle: float | None = None


class VirtualTokenRemove(Model):
    type: Literal["virtual_token_remove"] = "virtual_token_remove"
    id: str


class Ignite(Model):
    type: Literal["ignite"] = "ignite"
    x: float
    y: float


class Reset(Model):
    """Put the fire out and unburn the map. Tokens stay where they are. Also
    abandons any round and returns to the sandbox."""

    type: Literal["reset"] = "reset"


class LoadScenario(Model):
    """Switch to another scenario under assets/scenarios/. The engine rebuilds
    the fire, layers, routing and game from it, returns to the sandbox, and
    re-sends hello (the map size can change, so the UI must re-read terrain)."""

    type: Literal["load_scenario"] = "load_scenario"
    scenario: str = Field(min_length=1, max_length=64)


class SetWind(Model):
    type: Literal["set_wind"] = "set_wind"
    speed_ms: float = Field(ge=0, le=40)
    from_deg: float


class SetRunning(Model):
    """Pause (false) or resume (true) the fire. A paused round's clock stops too."""

    type: Literal["set_running"] = "set_running"
    running: bool


class SetSpeed(Model):
    """How many sim steps run per engine tick; fractions spread steps out."""

    type: Literal["set_speed"] = "set_speed"
    speed: float = Field(ge=0.25, le=8)


class StepOnce(Model):
    """Advance the fire one tick while paused (ignored while running)."""

    type: Literal["step_once"] = "step_once"


class CommanderQuery(Model):
    """A question for the incident commander, typed or transcribed. A new
    question cancels one still being answered."""

    type: Literal["commander_query"] = "commander_query"
    text: str = Field(min_length=1, max_length=500)


class VoiceMode(StrEnum):
    OFF = "off"
    CONSOLE = "console"  # the console window speaks commander_speech (Web Speech API)
    MAC = "mac"  # the engine speaks with macOS `say` (fallback if the webview's voices are poor)


class SetVoice(Model):
    """How the commander speaks. Off by default; the console sends its saved choice on connect."""

    type: Literal["set_voice"] = "set_voice"
    mode: VoiceMode


class PttStart(Model):
    """Push-to-talk pressed: the engine starts recording and the commander stops talking."""

    type: Literal["ptt_start"] = "ptt_start"


class PttStop(Model):
    """Push-to-talk released: the engine transcribes and asks the commander."""

    type: Literal["ptt_stop"] = "ptt_stop"


class AcceptRecommendation(Model):
    """Place the recommended token (as a virtual token) where it was recommended."""

    type: Literal["accept_recommendation"] = "accept_recommendation"
    id: str


class StartRound(Model):
    """Reset the map and start a timed, limited round, igniting at the
    scenario's ignition point if it has one."""

    type: Literal["start_round"] = "start_round"


class EndRound(Model):
    """End the running round now, freezing the fire and the score."""

    type: Literal["end_round"] = "end_round"


ClientMessage = Annotated[
    Union[
        VirtualTokenAdd, VirtualTokenMove, VirtualTokenRemove, Ignite, Reset, LoadScenario, SetWind, AcceptRecommendation,
        StartRound, EndRound, SetRunning, SetSpeed, StepOnce,
        CommanderQuery,
        SetVoice,
        PttStart,
        PttStop,
    ],
    Field(discriminator="type"),
]

client_message_adapter: TypeAdapter[ClientMessage] = TypeAdapter(ClientMessage)


class Protocol(Model):
    """Not sent on the wire. Exists so the TS generator sees both unions."""

    engine: EngineMessage
    client: ClientMessage


Hello.model_rebuild()  # StationInfo is defined after Hello
