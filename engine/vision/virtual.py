"""Virtual table mode: fake tokens created from UI clicks.

Behaves like a camera that sees exactly the tokens the UI has placed, and
reports them through the same TokenTracker path real vision uses.
"""

import itertools
import math

from protocol import (
    Token,
    TokenSource,
    VirtualTokenAdd,
    VirtualTokenMove,
    VirtualTokenRemove,
)
from vision.tokens import TokenTracker


class VirtualTable:
    def __init__(self, tracker: TokenTracker, width: int, height: int) -> None:
        self._tracker = tracker
        # Clamp just inside the far edge, so int(x) is always a valid cell index.
        self._max_x = math.nextafter(float(width), 0.0)
        self._max_y = math.nextafter(float(height), 0.0)
        self._tokens: dict[str, Token] = {}
        self._ids = itertools.count(1)

    def _clamp_x(self, v: float) -> float:
        return min(max(v, 0.0), self._max_x)

    def _clamp_y(self, v: float) -> float:
        return min(max(v, 0.0), self._max_y)

    def handle(self, msg: VirtualTokenAdd | VirtualTokenMove | VirtualTokenRemove) -> None:
        match msg:
            case VirtualTokenAdd():
                token_id = f"v{next(self._ids)}"
                self._tokens[token_id] = Token(
                    id=token_id,
                    token_type=msg.token_type,
                    x=self._clamp_x(msg.x),
                    y=self._clamp_y(msg.y),
                    angle=msg.angle,
                    source=TokenSource.VIRTUAL,
                )
            case VirtualTokenMove():
                if (token := self._tokens.get(msg.id)) is None:
                    return
                update = {"x": self._clamp_x(msg.x), "y": self._clamp_y(msg.y)}
                if msg.angle is not None:
                    update["angle"] = msg.angle
                self._tokens[msg.id] = token.model_copy(update=update)
            case VirtualTokenRemove():
                self._tokens.pop(msg.id, None)
        self._tracker.update(TokenSource.VIRTUAL, list(self._tokens.values()))
