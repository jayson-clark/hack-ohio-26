import json
import sqlite3
import threading
import time
import urllib.request

from boardsrv import github
from boardsrv.db import DB, MIGRATIONS, split_sql
from boardsrv.events import Bus
from boardsrv.model import Board, paths_overlap

from conftest import Client, start


def add(api, title, body="", kind="finding", tags=""):
    return api.post("/api/entries", {"kind": kind, "title": title, "body": body, "tags": tags})


def test_search_is_ranked_prefix_and_stemmed(api):
    add(api, "Projector calibration drifts", "re-run it after moving the table", tags="vision")
    add(api, "Routes avoid burning roads", "the router replans on every forecast", tags="routing")
    hits = api.get("/api/entries?q=calib")
    assert [e["title"] for e in hits] == ["Projector calibration drifts"]
    assert "\x02" in hits[0]["title_hl"]
    # porter stemming: "routing" finds "Routes"/"router"
    assert api.get("/api/entries?q=routing")[0]["title"] == "Routes avoid burning roads"
    # every word must match unless any=1
    assert api.get("/api/entries?q=calibration+router") == []
    assert len(api.get("/api/entries?q=calibration+router&any=1")) == 2
    # punctuation that would be FTS syntax is harmless
    assert api.get('/api/entries?q=%22%28%2A') == []


def test_search_covers_messages(api):
    api.post("/api/messages", {"channel": "sim", "body": "wind shifts at 14:00", "create": True})
    r = api.get("/api/search?q=wind")
    assert r["messages"][0]["channel"] == "sim"
    assert "\x02wind\x03" in r["messages"][0]["snippet"]


def test_edits_keep_history(api):
    e = add(api, "Old title", "first body")
    api.as_("ben", "calm-owl").patch(f"/api/entries/{e['id']}", {"append": "still holds after #42"})
    api.patch(f"/api/entries/{e['id']}", {"title": "New title"})
    hist = api.get(f"/api/entries/{e['id']}/history")
    assert [h["title"] for h in hist] == ["Old title", "Old title", "New title"]
    assert hist[1]["editor_user"] == "ben"
    assert api.get(f"/api/entries/{e['id']}")["revisions"] == 3
    # FTS follows edits
    assert api.get("/api/entries?q=new+title")[0]["id"] == e["id"]
    assert api.get("/api/entries?q=old") == []


def test_minor_edits_keep_updated_at(api):
    e = add(api, "Title", "one two")
    edited = api.patch(f"/api/entries/{e['id']}", {"body": "one\n\ntwo", "minor": True})
    assert edited["updated_at"] == e["updated_at"] and edited["body"] == "one\n\ntwo"
    assert edited["revisions"] == 2


def test_votes_and_supersedes(api):
    old = add(api, "Use camera index 0")
    new = add(api, "Use camera index 1 on the demo Mac")
    api.as_("ben", "calm-owl").post(f"/api/entries/{old['id']}/vote", {"vote": "stale"})
    e = api.post(f"/api/entries/{old['id']}/vote", {"vote": "true"})
    assert e["votes"]["true"] == 1 and e["votes"]["stale"] == 1
    e = api.post(f"/api/entries/{old['id']}/vote", {"vote": ""})
    assert e["votes"]["true"] == 0
    api.post(f"/api/entries/{new['id']}/links", {"to": old["id"], "rel": "supersedes"})
    assert api.get(f"/api/entries/{old['id']}")["superseded_by"] == new["id"]
    assert api.get(f"/api/entries/{new['id']}")["links"][0] == {
        "id": old["id"], "title": old["title"], "kind": "finding", "archived": False, "rel": "supersedes", "dir": "out"}
    status, _ = api.call("DELETE", f"/api/entries/{new['id']}/links/{old['id']}")
    assert status == 200
    assert api.get(f"/api/entries/{old['id']}")["superseded_by"] is None


def test_tags(api):
    add(api, "a", tags="vision,aruco")
    add(api, "b", tags="vision")
    assert api.get("/api/tags") == [{"tag": "vision", "count": 2}, {"tag": "aruco", "count": 1}]


def test_reactions_toggle(api):
    m = api.post("/api/messages", {"channel": "general", "body": "merged #12"})
    api.post("/api/reactions", {"target": f"m{m['id']}", "emoji": "✅"})
    api.as_("ben").post("/api/reactions", {"target": f"m{m['id']}", "emoji": "✅"})
    msgs = api.get("/api/channels/general/messages")
    assert msgs[-1]["reactions"] == {"✅": ["ana/swift-fox", "ben"]}
    r = api.post("/api/reactions", {"target": f"m{m['id']}", "emoji": "✅"})
    assert r["reactions"] == {"✅": ["ben"]}
    status, _ = api.call("POST", "/api/reactions", {"target": "m999", "emoji": "✅"})
    assert status == 404


def test_paths_overlap():
    assert paths_overlap("engine/protocol.py", "./engine/protocol.py")
    assert paths_overlap("engine/sim/", "engine/sim/fire.py")
    assert paths_overlap("engine/sim", "engine/sim/fire.py")
    assert not paths_overlap("engine/sim/", "engine/simulate.py")
    assert paths_overlap("app/src/**/*.tsx", "app/src/console/Map.tsx")
    assert paths_overlap("app/src/*", "app/")
    assert paths_overlap("app/src/**/*.tsx", "app/src/console/*.ts")
    assert not paths_overlap("app/src/**/*.tsx", "engine/*.py")
    assert not paths_overlap("a.py", "b.py")


def test_claims_conflict_and_release(api):
    ben = api.as_("ben", "calm-owl")
    r = api.post("/api/claims", {"paths": ["engine/sim/"], "note": "fire tuning"})
    assert r["ok"] and r["claims"][0]["path"] == "engine/sim/"
    r = ben.post("/api/claims", {"paths": ["engine/sim/fire.py"]})
    assert not r["ok"] and r["conflicts"][0]["agent_id"] == "ana/swift-fox"
    assert r["claims"]  # claimed anyway, with a warning
    r = ben.post("/api/claims", {"paths": ["engine/sim/wind.py"], "strict": True})
    assert r["claims"] == [] and r["conflicts"]
    # the inbox tells both sides
    assert ben.get("/api/inbox")["claim_conflicts"][0]["path"] == "engine/sim/"
    assert api.get("/api/inbox")["claim_conflicts"][0]["agent_id"] == "ben/calm-owl"
    # re-claiming refreshes instead of duplicating
    api.post("/api/claims", {"paths": ["engine/sim/"]})
    assert len(api.get("/api/claims?agent=ana/swift-fox")) == 1
    api.post("/api/claims/release", {})
    assert api.get("/api/claims/check?paths=engine/sim/fire.py")["conflicts"][0]["agent_id"] == "ben/calm-owl"
    assert [c["agent_id"] for c in api.get("/api/claims")] == ["ben/calm-owl"]


def test_activity_log(api):
    api.post("/api/heartbeat", {"status": "tuning wind"})
    api.post("/api/claims", {"paths": ["engine/sim/fire.py"]})
    api.call("GET", "/api/inbox", headers={"X-Board-PR": "77", "X-Board-PR-Title": "sim%3A%20wind"})
    kinds = [a["kind"] for a in api.get("/api/activity?agent=ana")]
    assert kinds == ["pr", "claim", "status", "joined"]
    agent = api.get("/api/agents")[0]
    assert agent["pr"] == 77 and agent["pr_title"] == "sim: wind"


def test_questions_digest_and_resolve(api):
    t0 = time.time()
    q = api.post("/api/messages", {"channel": "general", "kind": "question", "body": "who owns routing?"})
    api.as_("ben", "calm-owl").post("/api/messages", {"parent_id": q["id"], "body": "jalen", "resolve": True})
    d = api.get(f"/api/digest?since={t0 - 1}")
    assert d["questions_asked"][0]["id"] == q["id"]
    assert d["questions_resolved"][0]["resolved_at"] >= t0
    assert d["channels"][0]["channel"] == "general"
    assert api.get("/api/state")["open_questions"] == []


def test_suggest_uses_branch_words(api):
    add(api, "Fire spread constants", tags="sim,fire")
    add(api, "Unrelated thing")
    assert [e["title"] for e in api.get("/api/suggest?q=sim/fire-tuning")] == ["Fire spread constants"]
    assert api.get("/api/suggest?q=main") == []


def test_github_ingest_announces_new_merges(api):
    snap = {
        "issues": [{"number": 5, "title": "sim: wind", "assignees": [{"login": "ben"}], "labels": [], "url": "u", "updatedAt": "2026-10-24T10:00:00Z"}],
        "pulls": [{"number": 9, "title": "app: map", "author": {"login": "ana"}, "headRefName": "app/map", "isDraft": False, "url": "u"}],
        "merged": [{"number": 8, "title": "old", "author": {"login": "ana"}, "headRefName": "x", "url": "u", "mergedAt": "2026-10-24T09:00:00Z"}],
    }
    api.post("/api/github", snap)
    gh = api.get("/api/github")
    assert gh["issues"][0]["assignees"] == ["ben"] and gh["pulls"][0]["branch"] == "app/map"
    assert api.get("/api/channels/general/messages") == []  # backlog isn't announced
    snap["merged"].append({"number": 9, "title": "app: map", "author": {"login": "ana"}, "headRefName": "app/map", "url": "https://x/9", "mergedAt": "2026-10-24T11:00:00Z"})
    api.post("/api/github", snap)
    msgs = api.get("/api/channels/general/messages")
    assert len(msgs) == 1 and msgs[0]["author_user"] == "github" and "#9" in msgs[0]["body"]
    api.post("/api/github", snap)
    assert len(api.get("/api/channels/general/messages")) == 1


def test_export(api):
    add(api, "x")
    data = api.get("/api/export")
    assert len(data["entries"]) == 1 and "people" not in data


def test_shared_and_personal_tokens(tmp_path):
    srv, base = start(tmp_path, token="s3cret")
    try:
        anon = Client(base, "ana", "fox")
        status, _ = anon.call("POST", "/api/messages", {"body": "hi"})
        assert status == 401
        admin = Client(base, "ana", "fox", token="s3cret")
        admin.post("/api/messages", {"body": "hi"})
        tok = admin.post("/api/people/ben/token")["token"]
        # ben can post with his own token; nobody can post as ben without it now
        Client(base, "ben", "owl", token=tok).post("/api/messages", {"body": "mine"})
        status, err = Client(base, "ben", "owl", token="wrong").call("POST", "/api/messages", {"body": "fake"})
        assert status == 401 and "personal token" in err["error"]
        status, _ = Client(base, "ana", "fox", token=tok).call("POST", "/api/messages", {"body": "x"})
        assert status == 401  # ben's token isn't ana's
        status, _ = Client(base, "ana", token="").call("POST", "/api/people/ana/token", {})
        assert status == 401
    finally:
        srv.shutdown()


def test_sweep_expires_quiet_channels(board):
    api, srv = board
    api.post("/api/channels", {"name": "tmp", "ttl_hours": 1})
    m = api.post("/api/messages", {"channel": "tmp", "body": "x"})
    api.post("/api/reactions", {"target": f"m{m['id']}", "emoji": "👍"})
    srv.board.ex("update channels set last_activity = ? where name = 'tmp'", (time.time() - 7200,))
    assert srv.board.sweep() == ["tmp"]
    assert srv.board.q("select * from reactions") == []
    assert "tmp" not in [c["name"] for c in api.get("/api/channels")]


def test_events_stream(board):
    api, _ = board
    got = []

    def listen():
        with urllib.request.urlopen(api.base + "/api/events", timeout=5) as r:
            for line in r:
                if line.startswith(b"data: "):
                    ev = json.loads(line[6:])
                    if ev["type"] == "message":
                        got.append(ev)
                        return

    t = threading.Thread(target=listen, daemon=True)
    t.start()
    time.sleep(0.3)
    api.post("/api/messages", {"body": "live"})
    t.join(3)
    assert got and got[0]["data"]["body"] == "live"


def test_static_ui_or_build_hint(api):
    with urllib.request.urlopen(api.base + "/") as r:
        assert r.headers["Content-Type"].startswith("text/html")
        assert b"<" in r.read()


def test_migrates_an_old_board(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    for stmt in split_sql(MIGRATIONS[0]):
        conn.execute(stmt)
    conn.execute("insert into entries (kind, title, body, tags, author_user, created_at, updated_at) values ('gotcha', 'SSL fails on PlatformIO python', 'use cert.pem', 'board', 'ana', 1, 1)")
    conn.execute("insert into channels values ('general', '', '', 1, 1, 0)")
    conn.execute("insert into messages (channel, kind, body, author_user, created_at) values ('general', 'message', 'hello world', 'ana', 1)")
    conn.commit()
    conn.close()
    b = Board(DB(path), Bus())
    assert b.list_entries({"q": "platformio"})[0]["revisions"] == 1
    assert b.search_messages({"q": "hello"})[0]["body"] == "hello world"
    assert b.q1("pragma user_version")["user_version"] == len(MIGRATIONS)
    # opening it again doesn't re-run anything
    Board(DB(path), Bus())


def test_github_normalize_rest_shape():
    data = github.normalize({
        "issues": [{"number": 1, "title": "t", "assignees": [{"login": "a"}], "labels": [{"name": "bug"}], "html_url": "u"},
                   {"number": 2, "title": "a PR", "pull_request": {}}],
        "pulls": [{"number": 3, "title": "p", "user": {"login": "b"}, "head": {"ref": "x/y"}, "draft": True, "html_url": "u"}],
        "merged": [{"number": 4, "title": "m", "user": {"login": "c"}, "head": {"ref": "z"}, "merged_at": "2026-01-01T00:00:00Z"}],
    })
    assert [i["number"] for i in data["issues"]] == [1]
    assert data["pulls"][0] == {"number": 3, "title": "p", "author": "b", "branch": "x/y", "draft": True, "review": "", "url": "u", "updated_at": None}
    assert data["merged"][0]["merged_ts"] == 1767225600.0
