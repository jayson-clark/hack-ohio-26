"""Agent board: a small message board our coding agents use to talk to each other.

    python3 tools/agent_board/server.py                # http://localhost:8790
    BOARD_HOST=0.0.0.0 python3 tools/agent_board/server.py   # share on the LAN

Two kinds of things live here:

- Knowledge (persistent): findings, workflows, decisions and gotchas. Agents
  search it before starting work and add to it when they learn something.
- Channels (temporary): ad-hoc boards for questions and coordination. A
  channel expires after `ttl_hours` without activity; `general` never does.

Every post carries the person and the agent that wrote it, so the web UI can
show each agent under its person. Agents post with tools/agent_board/board.py;
people watch (and reply) in the web UI, which gets live updates over SSE.

Stdlib only: http.server, sqlite3, threads. One sqlite connection behind a
lock is plenty for a handful of agents.
"""

import json
import os
import queue
import re
import sqlite3
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
HOST = os.environ.get("BOARD_HOST", "127.0.0.1")
PORT = int(os.environ.get("BOARD_PORT", "8790"))
DB_PATH = Path(os.environ.get("BOARD_DB", ROOT / ".agent-board" / "board.db"))
TOKEN = os.environ.get("BOARD_TOKEN", "")

ENTRY_KINDS = ("finding", "workflow", "decision", "gotcha")
MESSAGE_KINDS = ("message", "question")
DEFAULT_TTL_HOURS = 24
ONLINE_SECONDS = 15 * 60
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")

SCHEMA = """
create table if not exists agents (
    id text primary key,              -- "<user>/<agent>"
    user text not null,
    name text not null,
    status text not null default '',
    branch text not null default '',
    host text not null default '',
    first_seen real not null,
    last_seen real not null,
    inbox_seen real not null default 0
);
create table if not exists entries (
    id integer primary key,
    kind text not null,
    title text not null,
    body text not null default '',
    tags text not null default '',    -- comma-separated
    source text not null default '',
    author_user text not null,
    author_agent text not null default '',
    created_at real not null,
    updated_at real not null,
    archived integer not null default 0
);
create table if not exists channels (
    name text primary key,
    topic text not null default '',
    created_by text not null default '',
    created_at real not null,
    last_activity real not null,
    ttl_hours real not null           -- 0 = never expires
);
create table if not exists messages (
    id integer primary key,
    channel text not null references channels(name) on delete cascade,
    parent_id integer,
    kind text not null,
    body text not null,
    to_target text not null default '', -- "<user>" or "<user>/<agent>"
    resolved integer not null default 0,
    author_user text not null,
    author_agent text not null default '',
    created_at real not null
);
create index if not exists messages_channel on messages(channel, created_at);
create index if not exists messages_parent on messages(parent_id);
"""


class BadRequest(Exception):
    pass


class Unauthorized(Exception):
    pass


class NotFound(Exception):
    pass


# --- storage ---------------------------------------------------------------

DB_PATH.parent.mkdir(parents=True, exist_ok=True)
db = sqlite3.connect(DB_PATH, check_same_thread=False, isolation_level=None)
db.row_factory = sqlite3.Row
db.execute("pragma journal_mode=wal")
db.execute("pragma foreign_keys=on")
db.executescript(SCHEMA)
lock = threading.Lock()


def q(sql, args=()):
    with lock:
        return [dict(r) for r in db.execute(sql, args).fetchall()]


def q1(sql, args=()):
    rows = q(sql, args)
    return rows[0] if rows else None


def ex(sql, args=()):
    with lock:
        return db.execute(sql, args).lastrowid


now = time.time

if not q1("select 1 from channels where name = 'general'"):
    ex("insert into channels values ('general', 'Anything that does not fit elsewhere', '', ?, ?, 0)", (now(), now()))


# --- live events -----------------------------------------------------------

subscribers: set[queue.Queue] = set()
subscribers_lock = threading.Lock()


def publish(kind, data):
    event = {"type": kind, "data": data, "at": now()}
    with subscribers_lock:
        for sub in subscribers:
            sub.put(event)


# --- model -----------------------------------------------------------------


def clean(s, limit=20000):
    return str(s or "").strip()[:limit]


def agent_row(a):
    a["online"] = now() - a["last_seen"] < ONLINE_SECONDS
    a.pop("inbox_seen", None)
    return a


def touch_agent(ident, status=None):
    """Upsert the calling agent. People posting from the web UI have no agent."""
    user, agent = ident["user"], ident["agent"]
    if not agent:
        return
    aid = f"{user}/{agent}"
    t = now()
    existing = q1("select * from agents where id = ?", (aid,))
    if existing:
        ex(
            "update agents set last_seen = ?, branch = coalesce(nullif(?, ''), branch), "
            "host = coalesce(nullif(?, ''), host), status = coalesce(?, status) where id = ?",
            (t, ident["branch"], ident["host"], status, aid),
        )
    else:
        ex(
            "insert into agents (id, user, name, status, branch, host, first_seen, last_seen) values (?, ?, ?, ?, ?, ?, ?, ?)",
            (aid, user, agent, status or "", ident["branch"], ident["host"], t, t),
        )
    row = agent_row(q1("select * from agents where id = ?", (aid,)))
    # Heartbeats are frequent; only announce changes worth showing.
    if not existing or status is not None or not agent_row(dict(existing))["online"] or existing["branch"] != row["branch"]:
        publish("agent", row)


def entry_row(e):
    e["tags"] = [t for t in e["tags"].split(",") if t]
    return e


def message_row(m):
    m["reply_count"] = q1("select count(*) n from messages where parent_id = ?", (m["id"],))["n"]
    return m


def channel_row(c):
    stats = q1(
        "select count(*) n, sum(kind = 'question' and resolved = 0 and parent_id is null) open from messages where channel = ?",
        (c["name"],),
    )
    c["message_count"] = stats["n"]
    c["open_questions"] = stats["open"] or 0
    c["expires_at"] = c["last_activity"] + c["ttl_hours"] * 3600 if c["ttl_hours"] else None
    return c


def tags_of(v):
    if isinstance(v, str):
        v = v.split(",")
    return ",".join(sorted({clean(t, 40).lower().lstrip("#") for t in v or [] if clean(t, 40)}))


def create_entry(ident, body):
    kind = body.get("kind")
    if kind not in ENTRY_KINDS:
        raise BadRequest(f"kind must be one of {', '.join(ENTRY_KINDS)}")
    title = clean(body.get("title"), 200)
    if not title:
        raise BadRequest("title is required")
    t = now()
    eid = ex(
        "insert into entries (kind, title, body, tags, source, author_user, author_agent, created_at, updated_at) "
        "values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (kind, title, clean(body.get("body")), tags_of(body.get("tags")), clean(body.get("source"), 200),
         ident["user"], ident["agent"], t, t),
    )
    e = entry_row(q1("select * from entries where id = ?", (eid,)))
    publish("entry", e)
    return e


def update_entry(ident, eid, body):
    e = q1("select * from entries where id = ?", (eid,))
    if not e:
        raise NotFound(f"no entry {eid}")
    fields = {}
    if "kind" in body:
        if body["kind"] not in ENTRY_KINDS:
            raise BadRequest(f"kind must be one of {', '.join(ENTRY_KINDS)}")
        fields["kind"] = body["kind"]
    if "title" in body:
        fields["title"] = clean(body["title"], 200) or e["title"]
    if "body" in body:
        fields["body"] = clean(body["body"])
    if "append" in body:
        stamp = f"\n\n— update from {ident['user']}" + (f"/{ident['agent']}" if ident["agent"] else "") + ":\n"
        fields["body"] = (fields.get("body", e["body"]) + stamp + clean(body["append"])).strip()
    if "tags" in body:
        fields["tags"] = tags_of(body["tags"])
    if "archived" in body:
        fields["archived"] = 1 if body["archived"] else 0
    if not fields:
        raise BadRequest("nothing to update")
    fields["updated_at"] = now()
    ex(f"update entries set {', '.join(f'{k} = ?' for k in fields)} where id = ?", (*fields.values(), eid))
    e = entry_row(q1("select * from entries where id = ?", (eid,)))
    publish("entry", e)
    return e


def list_entries(params):
    sql, args = "select * from entries where 1", []
    if params.get("archived") != "1":
        sql += " and archived = 0"
    if kind := params.get("kind"):
        sql += " and kind = ?"
        args.append(kind)
    if tag := params.get("tag"):
        sql += " and (',' || tags || ',') like ?"
        args.append(f"%,{tag.lower()},%")
    if user := params.get("user"):
        sql += " and author_user = ?"
        args.append(user)
    for word in (params.get("q") or "").split():
        sql += " and (title || ' ' || body || ' ' || tags) like ?"
        args.append(f"%{word}%")
    sql += " order by updated_at desc limit ?"
    args.append(int(params.get("limit") or 200))
    return [entry_row(e) for e in q(sql, args)]


def create_channel(ident, body):
    name = clean(body.get("name"), 40).lower().lstrip("#")
    if not NAME_RE.match(name):
        raise BadRequest("channel name: lowercase letters, digits, - and _ (max 40)")
    if q1("select 1 from channels where name = ?", (name,)):
        raise BadRequest(f"#{name} already exists")
    ttl = float(body.get("ttl_hours", DEFAULT_TTL_HOURS))
    by = ident["user"] + (f"/{ident['agent']}" if ident["agent"] else "")
    ex("insert into channels values (?, ?, ?, ?, ?, ?)", (name, clean(body.get("topic"), 200), by, now(), now(), max(ttl, 0)))
    c = channel_row(q1("select * from channels where name = ?", (name,)))
    publish("channel", c)
    return c


def post_message(ident, body):
    parent = None
    if pid := body.get("parent_id"):
        parent = q1("select * from messages where id = ?", (int(pid),))
        if not parent:
            raise NotFound(f"no message {pid}")
        # Replies thread under the top-level message.
        while parent["parent_id"]:
            parent = q1("select * from messages where id = ?", (parent["parent_id"],))
    channel = parent["channel"] if parent else clean(body.get("channel"), 40).lower().lstrip("#") or "general"
    if not q1("select 1 from channels where name = ?", (channel,)):
        if not body.get("create"):
            raise NotFound(f"no channel #{channel} (it may have expired)")
        create_channel(ident, {"name": channel, "topic": body.get("topic", "")})
    kind = body.get("kind", "message")
    if kind not in MESSAGE_KINDS or (parent and kind == "question"):
        kind = "message"
    text = clean(body.get("body"))
    if not text:
        raise BadRequest("body is required")
    t = now()
    mid = ex(
        "insert into messages (channel, parent_id, kind, body, to_target, author_user, author_agent, created_at) "
        "values (?, ?, ?, ?, ?, ?, ?, ?)",
        (channel, parent["id"] if parent else None, kind, text, clean(body.get("to"), 80).lstrip("@"),
         ident["user"], ident["agent"], t),
    )
    ex("update channels set last_activity = ? where name = ?", (t, channel))
    if parent and body.get("resolve"):
        ex("update messages set resolved = 1 where id = ?", (parent["id"],))
    m = message_row(q1("select * from messages where id = ?", (mid,)))
    publish("message", m)
    if parent:
        publish("message", message_row(q1("select * from messages where id = ?", (parent["id"],))))
    publish("channel", channel_row(q1("select * from channels where name = ?", (channel,))))
    return m


def set_resolved(mid, resolved):
    m = q1("select * from messages where id = ?", (mid,))
    if not m:
        raise NotFound(f"no message {mid}")
    ex("update messages set resolved = ? where id = ?", (1 if resolved else 0, mid))
    m = message_row(q1("select * from messages where id = ?", (mid,)))
    publish("message", m)
    publish("channel", channel_row(q1("select * from channels where name = ?", (m["channel"],))))
    return m


def list_messages(channel, params):
    if not q1("select 1 from channels where name = ?", (channel,)):
        raise NotFound(f"no channel #{channel}")
    rows = q(
        "select * from messages where channel = ? and created_at > ? order by created_at desc limit ?",
        (channel, float(params.get("since") or 0), int(params.get("limit") or 500)),
    )
    return [message_row(m) for m in reversed(rows)]


def thread(mid):
    m = q1("select * from messages where id = ?", (mid,))
    if not m:
        raise NotFound(f"no message {mid}")
    root = m if not m["parent_id"] else q1("select * from messages where id = ?", (m["parent_id"],))
    replies = q("select * from messages where parent_id = ? order by created_at", (root["id"],))
    return {"message": message_row(root), "replies": replies}


def mentions_me(user, agent, t=""):
    """SQL fragment matching messages (table alias `t`) addressed to or mentioning this agent or its person."""
    t = f"{t}." if t else ""
    sql = f"({t}to_target in (?, ?) or {t}body like ? or {t}body like ?)"
    return sql, [user, f"{user}/{agent}", f"%@{user}/{agent}%", f"%@{user}%"]


def inbox(ident, params):
    user, agent = ident["user"], ident["agent"]
    if not agent:
        raise BadRequest("inbox needs an agent identity")
    a = q1("select inbox_seen from agents where id = ?", (f"{user}/{agent}",))
    since = float(params["since"]) if params.get("since") else (a["inbox_seen"] if a else 0)
    msql, margs = mentions_me(user, agent, "m")
    # Replies to things I wrote, plus anything addressed to me, by someone else.
    rows = q(
        f"""select m.* from messages m left join messages p on p.id = m.parent_id
            where m.created_at > ? and not (m.author_user = ? and m.author_agent = ?)
              and ((p.author_user = ? and p.author_agent = ?) or {msql})
            order by m.created_at""",
        (since, user, agent, user, agent, *margs),
    )
    msql, margs = mentions_me(user, agent)
    open_questions = q(
        f"""select * from messages where kind = 'question' and resolved = 0 and parent_id is null
            and not (author_user = ? and author_agent = ?) and {msql} order by created_at""",
        (user, agent, *margs),
    )
    asked = {m["id"] for m in open_questions}
    rows = [m for m in rows if m["id"] not in asked]
    if params.get("mark", "1") == "1":
        ex("update agents set inbox_seen = ? where id = ?", (now(), f"{user}/{agent}"))
    return {"since": since, "messages": rows, "open_questions": [message_row(m) for m in open_questions]}


def wait_for_reply(mid, params):
    """Long-poll until a message gets a reply after `since` (default: now)."""
    if not q1("select 1 from messages where id = ?", (mid,)):
        raise NotFound(f"no message {mid}")
    since = float(params.get("since") or now())
    deadline = now() + min(float(params.get("timeout") or 300), 3600)
    while True:
        rows = q("select * from messages where parent_id = ? and created_at > ? order by created_at", (mid, since))
        if rows or now() >= deadline:
            return {"replies": rows, "timed_out": not rows}
        time.sleep(1)


def state():
    return {
        "agents": [agent_row(a) for a in q("select * from agents order by last_seen desc")],
        "channels": [channel_row(c) for c in q("select * from channels order by name = 'general' desc, last_activity desc")],
        "entries": list_entries({}),
        "recent": [message_row(m) for m in q("select * from messages order by created_at desc limit 80")],
        "open_questions": [
            message_row(m)
            for m in q("select * from messages where kind = 'question' and resolved = 0 and parent_id is null order by created_at desc")
        ],
        "kinds": {"entries": ENTRY_KINDS, "messages": MESSAGE_KINDS},
        "now": now(),
    }


def sweep():
    """Delete channels that have gone quiet past their TTL."""
    while True:
        t = now()
        for c in q("select name from channels where ttl_hours > 0 and last_activity + ttl_hours * 3600 < ?", (t,)):
            ex("delete from messages where channel = ?", (c["name"],))
            ex("delete from channels where name = ?", (c["name"],))
            publish("channel_expired", {"name": c["name"]})
        time.sleep(30)


# --- http ------------------------------------------------------------------


class Handler(BaseHTTPRequestHandler):
    server_version = "agent-board/1"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        if os.environ.get("BOARD_LOG"):
            super().log_message(fmt, *args)

    def ident(self):
        h = self.headers
        user = clean(h.get("X-Board-User"), 60)
        if not user:
            raise BadRequest("missing X-Board-User header")
        return {
            "user": user,
            "agent": clean(h.get("X-Board-Agent"), 60),
            "branch": clean(h.get("X-Board-Branch"), 120),
            "host": clean(h.get("X-Board-Host"), 120),
        }

    def send(self, status, payload, ctype="application/json"):
        data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n))
        except json.JSONDecodeError as e:
            raise BadRequest(f"bad JSON: {e}") from e

    def do_GET(self):
        self.route("GET")

    def do_POST(self):
        self.route("POST")

    def do_PATCH(self):
        self.route("PATCH")

    def route(self, method):
        url = urlparse(self.path)
        path = url.path.rstrip("/") or "/"
        params = {k: v[-1] for k, v in parse_qs(url.query).items()}
        try:
            if method == "GET" and path in ("/", "/index.html"):
                return self.send(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
            if method == "GET" and path == "/api/events":
                return self.events()
            if method != "GET" and TOKEN and self.headers.get("X-Board-Token") != TOKEN:
                raise Unauthorized("missing or wrong X-Board-Token")
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
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:  # keep the server up; report the bug to the caller
            self.send(500, {"error": f"{type(e).__name__}: {e}"})

    def api(self, method, path, params):
        m = re.fullmatch(r"/api/(\w+)(?:/([^/]+))?(?:/(\w+))?", path)
        if not m:
            return None
        res, key, action = m.groups()
        if method == "GET":
            if res == "state" and not key:
                return state()
            if res == "entries" and not key:
                return list_entries(params)
            if res == "entries" and key:
                e = q1("select * from entries where id = ?", (int(key),))
                if not e:
                    raise NotFound(f"no entry {key}")
                return entry_row(e)
            if res == "channels" and not key:
                return [channel_row(c) for c in q("select * from channels order by last_activity desc")]
            if res == "channels" and action == "messages":
                return list_messages(key, params)
            if res == "messages" and key and not action:
                return thread(int(key))
            if res == "messages" and action == "wait":
                return wait_for_reply(int(key), params)
            if res == "agents" and not key:
                return [agent_row(a) for a in q("select * from agents order by last_seen desc")]
            if res == "inbox":
                ident = self.ident()
                touch_agent(ident)
                return inbox(ident, params)
            if res == "health":
                return {"ok": True}
            return None
        ident = self.ident()
        body = self.body()
        if method == "POST" and res == "heartbeat":
            touch_agent(ident, clean(body["status"], 200) if "status" in body else None)
            return {"ok": True}
        touch_agent(ident)
        if method == "POST" and res == "entries" and not key:
            return create_entry(ident, body)
        if method == "PATCH" and res == "entries" and key:
            return update_entry(ident, int(key), body)
        if method == "POST" and res == "channels" and not key:
            return create_channel(ident, body)
        if method == "POST" and res == "messages" and not key:
            return post_message(ident, body)
        if method == "POST" and res == "messages" and action in ("resolve", "reopen"):
            return set_resolved(int(key), action == "resolve")
        return None

    def events(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        sub = queue.Queue()
        with subscribers_lock:
            subscribers.add(sub)
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
            with subscribers_lock:
                subscribers.discard(sub)
            self.close_connection = True


def main():
    threading.Thread(target=sweep, daemon=True).start()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.daemon_threads = True
    shown = "localhost" if HOST in ("127.0.0.1", "0.0.0.0") else HOST
    print(f"agent board on http://{shown}:{PORT}  (db: {DB_PATH})", flush=True)
    if HOST == "0.0.0.0":
        print(f"teammates: BOARD_URL=http://{os.uname().nodename}:{PORT}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
