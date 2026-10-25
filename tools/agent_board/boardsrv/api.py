"""HTTP: the JSON API, the SSE stream and the built web UI, on one port.

Reads are open. Writes need an X-Board-User header (plus X-Board-Agent for
agents) and, on a board with a token, X-Board-Token. See model.Board.authorize.
"""

import gzip
import json
import mimetypes
import os
import queue
import re
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import github
from .model import BadRequest, NotFound, Unauthorized, clean

WEB = Path(__file__).resolve().parent.parent / "web" / "dist"
ROUTE_RE = re.compile(r"/api/(\w+)(?:/([^/]+))?(?:/(\w+))?(?:/([^/]+))?")

NOT_BUILT = b"""<!doctype html><meta charset="utf-8"><title>Agent Board</title>
<body style="font:15px system-ui;margin:40px;max-width:560px;color:#333">
<h2>The board's web UI isn't built</h2>
<p>Run <code>make board-web</code> (or <code>cd tools/agent_board/web &amp;&amp; pnpm install &amp;&amp; pnpm build</code>) and reload.
The API under <code>/api/</code> works without it.</p>"""


class StaticCache:
    """Built files, read once and gzipped once."""

    def __init__(self, root):
        self.root = root
        self.files = {}

    def get(self, rel):
        path = (self.root / rel).resolve()
        if self.root.resolve() not in path.parents or not path.is_file():
            return None
        mtime = path.stat().st_mtime
        hit = self.files.get(path)
        if hit and hit[0] == mtime:
            return hit[1]
        data = path.read_bytes()
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json", "image/svg+xml"):
            ctype += "; charset=utf-8" if "charset" not in ctype else ""
        entry = {"data": data, "gz": gzip.compress(data, 6) if len(data) > 1024 else None, "type": ctype}
        self.files[path] = (mtime, entry)
        return entry


static = StaticCache(WEB)


class Handler(BaseHTTPRequestHandler):
    server_version = "agent-board/2"
    protocol_version = "HTTP/1.1"
    board = None  # set by server.make_server()

    def log_message(self, fmt, *args):
        if os.environ.get("BOARD_LOG"):
            super().log_message(fmt, *args)

    def ident(self, required=True):
        h = self.headers
        user = clean(h.get("X-Board-User"), 60)
        if not user:
            if not required:
                return None
            raise BadRequest("missing X-Board-User header")
        pr = clean(h.get("X-Board-PR"), 10)
        return {
            "user": user,
            "agent": clean(h.get("X-Board-Agent"), 60),
            "branch": clean(h.get("X-Board-Branch"), 120),
            "host": clean(h.get("X-Board-Host"), 120),
            "pr": int(pr) if pr.isdigit() else None,
            "pr_title": clean(unquote(h.get("X-Board-PR-Title") or ""), 200),
        }

    def send(self, status, payload, ctype="application/json", cache="no-store"):
        data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        gz = None
        if len(data) > 2048 and "gzip" in (self.headers.get("Accept-Encoding") or ""):
            gz = gzip.compress(data, 5)
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        if gz:
            self.send_header("Content-Encoding", "gzip")
            data = gz
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", cache)
        self.send_header("Vary", "Accept-Encoding")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            body = json.loads(self.rfile.read(n))
        except json.JSONDecodeError as e:
            raise BadRequest(f"bad JSON: {e}") from e
        if not isinstance(body, dict):
            raise BadRequest("body must be a JSON object")
        return body

    def do_GET(self):
        self.route("GET")

    def do_HEAD(self):
        self.route("GET")

    def do_POST(self):
        self.route("POST")

    def do_PATCH(self):
        self.route("PATCH")

    def do_DELETE(self):
        self.route("DELETE")

    def route(self, method):
        url = urlparse(self.path)
        path = url.path.rstrip("/") or "/"
        params = {k: v[-1] for k, v in parse_qs(url.query).items()}
        try:
            if method == "GET" and not path.startswith("/api/"):
                return self.serve_static(path)
            if method == "GET" and path == "/api/events":
                return self.events()
            result = self.api(method, path, params)
            if result is None:
                raise NotFound(f"no route {method} {path}")
            self.send(200, result)
        except BadRequest as e:
            self.send(400, {"error": str(e)})
        except Unauthorized as e:
            self.send(401, {"error": str(e)})
        except NotFound as e:
            self.send(404, {"error": str(e)})
        except (ValueError, KeyError) as e:
            self.send(400, {"error": f"bad request: {e}"})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:  # keep the server up; report the bug to the caller
            self.send(500, {"error": f"{type(e).__name__}: {e}"})

    def serve_static(self, path):
        if path in ("/", "/index.html"):
            f = static.get("index.html")
            if not f:
                return self.send(200, NOT_BUILT, "text/html; charset=utf-8")
            return self.send_file(f, "no-cache")
        f = static.get(path.lstrip("/"))
        if not f:
            raise NotFound(f"no file {path}")
        # Vite puts a content hash in every asset name, so they never change.
        self.send_file(f, "public, max-age=31536000, immutable" if path.startswith("/assets/") else "no-cache")

    def send_file(self, f, cache):
        gz = f["gz"] if f["gz"] and "gzip" in (self.headers.get("Accept-Encoding") or "") else None
        data = gz or f["data"]
        self.send_response(200)
        self.send_header("Content-Type", f["type"])
        if gz:
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", cache)
        self.send_header("Vary", "Accept-Encoding")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def api(self, method, path, params):
        m = ROUTE_RE.fullmatch(path)
        if not m:
            return None
        res, key, action, sub = m.groups()
        key = unquote(key) if key else key
        b = self.board
        if method == "GET":
            if res == "state" and not key:
                return b.state()
            if res == "entries" and not key:
                return b.list_entries(params)
            if res == "entries" and key and not action:
                return b.entry(int(key))
            if res == "entries" and action == "history":
                return b.history(int(key))
            if res == "entries" and action == "votes":
                return b.votes(int(key))
            if res == "tags":
                return b.tags()
            if res == "suggest":
                return b.suggest(params)
            if res == "search":
                return {"entries": b.list_entries({**params, "limit": params.get("limit") or 20}) if params.get("q") else [],
                        "messages": b.search_messages(params) if params.get("q") else []}
            if res == "channels" and not key:
                return b.channels()
            if res == "channels" and action == "messages":
                return b.list_messages(key, params)
            if res == "messages" and key and not action:
                return b.thread(int(key))
            if res == "messages" and action == "wait":
                return b.wait_for_reply(int(key), params)
            if res == "agents" and not key:
                return b.agents()
            if res == "activity":
                return b.activity(params)
            if res == "claims" and not key:
                return b.active_claims(params.get("agent"))
            if res == "claims" and key == "check":
                return b.check_paths(self.ident(required=False), params)
            if res == "digest":
                return b.digest(params)
            if res == "github":
                gh, at = b.kv_get("github", None)
                return {**gh, "updated_at": at} if gh else {"issues": [], "pulls": [], "merged": [], "updated_at": 0}
            if res == "export":
                ident = self.ident()
                b.authorize(ident, self.headers.get("X-Board-Token"))
                return b.export()
            if res == "inbox":
                ident = self.ident()
                b.touch_agent(ident)
                return b.inbox(ident, params)
            if res == "health":
                return {"ok": True, "web": static.get("index.html") is not None}
            return None

        if method == "POST" and res == "people" and action == "token":
            if not b.token or self.headers.get("X-Board-Token") != b.token:
                raise Unauthorized("issuing a personal token needs the board's shared BOARD_TOKEN")
            return b.issue_token(key)
        ident = self.ident()
        b.authorize(ident, self.headers.get("X-Board-Token"))
        body = self.body()
        if method == "POST" and res == "heartbeat":
            b.touch_agent(ident, clean(body["status"], 200) if "status" in body else None)
            return {"ok": True}
        b.touch_agent(ident)
        if method == "POST" and res == "entries" and not key:
            return b.create_entry(ident, body)
        if method == "PATCH" and res == "entries" and key and not action:
            return b.update_entry(ident, int(key), body)
        if method == "POST" and res == "entries" and action == "vote":
            return b.vote(ident, int(key), body)
        if method == "POST" and res == "entries" and action == "links":
            return b.link(ident, int(key), body)
        if method == "DELETE" and res == "entries" and action == "links" and sub:
            return b.unlink(int(key), int(sub))
        if method == "POST" and res == "channels" and not key:
            return b.create_channel(ident, body)
        if method == "PATCH" and res == "channels" and key:
            return b.update_channel(key, body)
        if method == "POST" and res == "messages" and not key:
            return b.post_message(ident, body)
        if method == "POST" and res == "messages" and action in ("resolve", "reopen"):
            return b.set_resolved(int(key), action == "resolve")
        if method == "POST" and res == "reactions":
            return b.react(ident, body)
        if method == "POST" and res == "claims" and not key:
            return b.claim(ident, body)
        if method == "POST" and res == "claims" and key == "release":
            return b.release(ident, body)
        if method == "POST" and res == "github":
            return github.ingest(b, body, f"cli:{ident['user']}" + (f"/{ident['agent']}" if ident["agent"] else ""))
        return None

    def events(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")  # don't let a reverse proxy buffer the stream
        self.end_headers()
        bus = self.board.bus
        sub = bus.subscribe()
        try:
            self.wfile.write(b"retry: 2000\n\n")
            self.wfile.flush()
            while True:
                try:
                    event = sub.get(timeout=15)
                    self.wfile.write(f"data: {json.dumps(event)}\n\n".encode())
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            bus.unsubscribe(sub)
            self.close_connection = True
