"""Engine entry point: WebSocket server plus the main loop.

Run with `uv run server.py` from engine/. The engine holds all state; UI
windows are views that can connect and disconnect at any time.
"""

import asyncio
import logging
import os

from pydantic import ValidationError
from websockets.asyncio.server import ServerConnection, broadcast, serve
from websockets.exceptions import ConnectionClosed

from protocol import (
    Hello,
    ScenarioState,
    Tokens,
    VirtualTokenAdd,
    VirtualTokenMove,
    VirtualTokenRemove,
    client_message_adapter,
)
from scenario import load_scenario
from vision.tokens import TokenTracker
from vision.virtual import VirtualTable

HOST = os.environ.get("ENGINE_HOST", "localhost")
PORT = int(os.environ.get("ENGINE_PORT", "8765"))
SCENARIO = os.environ.get("SCENARIO", "paradise")
TICK_HZ = 10

log = logging.getLogger("engine")


class Engine:
    def __init__(self) -> None:
        self.clients: set[ServerConnection] = set()
        self.tick = 0
        self.scenario = load_scenario(SCENARIO)
        self.tracker = TokenTracker()
        self.virtual = VirtualTable(self.tracker, self.scenario.width, self.scenario.height)
        self._sent_token_version = -1

    def hello_msg(self) -> str:
        s = self.scenario
        return Hello(scenario=s.name, map_width=s.width, map_height=s.height).model_dump_json()

    def tokens_msg(self) -> str:
        return Tokens(tokens=self.tracker.tokens).model_dump_json()

    def state_msg(self) -> str:
        return ScenarioState(tick=self.tick, running=True).model_dump_json()

    async def handle_client(self, ws: ServerConnection) -> None:
        self.clients.add(ws)
        log.info("client connected (%d total)", len(self.clients))
        try:
            await ws.send(self.hello_msg())
            await ws.send(self.state_msg())
            await ws.send(self.tokens_msg())
            async for raw in ws:
                try:
                    msg = client_message_adapter.validate_json(raw)
                except ValidationError as e:
                    log.warning("bad message: %s", e)
                    continue
                self.dispatch(msg)
        except ConnectionClosed:
            pass
        finally:
            self.clients.discard(ws)
            log.info("client disconnected (%d total)", len(self.clients))

    def dispatch(self, msg) -> None:
        match msg:
            case VirtualTokenAdd() | VirtualTokenMove() | VirtualTokenRemove():
                self.virtual.handle(msg)
        # Push token changes immediately rather than waiting for the next tick,
        # so dragging feels responsive.
        self.flush_tokens()

    def flush_tokens(self) -> None:
        if self.tracker.version != self._sent_token_version:
            self._sent_token_version = self.tracker.version
            broadcast(self.clients, self.tokens_msg())

    async def run(self) -> None:
        period = 1 / TICK_HZ
        loop = asyncio.get_running_loop()
        next_tick = loop.time()
        while True:
            self.tick += 1
            self.flush_tokens()
            if self.tick % TICK_HZ == 0:
                broadcast(self.clients, self.state_msg())
            next_tick += period
            await asyncio.sleep(max(0.0, next_tick - loop.time()))


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    engine = Engine()
    async with serve(engine.handle_client, HOST, PORT, max_size=None):
        log.info("listening on ws://%s:%d", HOST, PORT)
        await engine.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
