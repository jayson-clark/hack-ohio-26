"""Virtual table mode: fake tokens created from UI clicks.

Behaves like a camera that sees exactly the tokens the UI has placed, and
reports them through the same TokenTracker path real vision uses.
"""

import itertools

from protocol import (
    MAP_SIZE,
    Token,
    TokenSource,
    VirtualTokenAdd,
    VirtualTokenMove,
    VirtualTokenRemove,
)
from vision.tokens import TokenTracker


def _clamp(v: float) -> float:
    return min(max(v, 0.0), float(MAP_SIZE))


class VirtualTable:
    def __init__(self, tracker: TokenTracker) -> None:
        self._tracker = tracker
        self._tokens: dict[str, Token] = {}
        self._ids = itertools.count(1)

    def handle(self, msg: VirtualTokenAdd | VirtualTokenMove | VirtualTokenRemove) -> None:
        match msg:
            case VirtualTokenAdd():
                token_id = f"v{next(self._ids)}"
                self._tokens[token_id] = Token(
                    id=token_id,
                    token_type=msg.token_type,
                    x=_clamp(msg.x),
                    y=_clamp(msg.y),
                    angle=msg.angle,
                    source=TokenSource.VIRTUAL,
                )
            case VirtualTokenMove():
                if (token := self._tokens.get(msg.id)) is None:
                    return
                update = {"x": _clamp(msg.x), "y": _clamp(msg.y)}
                if msg.angle is not None:
                    update["angle"] = msg.angle
                self._tokens[msg.id] = token.model_copy(update=update)
            case VirtualTokenRemove():
                self._tokens.pop(msg.id, None)
        self._tracker.update(TokenSource.VIRTUAL, list(self._tokens.values()))
