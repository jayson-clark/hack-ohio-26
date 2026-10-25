import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

BOARD = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BOARD))

import server  # noqa: E402


class Client:
    def __init__(self, base, user="ana", agent="swift-fox", token=""):
        self.base, self.user, self.agent, self.token = base, user, agent, token

    def as_(self, user, agent="", token=None):
        return Client(self.base, user, agent, self.token if token is None else token)

    def call(self, method, path, body=None, headers=None):
        h = {"Content-Type": "application/json", "X-Board-User": self.user}
        if self.agent:
            h["X-Board-Agent"] = self.agent
        if self.token:
            h["X-Board-Token"] = self.token
        h.update(headers or {})
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def get(self, path):
        status, data = self.call("GET", path)
        assert status == 200, data
        return data

    def post(self, path, body=None):
        status, data = self.call("POST", path, body or {})
        assert status == 200, data
        return data

    def patch(self, path, body):
        status, data = self.call("PATCH", path, body)
        assert status == 200, data
        return data


def start(tmp_path, token=""):
    srv = server.make_server(db_path=tmp_path / "board.db", host="127.0.0.1", port=0, token=token)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


@pytest.fixture
def board(tmp_path):
    srv, base = start(tmp_path)
    yield Client(base), srv
    srv.shutdown()


@pytest.fixture
def api(board):
    return board[0]
