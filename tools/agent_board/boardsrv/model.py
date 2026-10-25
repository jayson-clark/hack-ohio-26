"""The board's data model: everything the HTTP layer calls, with no HTTP in it.

`Board` wraps a `DB` and an event `Bus`. Every write publishes an event so the
web UI updates live; see `http.py` for the routes.
"""

import fnmatch
import hashlib
import json
import re
import secrets
import time

from . import search

ENTRY_KINDS = ("finding", "workflow", "decision", "gotcha")
MESSAGE_KINDS = ("message", "question")
LINK_RELS = ("related", "supersedes")
VOTES = ("true", "stale")
DEFAULT_TTL_HOURS = 24
DEFAULT_CLAIM_MINUTES = 120
ONLINE_SECONDS = 15 * 60
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
EMOJI_MAX = 16

now = time.time


class BadRequest(Exception):
    pass


class Unauthorized(Exception):
    pass


class NotFound(Exception):
    pass


def clean(s, limit=20000):
    return str(s or "").strip()[:limit]


def who(ident):
    return ident["user"] + (f"/{ident['agent']}" if ident.get("agent") else "")


def tags_of(v):
    if isinstance(v, str):
        v = v.split(",")
    return ",".join(sorted({clean(t, 40).lower().lstrip("#") for t in v or [] if clean(t, 40)}))


def hash_token(t):
    return hashlib.sha256(t.encode()).hexdigest()


def norm_path(p):
    p = clean(p, 300).replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p.lstrip("/")


def is_glob(p):
    return any(c in p for c in "*?[")


def glob_root(p):
    """The literal directory part of a glob: 'app/src/**/*.tsx' -> 'app/src/'."""
    i = min((p.index(c) for c in "*?[" if c in p), default=len(p))
    return p[:i].rsplit("/", 1)[0] + "/" if "/" in p[:i] else ""


def paths_overlap(a, b):
    """Whether two claimed paths (files, directories or globs) could touch the same file."""
    a, b = norm_path(a), norm_path(b)
    if not a or not b:
        return False
    if a == b or a.rstrip("/") == b.rstrip("/"):
        return True
    if is_glob(a) and is_glob(b):
        ra, rb = glob_root(a), glob_root(b)
        return ra.startswith(rb) or rb.startswith(ra)
    for x, y in ((a, b), (b, a)):
        if is_glob(x):
            if fnmatch.fnmatch(y, x) or y.rstrip("/") + "/" == glob_root(x) or glob_root(x).startswith(y.rstrip("/") + "/"):
                return True
        elif y.startswith(x.rstrip("/") + "/"):
            return True  # x is a directory containing y
    return False


class Board:
    def __init__(self, db, bus, token="", repo=""):
        self.db = db
        self.bus = bus
        self.token = token
        self.repo = repo  # "owner/name", for links in the UI
        self.q, self.q1, self.ex = db.q, db.q1, db.ex

    def publish(self, kind, data):
        self.bus.publish(kind, data)

    # --- auth ----------------------------------------------------------------

    def authorize(self, ident, given):
        """Writes need the shared BOARD_TOKEN or the person's own token (if they have one)."""
        if self.token and given and secrets.compare_digest(given, self.token):
            return
        person = self.q1("select token_hash from people where name = ?", (ident["user"],))
        if person and person["token_hash"]:
            if given and secrets.compare_digest(hash_token(given), person["token_hash"]):
                return
            raise Unauthorized(f"{ident['user']} has a personal token; send it as X-Board-Token")
        if self.token:
            raise Unauthorized("missing or wrong X-Board-Token")

    def issue_token(self, name):
        name = clean(name, 60)
        if not name:
            raise BadRequest("name is required")
        token = "bt_" + secrets.token_urlsafe(24)
        self.ex(
            "insert into people (name, token_hash, created_at) values (?, ?, ?) "
            "on conflict(name) do update set token_hash = excluded.token_hash",
            (name, hash_token(token), now()),
        )
        return {"name": name, "token": token}

    # --- agents and activity ---------------------------------------------------

    def agent_row(self, a):
        a["online"] = now() - a["last_seen"] < ONLINE_SECONDS
        a.pop("inbox_seen", None)
        return a

    def log(self, agent_id, kind, detail="", ref=""):
        t = now()
        aid = self.ex(
            "insert into activity (agent_id, kind, detail, ref, created_at) values (?, ?, ?, ?, ?)",
            (agent_id, kind, clean(detail, 300), ref, t),
        )
        row = {"id": aid, "agent_id": agent_id, "kind": kind, "detail": clean(detail, 300), "ref": ref, "created_at": t}
        self.publish("activity", row)
        return row

    def touch_agent(self, ident, status=None):
        """Upsert the calling agent. People posting from the web UI have no agent."""
        user, agent = ident["user"], ident["agent"]
        if not agent:
            return
        aid = f"{user}/{agent}"
        t = now()
        pr = ident.get("pr")
        existing = self.q1("select * from agents where id = ?", (aid,))
        if existing:
            self.ex(
                "update agents set last_seen = ?, branch = coalesce(nullif(?, ''), branch), "
                "host = coalesce(nullif(?, ''), host), status = coalesce(?, status), "
                "pr = coalesce(?, pr), pr_title = case when ? is null then pr_title else ? end where id = ?",
                (t, ident["branch"], ident["host"], status, pr, pr, ident.get("pr_title", ""), aid),
            )
        else:
            self.ex(
                "insert into agents (id, user, name, status, branch, host, first_seen, last_seen, pr, pr_title) "
                "values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (aid, user, agent, status or "", ident["branch"], ident["host"], t, t, pr, ident.get("pr_title", "")),
            )
        row = self.agent_row(self.q1("select * from agents where id = ?", (aid,)))
        before = existing or {"status": "", "branch": row["branch"], "pr": None}
        if not existing:
            self.log(aid, "joined", row["branch"])
        if status and status != before["status"]:
            self.log(aid, "status", status)
        if row["branch"] != before["branch"]:
            self.log(aid, "branch", row["branch"])
        if row["pr"] and row["pr"] != before["pr"]:
            self.log(aid, "pr", f"#{row['pr']} {row['pr_title']}".strip(), f"pr{row['pr']}")
        # Heartbeats are frequent; only announce changes worth showing.
        was_online = now() - existing["last_seen"] < ONLINE_SECONDS if existing else False
        if not existing or status is not None or not was_online or existing["branch"] != row["branch"] or existing["pr"] != row["pr"]:
            self.publish("agent", row)

    def agents(self):
        return [self.agent_row(a) for a in self.q("select * from agents order by last_seen desc")]

    def activity(self, params):
        sql, args = "select * from activity where 1", []
        if agent := params.get("agent"):
            if "/" in agent:
                sql += " and agent_id = ?"
                args.append(agent)
            else:
                sql += " and (agent_id = ? or agent_id like ?)"
                args += [agent, f"{agent}/%"]
        if since := params.get("since"):
            sql += " and created_at > ?"
            args.append(float(since))
        sql += " order by created_at desc limit ?"
        args.append(min(int(params.get("limit") or 100), 1000))
        return self.q(sql, args)

    # --- reactions -------------------------------------------------------------

    def reactions_for(self, targets):
        """{target: {emoji: [who, ...]}} for a list of 'm<id>'/'e<id>' targets."""
        out = {t: {} for t in targets}
        if not targets:
            return out
        for chunk in range(0, len(targets), 500):
            part = targets[chunk:chunk + 500]
            rows = self.q(
                f"select * from reactions where target in ({','.join('?' * len(part))}) order by created_at",
                part,
            )
            for r in rows:
                out[r["target"]].setdefault(r["emoji"], []).append(r["who"])
        return out

    def react(self, ident, body):
        target = clean(body.get("target"), 20)
        emoji = clean(body.get("emoji"), EMOJI_MAX)
        if not re.fullmatch(r"[me]\d+", target):
            raise BadRequest("target must be m<message id> or e<entry id>")
        if not emoji:
            raise BadRequest("emoji is required")
        table = "messages" if target[0] == "m" else "entries"
        if not self.q1(f"select 1 from {table} where id = ?", (int(target[1:]),)):
            raise NotFound(f"no {table[:-1]} {target[1:]}")
        me = who(ident)
        on = body.get("on")
        has = self.q1("select 1 from reactions where target = ? and emoji = ? and who = ?", (target, emoji, me))
        if on is None:
            on = not has
        if on and not has:
            self.ex("insert into reactions values (?, ?, ?, ?)", (target, emoji, me, now()))
        elif not on and has:
            self.ex("delete from reactions where target = ? and emoji = ? and who = ?", (target, emoji, me))
        data = {"target": target, "reactions": self.reactions_for([target])[target]}
        self.publish("reaction", data)
        return data

    # --- knowledge ---------------------------------------------------------------

    def decorate_entries(self, rows):
        if not rows:
            return rows
        ids = [e["id"] for e in rows]
        marks = ",".join("?" * len(ids))
        votes = {}
        for v in self.q(f"select entry_id, vote, count(*) n, max(created_at) last from entry_votes where entry_id in ({marks}) group by entry_id, vote", ids):
            votes.setdefault(v["entry_id"], {})[v["vote"]] = (v["n"], v["last"])
        links = {}
        for l in self.q(
            f"""select l.src, l.dst, l.rel, s.title s_title, s.kind s_kind, s.archived s_arch, d.title d_title, d.kind d_kind, d.archived d_arch
                from entry_links l join entries s on s.id = l.src join entries d on d.id = l.dst
                where l.src in ({marks}) or l.dst in ({marks})""",
            ids + ids,
        ):
            links.setdefault(l["src"], []).append({"id": l["dst"], "title": l["d_title"], "kind": l["d_kind"], "archived": bool(l["d_arch"]), "rel": l["rel"], "dir": "out"})
            links.setdefault(l["dst"], []).append({"id": l["src"], "title": l["s_title"], "kind": l["s_kind"], "archived": bool(l["s_arch"]), "rel": l["rel"], "dir": "in"})
        revs = {r["entry_id"]: r["n"] for r in self.q(f"select entry_id, count(*) n from entry_revisions where entry_id in ({marks}) group by entry_id", ids)}
        reactions = self.reactions_for([f"e{i}" for i in ids])
        for e in rows:
            if isinstance(e["tags"], str):
                e["tags"] = [t for t in e["tags"].split(",") if t]
            v = votes.get(e["id"], {})
            e["votes"] = {"true": v.get("true", (0, None))[0], "stale": v.get("stale", (0, None))[0],
                          "confirmed_at": v.get("true", (0, None))[1]}
            e["links"] = links.get(e["id"], [])
            e["superseded_by"] = next((l["id"] for l in e["links"] if l["rel"] == "supersedes" and l["dir"] == "in"), None)
            e["revisions"] = revs.get(e["id"], 1)
            e["reactions"] = reactions[f"e{e['id']}"]
            e.pop("rank", None)
        return rows

    def entry(self, eid):
        e = self.q1("select * from entries where id = ?", (eid,))
        if not e:
            raise NotFound(f"no entry {eid}")
        return self.decorate_entries([e])[0]

    def snapshot_entry(self, eid, ident):
        e = self.q1("select * from entries where id = ?", (eid,))
        self.ex(
            "insert into entry_revisions (entry_id, kind, title, body, tags, archived, editor_user, editor_agent, created_at) "
            "values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (eid, e["kind"], e["title"], e["body"], e["tags"], e["archived"], ident["user"], ident["agent"], now()),
        )

    def create_entry(self, ident, body):
        kind = body.get("kind")
        if kind not in ENTRY_KINDS:
            raise BadRequest(f"kind must be one of {', '.join(ENTRY_KINDS)}")
        title = clean(body.get("title"), 200)
        if not title:
            raise BadRequest("title is required")
        t = now()
        with self.db.tx():
            eid = self.ex(
                "insert into entries (kind, title, body, tags, source, author_user, author_agent, created_at, updated_at) "
                "values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (kind, title, clean(body.get("body")), tags_of(body.get("tags")), clean(body.get("source"), 200),
                 ident["user"], ident["agent"], t, t),
            )
            self.snapshot_entry(eid, ident)
        for target in body.get("supersedes") or []:
            self.link(ident, eid, {"to": target, "rel": "supersedes"}, publish=False)
        e = self.entry(eid)
        self.publish("entry", e)
        if ident["agent"]:
            self.log(who(ident), "entry", f"{kind}: {title}", f"e{eid}")
        return e

    def update_entry(self, ident, eid, body):
        e = self.q1("select * from entries where id = ?", (eid,))
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
            stamp = f"\n\n— update from {who(ident)}:\n"
            fields["body"] = (fields.get("body", e["body"]) + stamp + clean(body["append"])).strip()
        if "tags" in body:
            fields["tags"] = tags_of(body["tags"])
        if "source" in body:
            fields["source"] = clean(body["source"], 200)
        if "archived" in body:
            fields["archived"] = 1 if body["archived"] else 0
        if not fields:
            raise BadRequest("nothing to update")
        fields["updated_at"] = now()
        with self.db.tx():
            self.ex(f"update entries set {', '.join(f'{k} = ?' for k in fields)} where id = ?", (*fields.values(), eid))
            self.snapshot_entry(eid, ident)
        e = self.entry(eid)
        self.publish("entry", e)
        return e

    def history(self, eid):
        if not self.q1("select 1 from entries where id = ?", (eid,)):
            raise NotFound(f"no entry {eid}")
        rows = self.q("select * from entry_revisions where entry_id = ? order by created_at, id", (eid,))
        for r in rows:
            r["tags"] = [t for t in r["tags"].split(",") if t]
        return rows

    def vote(self, ident, eid, body):
        if not self.q1("select 1 from entries where id = ?", (eid,)):
            raise NotFound(f"no entry {eid}")
        v = body.get("vote") or ""
        if v and v not in VOTES:
            raise BadRequest("vote must be 'true', 'stale' or '' (clear)")
        me = who(ident)
        if v:
            self.ex(
                "insert into entry_votes values (?, ?, ?, ?, ?) on conflict(entry_id, voter) do update set "
                "vote = excluded.vote, note = excluded.note, created_at = excluded.created_at",
                (eid, me, v, clean(body.get("note"), 500), now()),
            )
        else:
            self.ex("delete from entry_votes where entry_id = ? and voter = ?", (eid, me))
        e = self.entry(eid)
        self.publish("entry", e)
        return e

    def votes(self, eid):
        return self.q("select voter, vote, note, created_at from entry_votes where entry_id = ? order by created_at desc", (eid,))

    def link(self, ident, eid, body, publish=True):
        try:
            to = int(str(body.get("to", "")).lstrip("#"))
        except ValueError:
            raise BadRequest("to must be an entry id") from None
        rel = body.get("rel") or "related"
        if rel not in LINK_RELS:
            raise BadRequest(f"rel must be one of {', '.join(LINK_RELS)}")
        if to == eid:
            raise BadRequest("an entry can't link to itself")
        for x in (eid, to):
            if not self.q1("select 1 from entries where id = ?", (x,)):
                raise NotFound(f"no entry {x}")
        self.ex("delete from entry_links where (src = ? and dst = ?) or (src = ? and dst = ?)", (eid, to, to, eid))
        self.ex("insert into entry_links values (?, ?, ?, ?, ?)", (eid, to, rel, who(ident), now()))
        if publish:
            for x in (eid, to):
                self.publish("entry", self.entry(x))
        return self.entry(eid)

    def unlink(self, eid, to):
        self.ex("delete from entry_links where (src = ? and dst = ?) or (src = ? and dst = ?)", (eid, to, to, eid))
        for x in (eid, to):
            if self.q1("select 1 from entries where id = ?", (x,)):
                self.publish("entry", self.entry(x))
        return self.entry(eid)

    def list_entries(self, params):
        if (params.get("q") or "").strip():
            rows = search.search_entries(
                self.db, params["q"], kind=params.get("kind"), tag=params.get("tag"), user=params.get("user"),
                archived=params.get("archived") == "1", limit=int(params.get("limit") or 200),
                any_word=params.get("any") == "1",
            )
            return self.decorate_entries(rows)
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
        sql += " order by updated_at desc limit ?"
        args.append(int(params.get("limit") or 200))
        return self.decorate_entries(self.q(sql, args))

    def tags(self):
        counts = {}
        for e in self.q("select tags from entries where archived = 0 and tags != ''"):
            for t in e["tags"].split(","):
                counts[t] = counts.get(t, 0) + 1
        return [{"tag": t, "count": n} for t, n in sorted(counts.items(), key=lambda x: (-x[1], x[0]))]

    def suggest(self, params):
        """Knowledge likely relevant to what an agent is doing (any word of its branch or status)."""
        text = re.sub(r"[/_-]+", " ", params.get("q") or "")
        stop = {"app", "the", "and", "for", "with", "fix", "add", "on", "of", "to", "a", "in", "main", "pr", "issue"}
        words = [w for w in re.findall(r"[a-zA-Z]{3,}", text) if w.lower() not in stop]
        if not words:
            return []
        return self.decorate_entries(search.search_entries(self.db, " ".join(words), any_word=True, limit=int(params.get("limit") or 5)))

    # --- channels and messages ----------------------------------------------------

    def channel_row(self, c):
        stats = self.q1(
            "select count(*) n, sum(kind = 'question' and resolved = 0 and parent_id is null) open from messages where channel = ?",
            (c["name"],),
        )
        c["message_count"] = stats["n"]
        c["open_questions"] = stats["open"] or 0
        c["expires_at"] = c["last_activity"] + c["ttl_hours"] * 3600 if c["ttl_hours"] else None
        return c

    def channel(self, name):
        c = self.q1("select * from channels where name = ?", (name,))
        return self.channel_row(c) if c else None

    def channels(self):
        return [self.channel_row(c) for c in self.q("select * from channels order by name = 'general' desc, last_activity desc")]

    def decorate_messages(self, rows):
        if not rows:
            return rows
        ids = [m["id"] for m in rows]
        counts = {}
        for chunk in range(0, len(ids), 500):
            part = ids[chunk:chunk + 500]
            for r in self.q(
                f"select parent_id, count(*) n, max(created_at) last from messages where parent_id in ({','.join('?' * len(part))}) group by parent_id",
                part,
            ):
                counts[r["parent_id"]] = (r["n"], r["last"])
        reactions = self.reactions_for([f"m{i}" for i in ids])
        for m in rows:
            m["reply_count"], m["last_reply_at"] = counts.get(m["id"], (0, None))
            m["reactions"] = reactions[f"m{m['id']}"]
            m.pop("rank", None)
        return rows

    def message(self, mid):
        m = self.q1("select * from messages where id = ?", (mid,))
        if not m:
            raise NotFound(f"no message {mid}")
        return self.decorate_messages([m])[0]

    def create_channel(self, ident, body):
        name = clean(body.get("name"), 40).lower().lstrip("#")
        if not NAME_RE.match(name):
            raise BadRequest("channel name: lowercase letters, digits, - and _ (max 40)")
        if self.q1("select 1 from channels where name = ?", (name,)):
            raise BadRequest(f"#{name} already exists")
        ttl = float(body.get("ttl_hours", DEFAULT_TTL_HOURS))
        self.ex("insert into channels values (?, ?, ?, ?, ?, ?)", (name, clean(body.get("topic"), 200), who(ident), now(), now(), max(ttl, 0)))
        c = self.channel(name)
        self.publish("channel", c)
        return c

    def update_channel(self, name, body):
        c = self.q1("select * from channels where name = ?", (name,))
        if not c:
            raise NotFound(f"no channel #{name}")
        if "topic" in body:
            self.ex("update channels set topic = ? where name = ?", (clean(body["topic"], 200), name))
        if "ttl_hours" in body and name != "general":
            self.ex("update channels set ttl_hours = ?, last_activity = ? where name = ?", (max(float(body["ttl_hours"]), 0), now(), name))
        c = self.channel(name)
        self.publish("channel", c)
        return c

    def post_message(self, ident, body):
        parent = None
        if pid := body.get("parent_id"):
            parent = self.q1("select * from messages where id = ?", (int(pid),))
            if not parent:
                raise NotFound(f"no message {pid}")
            # Replies thread under the top-level message.
            while parent["parent_id"]:
                parent = self.q1("select * from messages where id = ?", (parent["parent_id"],))
        channel = parent["channel"] if parent else clean(body.get("channel"), 40).lower().lstrip("#") or "general"
        if not self.q1("select 1 from channels where name = ?", (channel,)):
            if not body.get("create"):
                raise NotFound(f"no channel #{channel} (it may have expired)")
            self.create_channel(ident, {"name": channel, "topic": body.get("topic", "")})
        kind = body.get("kind", "message")
        if kind not in MESSAGE_KINDS or (parent and kind == "question"):
            kind = "message"
        text = clean(body.get("body"))
        if not text:
            raise BadRequest("body is required")
        t = now()
        mid = self.ex(
            "insert into messages (channel, parent_id, kind, body, to_target, author_user, author_agent, created_at) "
            "values (?, ?, ?, ?, ?, ?, ?, ?)",
            (channel, parent["id"] if parent else None, kind, text, clean(body.get("to"), 80).lstrip("@"),
             ident["user"], ident["agent"], t),
        )
        self.ex("update channels set last_activity = ? where name = ?", (t, channel))
        if parent and body.get("resolve"):
            self.ex("update messages set resolved = 1, resolved_at = ? where id = ?", (t, parent["id"]))
        m = self.message(mid)
        self.publish("message", m)
        if parent:
            self.publish("message", self.message(parent["id"]))
        self.publish("channel", self.channel(channel))
        if kind == "question" and ident["agent"]:
            self.log(who(ident), "question", text.splitlines()[0][:200], f"m{mid}")
        return m

    def set_resolved(self, mid, resolved):
        m = self.q1("select * from messages where id = ?", (mid,))
        if not m:
            raise NotFound(f"no message {mid}")
        self.ex("update messages set resolved = ?, resolved_at = ? where id = ?", (1 if resolved else 0, now() if resolved else None, mid))
        m = self.message(mid)
        self.publish("message", m)
        self.publish("channel", self.channel(m["channel"]))
        return m

    def list_messages(self, channel, params):
        if not self.q1("select 1 from channels where name = ?", (channel,)):
            raise NotFound(f"no channel #{channel}")
        sql, args = "select * from messages where channel = ? and created_at > ?", [channel, float(params.get("since") or 0)]
        if before := params.get("before"):
            sql += " and created_at < ?"
            args.append(float(before))
        sql += " order by created_at desc limit ?"
        args.append(int(params.get("limit") or 500))
        return self.decorate_messages(list(reversed(self.q(sql, args))))

    def thread(self, mid):
        m = self.q1("select * from messages where id = ?", (mid,))
        if not m:
            raise NotFound(f"no message {mid}")
        root = m if not m["parent_id"] else self.q1("select * from messages where id = ?", (m["parent_id"],))
        replies = self.q("select * from messages where parent_id = ? order by created_at", (root["id"],))
        return {"message": self.decorate_messages([root])[0], "replies": self.decorate_messages(replies)}

    def search_messages(self, params):
        rows = search.search_messages(self.db, params.get("q") or "", channel=params.get("channel"), limit=int(params.get("limit") or 30))
        return self.decorate_messages(rows)

    def open_questions(self):
        return self.decorate_messages(self.q(
            "select * from messages where kind = 'question' and resolved = 0 and parent_id is null order by created_at desc"
        ))

    @staticmethod
    def mentions_me(user, agent, t=""):
        """SQL fragment matching messages (table alias `t`) addressed to or mentioning this agent or its person."""
        t = f"{t}." if t else ""
        sql = f"({t}to_target in (?, ?) or {t}body like ? or {t}body like ?)"
        return sql, [user, f"{user}/{agent}", f"%@{user}/{agent}%", f"%@{user}%"]

    def inbox(self, ident, params):
        user, agent = ident["user"], ident["agent"]
        if not agent:
            raise BadRequest("inbox needs an agent identity")
        a = self.q1("select inbox_seen from agents where id = ?", (f"{user}/{agent}",))
        since = float(params["since"]) if params.get("since") else (a["inbox_seen"] if a else 0)
        msql, margs = self.mentions_me(user, agent, "m")
        # Replies to things I wrote, plus anything addressed to me, by someone else.
        rows = self.q(
            f"""select m.* from messages m left join messages p on p.id = m.parent_id
                where m.created_at > ? and not (m.author_user = ? and m.author_agent = ?)
                  and ((p.author_user = ? and p.author_agent = ?) or {msql})
                order by m.created_at""",
            (since, user, agent, user, agent, *margs),
        )
        msql, margs = self.mentions_me(user, agent)
        open_questions = self.q(
            f"""select * from messages where kind = 'question' and resolved = 0 and parent_id is null
                and not (author_user = ? and author_agent = ?) and {msql} order by created_at""",
            (user, agent, *margs),
        )
        asked = {m["id"] for m in open_questions}
        rows = [m for m in rows if m["id"] not in asked]
        conflicts = self.conflicts_for(f"{user}/{agent}")
        if params.get("mark", "1") == "1":
            self.ex("update agents set inbox_seen = ? where id = ?", (now(), f"{user}/{agent}"))
        return {"since": since, "messages": self.decorate_messages(rows),
                "open_questions": self.decorate_messages(open_questions), "claim_conflicts": conflicts}

    def wait_for_reply(self, mid, params):
        """Long-poll until a message gets a reply after `since` (default: now)."""
        if not self.q1("select 1 from messages where id = ?", (mid,)):
            raise NotFound(f"no message {mid}")
        since = float(params.get("since") or now())
        deadline = now() + min(float(params.get("timeout") or 300), 3600)
        while True:
            rows = self.q("select * from messages where parent_id = ? and created_at > ? order by created_at", (mid, since))
            if rows or now() >= deadline:
                return {"replies": self.decorate_messages(rows), "timed_out": not rows}
            time.sleep(1)

    # --- file claims ---------------------------------------------------------------

    def active_claims(self, agent_id=None):
        sql, args = "select * from claims where released_at is null and expires_at > ?", [now()]
        if agent_id:
            sql += " and agent_id = ?"
            args.append(agent_id)
        return self.q(sql + " order by created_at", args)

    def overlapping(self, paths, exclude):
        out = []
        for c in self.active_claims():
            if c["agent_id"] == exclude:
                continue
            for p in paths:
                if paths_overlap(p, c["path"]):
                    out.append({**c, "wanted": p})
                    break
        return out

    def conflicts_for(self, agent_id):
        mine = [c["path"] for c in self.active_claims(agent_id)]
        return self.overlapping(mine, agent_id) if mine else []

    def claim(self, ident, body):
        paths = body.get("paths") or ([body["path"]] if body.get("path") else [])
        paths = [p for p in (norm_path(p) for p in paths) if p]
        if not paths:
            raise BadRequest("paths is required")
        if len(paths) > 100:
            raise BadRequest("at most 100 paths per claim")
        me = who(ident)
        minutes = float(body.get("ttl_minutes") or DEFAULT_CLAIM_MINUTES)
        t = now()
        expires = t + max(1.0, min(minutes, 24 * 60)) * 60
        note = clean(body.get("note"), 200)
        conflicts = self.overlapping(paths, me)
        if conflicts and body.get("strict"):
            return {"claims": [], "conflicts": conflicts, "ok": False}
        fresh = []
        for p in paths:
            existing = self.q1("select id from claims where agent_id = ? and path = ? and released_at is null and expires_at > ?", (me, p, t))
            if existing:
                self.ex("update claims set expires_at = ?, note = coalesce(nullif(?, ''), note), branch = ? where id = ?",
                        (expires, note, ident.get("branch", ""), existing["id"]))
            else:
                self.ex("insert into claims (agent_id, path, note, branch, created_at, expires_at) values (?, ?, ?, ?, ?, ?)",
                        (me, p, note, ident.get("branch", ""), t, expires))
                fresh.append(p)
        if fresh:
            self.log(me, "claim", ", ".join(fresh) + (f" — {note}" if note else ""), fresh[0])
        claims = self.active_claims(me)
        self.publish("claims", {"agent_id": me, "claims": claims})
        for c in conflicts:
            self.publish("claim_conflict", {"agent_id": me, "path": c["wanted"], "held_by": c["agent_id"], "held_path": c["path"]})
        return {"claims": claims, "conflicts": conflicts, "ok": not conflicts}

    def release(self, ident, body):
        me = who(ident)
        paths = [norm_path(p) for p in body.get("paths") or []]
        t = now()
        if paths:
            for p in paths:
                self.ex("update claims set released_at = ? where agent_id = ? and path = ? and released_at is null", (t, me, p))
        else:
            self.ex("update claims set released_at = ? where agent_id = ? and released_at is null", (t, me))
        self.log(me, "release", ", ".join(paths) if paths else "everything")
        claims = self.active_claims(me)
        self.publish("claims", {"agent_id": me, "claims": claims})
        return {"claims": claims}

    def check_paths(self, ident, params):
        paths = [norm_path(p) for p in (params.get("paths") or "").split(",") if p.strip()]
        return {"conflicts": self.overlapping(paths, who(ident) if ident else "")}

    # --- key/value (GitHub snapshot and friends) -------------------------------------

    def kv_get(self, key, default=None):
        r = self.q1("select value, updated_at from kv where key = ?", (key,))
        return (json.loads(r["value"]), r["updated_at"]) if r else (default, 0)

    def kv_set(self, key, value):
        self.ex("insert into kv values (?, ?, ?) on conflict(key) do update set value = excluded.value, updated_at = excluded.updated_at",
                (key, json.dumps(value), now()))

    # --- digests and snapshots --------------------------------------------------------

    def digest(self, params):
        """What changed since `since`: for 'while you were away' and `board.py digest`."""
        since = float(params.get("since") or now() - 8 * 3600)
        entries_new = self.decorate_entries(self.q("select * from entries where created_at > ? and archived = 0 order by created_at desc", (since,)))
        entries_updated = self.decorate_entries(self.q(
            "select * from entries where updated_at > ? and created_at <= ? and archived = 0 order by updated_at desc", (since, since)
        ))
        by_channel = self.q(
            """select channel, count(*) n, sum(kind = 'question' and parent_id is null) questions, max(created_at) last
               from messages where created_at > ? group by channel order by last desc""",
            (since,),
        )
        asked = self.decorate_messages(self.q(
            "select * from messages where kind = 'question' and parent_id is null and created_at > ? order by created_at desc", (since,)
        ))
        resolved = self.decorate_messages(self.q(
            "select * from messages where kind = 'question' and resolved = 1 and resolved_at > ? order by resolved_at desc", (since,)
        ))
        activity = self.q("select * from activity where created_at > ? and kind in ('joined', 'status', 'pr', 'claim') order by created_at desc limit 100", (since,))
        gh, _ = self.kv_get("github", {})
        merged = [p for p in (gh or {}).get("merged", []) if (p.get("merged_ts") or 0) > since]
        return {"since": since, "now": now(), "entries_new": entries_new, "entries_updated": entries_updated,
                "channels": by_channel, "questions_asked": asked, "questions_resolved": resolved,
                "activity": activity, "merged": merged}

    def state(self):
        gh, gh_at = self.kv_get("github", None)
        return {
            "agents": self.agents(),
            "channels": self.channels(),
            "entries": self.list_entries({}),
            "recent": self.decorate_messages(self.q("select * from messages order by created_at desc limit 80")),
            "open_questions": self.open_questions(),
            "claims": self.active_claims(),
            "activity": self.q("select * from activity order by created_at desc limit 150"),
            "tags": self.tags(),
            "github": {**gh, "updated_at": gh_at} if gh else None,
            "kinds": {"entries": ENTRY_KINDS, "messages": MESSAGE_KINDS},
            "repo": self.repo,
            "now": now(),
        }

    def export(self):
        tables = ("agents", "entries", "entry_revisions", "entry_votes", "entry_links", "channels", "messages",
                  "reactions", "claims", "activity")
        return {"exported_at": now(), "schema_version": self.q1("pragma user_version")["user_version"],
                **{t: self.q(f"select * from {t}") for t in tables}}

    def sweep(self):
        """Delete channels that have gone quiet past their TTL. Returns the names removed."""
        t = now()
        gone = []
        for c in self.q("select name from channels where ttl_hours > 0 and last_activity + ttl_hours * 3600 < ?", (t,)):
            ids = [m["id"] for m in self.q("select id from messages where channel = ?", (c["name"],))]
            for chunk in range(0, len(ids), 500):
                part = ids[chunk:chunk + 500]
                self.ex(f"delete from reactions where target in ({','.join('?' * len(part))})", [f"m{i}" for i in part])
            self.ex("delete from messages where channel = ?", (c["name"],))
            self.ex("delete from channels where name = ?", (c["name"],))
            self.publish("channel_expired", {"name": c["name"]})
            gone.append(c["name"])
        for c in self.q("select distinct agent_id from claims where released_at is null and expires_at <= ? and expires_at > ?", (t, t - 60)):
            self.publish("claims", {"agent_id": c["agent_id"], "claims": self.active_claims(c["agent_id"])})
        return gone
