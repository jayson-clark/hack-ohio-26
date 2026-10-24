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

All positions are in map-grid coordinates, in cell units (floats allowed):
x runs from 0 to the map width, y from 0 to the map height, origin at the
top-left (north-west) of the map. The map isn't square; Hello carries its size.
"""

import struct
from enum import IntEnum, StrEnum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

PROTOCOL_VERSION = 4


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
    map_width: int
    map_height: int
    sim_minutes_per_tick: float
    forecast_horizons_min: list[float]  # order of the grids in a FORECAST_GRID frame


class WindState(Model):
    speed_ms: float
    # Meteorological: where the wind blows FROM, degrees clockwise from north
    # (map up). 270 is a west wind, pushing fire east (+x).
    from_deg: float


class ScenarioState(Model):
    """Sent once a second, and immediately after ignite, reset or set_wind."""

    type: Literal["scenario_state"] = "scenario_state"
    tick: int
    running: bool
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


class Routes(Model):
    """Every town's evacuation route. Sent after each forecast, on reset, and on connect."""

    type: Literal["routes"] = "routes"
    tick: int  # sim tick the routes were planned at
    routes: list[RouteInfo]


EngineMessage = Annotated[Union[Hello, ScenarioState, Tokens, Routes], Field(discriminator="type")]


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
    """Put the fire out and unburn the map. Tokens stay where they are."""

    type: Literal["reset"] = "reset"


class SetWind(Model):
    type: Literal["set_wind"] = "set_wind"
    speed_ms: float = Field(ge=0, le=40)
    from_deg: float


ClientMessage = Annotated[
    Union[VirtualTokenAdd, VirtualTokenMove, VirtualTokenRemove, Ignite, Reset, SetWind],
    Field(discriminator="type"),
]

client_message_adapter: TypeAdapter[ClientMessage] = TypeAdapter(ClientMessage)


class Protocol(Model):
    """Not sent on the wire. Exists so the TS generator sees both unions."""

    engine: EngineMessage
    client: ClientMessage
