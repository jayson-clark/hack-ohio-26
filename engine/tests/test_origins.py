"""The engine's WebSocket server only accepts the app's own pages (and non-browser clients)."""

import asyncio

import pytest
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve
from websockets.exceptions import InvalidStatus

from server import allowed_origins


def test_default_origins_cover_vite_and_tauri():
    origins = allowed_origins()
    assert "http://localhost:1420" in origins and "tauri://localhost" in origins
    assert None in origins  # scripts and tests send no Origin header


def test_setting_is_comma_separated_and_trimmed():
    assert allowed_origins(" http://a:1, http://b:2 ,") == ["http://a:1", "http://b:2", None]


async def _connect(port: int, origin: str | None) -> str:
    async with connect(f"ws://localhost:{port}", origin=origin) as ws:
        return await ws.recv()


@pytest.mark.parametrize(
    ("origin", "accepted"),
    [("http://localhost:1420", True), ("tauri://localhost", True), (None, True), ("https://evil.example", False)],
)
def test_server_rejects_other_origins(origin, accepted):
    async def run():
        async def hello(ws):
            await ws.send("hi")

        async with serve(hello, "localhost", 0, origins=allowed_origins()) as server:
            port = server.sockets[0].getsockname()[1]
            if accepted:
                assert await _connect(port, origin) == "hi"
            else:
                with pytest.raises(InvalidStatus) as e:
                    await _connect(port, origin)
                assert e.value.response.status_code == 403

    asyncio.run(run())
