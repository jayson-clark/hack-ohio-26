import json
import os
import subprocess
import sys

from conftest import BOARD


def run(api, *args, agent="swift-fox", stdin=None):
    env = {**os.environ, "BOARD_URL": api.base, "BOARD_USER": api.user, "AGENT_NAME": agent, "BOARD_NO_GH": "1", "BOARD_TOKEN": ""}
    out = subprocess.run([sys.executable, str(BOARD / "board.py"), *args], capture_output=True, text=True, env=env,
                         input=stdin, timeout=30, cwd=BOARD.parent.parent)
    return out.returncode, out.stdout + out.stderr


def test_add_search_show(api):
    code, out = run(api, "add", "gotcha", "Vite needs envDir", "--body", "-", "--tags", "app,vite", stdin="set envDir to ..\n")
    assert code == 0 and "added gotcha [1]" in out
    code, out = run(api, "search", "envdir")
    assert "[1] GOTCHA" in out and "#app" in out
    code, out = run(api, "--json", "show", "1")
    assert json.loads(out)["body"] == "set envDir to .."


def test_claims_warn_on_overlap(api):
    run(api, "claim", "engine/sim/", "--note", "wind")
    code, out = run(api, "claim", "engine/sim/fire.py", agent="calm-owl")
    assert code == 0 and "claimed by ana/swift-fox (wind)" in out
    code, out = run(api, "claim", "engine/sim/x.py", "--strict", agent="calm-owl")
    assert code == 3
    code, out = run(api, "brief", agent="calm-owl")
    assert "Files others have claimed" in out and "engine/sim/" in out
    assert "Your claims overlap" in out or "overlap with" in out
    run(api, "release")
    code, out = run(api, "claims")
    assert "swift-fox" not in out


def test_react_vote_link_history(api):
    run(api, "add", "finding", "Old way")
    run(api, "add", "finding", "New way")
    code, out = run(api, "link", "2", "1", "--rel", "supersedes")
    assert code == 0 and "supersedes [1]" in out
    code, out = run(api, "search", "way")
    assert "(superseded by [2])" in out
    code, out = run(api, "vote", "2", "true")
    assert "still true: 1" in out
    run(api, "update", "2", "--append", "also on main")
    code, out = run(api, "history", "2")
    assert "+also on main" in out
    run(api, "post", "merged it")
    code, out = run(api, "react", "1", "✅")
    assert "✅1" in out


def test_digest_and_timeline(api):
    run(api, "status", "testing the CLI")
    run(api, "ask", "anyone?", "-c", "general")
    code, out = run(api, "digest")
    assert "Questions asked" in out and "anyone?" in out
    code, out = run(api, "timeline", "ana")
    assert "status" in out and "testing the CLI" in out
