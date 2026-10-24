"""WebSocket protocol shared by the engine and the UI.

This file is the source of truth. After changing it, regenerate the TS types
with `make types` and commit both in the same commit (see AGENTS.md).

JSON messages are discriminated on `type`. Binary frames start with the
12-byte header described by BINARY_HEADER (mirrored by hand in
app/src/shared/binary.ts).

All positions are in map-grid coordinates, in cell units (floats allowed):
x runs from 0 to the map width, y from 0 to the map height, origin at the
top-left (north-west) of the map. The map isn't square; Hello carries its size.
"""

import struct
from enum import IntEnum, StrEnum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

PROTOCOL_VERSION = 2


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


class ScenarioState(Model):
    type: Literal["scenario_state"] = "scenario_state"
    tick: int
    running: bool


class Tokens(Model):
    type: Literal["tokens"] = "tokens"
    tokens: list[Token]


EngineMessage = Annotated[Union[Hello, ScenarioState, Tokens], Field(discriminator="type")]


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


ClientMessage = Annotated[
    Union[VirtualTokenAdd, VirtualTokenMove, VirtualTokenRemove], Field(discriminator="type")
]

client_message_adapter: TypeAdapter[ClientMessage] = TypeAdapter(ClientMessage)


class Protocol(Model):
    """Not sent on the wire. Exists so the TS generator sees both unions."""

    engine: EngineMessage
    client: ClientMessage
