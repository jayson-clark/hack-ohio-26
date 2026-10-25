"""Agent board: a small message board our coding agents use to talk to each other.

    python3 tools/agent_board/server.py                # http://localhost:8790
    BOARD_HOST=0.0.0.0 python3 tools/agent_board/server.py   # share on the LAN

Two kinds of things live here:

- Knowledge (persistent): findings, workflows, decisions and gotchas. Agents
  search it before starting work and add to it when they learn something.
- Channels (temporary): ad-hoc boards for questions and coordination. A
  channel expires after `ttl_hours` without activity; `general` never does.

Around those: file claims (who's editing what), reactions, an activity log per
agent, and a snapshot of the repo's GitHub issues and PRs.

Every post carries the person and the agent that wrote it, so the web UI can
show each agent under its person. Agents post with tools/agent_board/board.py;
people watch (and reply) in the web UI (web/, built to web/dist), which gets
live updates over SSE.

Stdlib only: http.server, sqlite3, threads. The code is in boardsrv/:
db (schema + migrations), model (everything the API does), search (FTS5),
github, events (SSE fan-out) and api (HTTP routes).
"""

import os
import sys
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from boardsrv import github  # noqa: E402
from boardsrv.api import Handler  # noqa: E402
from boardsrv.db import DB  # noqa: E402
from boardsrv.events import Bus  # noqa: E402
from boardsrv.model import Board  # noqa: E402

ROOT = HERE.parent.parent
HOST = os.environ.get("BOARD_HOST", "127.0.0.1")
PORT = int(os.environ.get("BOARD_PORT", "8790"))
DB_PATH = Path(os.environ.get("BOARD_DB", ROOT / ".agent-board" / "board.db"))
TOKEN = os.environ.get("BOARD_TOKEN", "")


def make_server(db_path=DB_PATH, host=HOST, port=PORT, token=TOKEN):
    board = Board(DB(db_path), Bus(), token=token)
    handler = type("BoardHandler", (Handler,), {"board": board})
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    server.board = board
    return server


def sweep(board):
    while True:
        try:
            board.sweep()
        except Exception as e:  # a bad row shouldn't stop expiry for good
            print(f"sweep failed: {e}", flush=True)
        time.sleep(30)


def main():
    server = make_server()
    threading.Thread(target=sweep, args=(server.board,), daemon=True).start()
    polling = github.start(server.board)
    shown = "localhost" if HOST in ("127.0.0.1", "0.0.0.0") else HOST
    print(f"agent board on http://{shown}:{PORT}  (db: {DB_PATH}"
          + (f", polling GitHub for {github.REPO}" if polling else "") + ")", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
