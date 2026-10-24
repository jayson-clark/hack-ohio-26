from protocol import (
    MAP_SIZE,
    TokenSource,
    TokenType,
    VirtualTokenAdd,
    VirtualTokenMove,
    VirtualTokenRemove,
    client_message_adapter,
)
from vision.tokens import TokenTracker
from vision.virtual import VirtualTable


def test_virtual_tokens_flow_through_tracker():
    tracker = TokenTracker()
    table = VirtualTable(tracker)

    table.handle(VirtualTokenAdd(token_type=TokenType.CREW, x=10, y=20))
    [token] = tracker.tokens
    assert token.source == TokenSource.VIRTUAL
    assert (token.x, token.y) == (10, 20)

    table.handle(VirtualTokenMove(id=token.id, x=999, y=-5))
    [moved] = tracker.tokens
    assert (moved.x, moved.y) == (MAP_SIZE, 0)

    table.handle(VirtualTokenRemove(id=token.id))
    assert tracker.tokens == []


def test_tracker_version_only_bumps_on_change():
    tracker = TokenTracker()
    tracker.update(TokenSource.VISION, [])
    assert tracker.version == 0
    VirtualTable(tracker).handle(VirtualTokenRemove(id="missing"))
    assert tracker.version == 0


def test_client_message_parses_by_type():
    msg = client_message_adapter.validate_json(
        '{"type": "virtual_token_add", "token_type": "bus", "x": 1, "y": 2}'
    )
    assert isinstance(msg, VirtualTokenAdd)
