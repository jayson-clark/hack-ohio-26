"""Storage: one sqlite connection behind a lock, plus numbered migrations.

The database's `user_version` says how many migrations have run, so a board
deployed with an older schema upgrades in place on start.
"""

import sqlite3
import threading
import time
from pathlib import Path

now = time.time

MIGRATIONS = [
    # 1: the original board.
    """
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
    """,
    # 2: full-text search over knowledge and messages, kept in sync by triggers.
    """
    create virtual table entries_fts using fts5(
        title, body, tags, content='entries', content_rowid='id', tokenize='porter unicode61'
    );
    create trigger entries_ai after insert on entries begin
        insert into entries_fts(rowid, title, body, tags) values (new.id, new.title, new.body, new.tags);
    end;
    create trigger entries_ad after delete on entries begin
        insert into entries_fts(entries_fts, rowid, title, body, tags) values ('delete', old.id, old.title, old.body, old.tags);
    end;
    create trigger entries_au after update of title, body, tags on entries begin
        insert into entries_fts(entries_fts, rowid, title, body, tags) values ('delete', old.id, old.title, old.body, old.tags);
        insert into entries_fts(rowid, title, body, tags) values (new.id, new.title, new.body, new.tags);
    end;
    insert into entries_fts(rowid, title, body, tags) select id, title, body, tags from entries;

    create virtual table messages_fts using fts5(body, content='messages', content_rowid='id', tokenize='porter unicode61');
    create trigger messages_ai after insert on messages begin
        insert into messages_fts(rowid, body) values (new.id, new.body);
    end;
    create trigger messages_ad after delete on messages begin
        insert into messages_fts(messages_fts, rowid, body) values ('delete', old.id, old.body);
    end;
    insert into messages_fts(rowid, body) select id, body from messages;
    """,
    # 3: knowledge history, "still true?" votes and links between entries.
    """
    create table entry_revisions (
        id integer primary key,
        entry_id integer not null references entries(id) on delete cascade,
        kind text not null,
        title text not null,
        body text not null,
        tags text not null,
        archived integer not null,
        editor_user text not null,
        editor_agent text not null default '',
        created_at real not null
    );
    create index entry_revisions_entry on entry_revisions(entry_id, created_at);
    insert into entry_revisions (entry_id, kind, title, body, tags, archived, editor_user, editor_agent, created_at)
        select id, kind, title, body, tags, archived, author_user, author_agent, created_at from entries;

    create table entry_votes (
        entry_id integer not null references entries(id) on delete cascade,
        voter text not null,              -- "<user>" or "<user>/<agent>"
        vote text not null,               -- 'true' or 'stale'
        note text not null default '',
        created_at real not null,
        primary key (entry_id, voter)
    );
    create table entry_links (
        src integer not null references entries(id) on delete cascade,
        dst integer not null references entries(id) on delete cascade,
        rel text not null,                -- 'related' or 'supersedes' (src supersedes dst)
        created_by text not null,
        created_at real not null,
        primary key (src, dst)
    );
    """,
    # 4: reactions, file claims, the agent activity log and per-person tokens.
    """
    create table reactions (
        target text not null,             -- 'm<id>' (message) or 'e<id>' (entry)
        emoji text not null,
        who text not null,                -- "<user>" or "<user>/<agent>"
        created_at real not null,
        primary key (target, emoji, who)
    );
    create table claims (
        id integer primary key,
        agent_id text not null,           -- "<user>/<agent>", or "<user>" from the web UI
        path text not null,               -- file, directory ("engine/sim/") or glob ("app/src/**/*.tsx")
        note text not null default '',
        branch text not null default '',
        created_at real not null,
        expires_at real not null,
        released_at real
    );
    create index claims_active on claims(released_at, expires_at);
    create table activity (
        id integer primary key,
        agent_id text not null,
        kind text not null,               -- joined, status, branch, pr, claim, release, entry, question
        detail text not null default '',
        ref text not null default '',     -- what it points at: 'e12', 'm40', a path
        created_at real not null
    );
    create index activity_agent on activity(agent_id, created_at);
    create index activity_time on activity(created_at);
    create table people (
        name text primary key,
        token_hash text not null default '',
        created_at real not null
    );
    create table kv (
        key text primary key,
        value text not null,              -- JSON
        updated_at real not null
    );
    alter table agents add column pr integer;
    alter table agents add column pr_title text not null default '';
    alter table messages add column resolved_at real;
    """,
]


class DB:
    def __init__(self, path):
        path = Path(path)
        if str(path) != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("pragma journal_mode=wal")
        self.conn.execute("pragma foreign_keys=on")
        self.lock = threading.RLock()
        self.migrate()
        if not self.q1("select 1 from channels where name = 'general'"):
            self.ex("insert into channels values ('general', 'Anything that does not fit elsewhere', '', ?, ?, 0)", (now(), now()))

    def migrate(self):
        with self.lock:
            version = self.conn.execute("pragma user_version").fetchone()[0]
            for i, sql in enumerate(MIGRATIONS[version:], start=version + 1):
                # executescript() commits as it goes, so run the statements one by one inside a transaction.
                self.conn.execute("begin")
                try:
                    for stmt in split_sql(sql):
                        self.conn.execute(stmt)
                    self.conn.execute(f"pragma user_version = {i}")
                    self.conn.execute("commit")
                except Exception:
                    self.conn.execute("rollback")
                    raise

    def q(self, sql, args=()):
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def q1(self, sql, args=()):
        rows = self.q(sql, args)
        return rows[0] if rows else None

    def ex(self, sql, args=()):
        with self.lock:
            return self.conn.execute(sql, args).lastrowid

    def tx(self):
        """`with db.tx():` runs a group of writes atomically."""
        return Tx(self)


class Tx:
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        self.db.lock.acquire()
        self.db.conn.execute("begin")
        return self.db

    def __exit__(self, exc_type, *_):
        try:
            self.db.conn.execute("rollback" if exc_type else "commit")
        finally:
            self.db.lock.release()


def split_sql(sql):
    """Split a migration into statements, keeping trigger bodies (begin ... end;) whole."""
    out, cur = [], []
    for line in sql.splitlines():
        if not line.strip() or line.strip().startswith("--"):
            continue
        cur.append(line)
        joined = "\n".join(cur).strip()
        if sqlite3.complete_statement(joined):
            out.append(joined)
            cur = []
    if "\n".join(cur).strip():
        out.append("\n".join(cur).strip())
    return out
