"""GitHub issues and PRs on the board, so the UI can show who's on what.

Two ways in, both ending in `ingest()`:
- the server polls the REST API itself when GITHUB_TOKEN is set (BOARD_REPO
  names the repo), or
- any agent pushes a snapshot it got from `gh` (`board.py gh-sync`, which
  `brief` runs when the board's copy is more than a few minutes old). That way
  a private repo works without giving the deployed board a token.

Newly merged PRs are announced in #general.
"""

import json
import os
import threading
import time
import urllib.request
from datetime import datetime

REPO = os.environ.get("BOARD_REPO", "jayson-clark/hack-ohio-26")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
POLL_SECONDS = 90
ANNOUNCE = os.environ.get("BOARD_ANNOUNCE_MERGES", "1") != "0"
BOT = {"user": "github", "agent": "", "branch": "", "host": ""}


def ts(iso):
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def login(v):
    if isinstance(v, dict):
        return v.get("login") or ""
    return str(v or "")


def normalize(snap):
    """Accept either `gh --json` output or REST API objects; return the board's shape."""
    issues = [{
        "number": int(i["number"]),
        "title": str(i.get("title", ""))[:300],
        "assignees": [login(a) for a in i.get("assignees") or []],
        "labels": [l.get("name", "") if isinstance(l, dict) else str(l) for l in i.get("labels") or []],
        "url": i.get("url") or i.get("html_url") or "",
        "updated_at": ts(i.get("updatedAt") or i.get("updated_at")),
    } for i in snap.get("issues") or [] if "pull_request" not in i]
    pulls = [{
        "number": int(p["number"]),
        "title": str(p.get("title", ""))[:300],
        "author": login(p.get("author") or p.get("user")),
        "branch": p.get("headRefName") or (p.get("head") or {}).get("ref", ""),
        "draft": bool(p.get("isDraft", p.get("draft", False))),
        "review": p.get("reviewDecision") or "",
        "url": p.get("url") or p.get("html_url") or "",
        "updated_at": ts(p.get("updatedAt") or p.get("updated_at")),
    } for p in snap.get("pulls") or []]
    merged = [{
        "number": int(p["number"]),
        "title": str(p.get("title", ""))[:300],
        "author": login(p.get("author") or p.get("user")),
        "branch": p.get("headRefName") or (p.get("head") or {}).get("ref", ""),
        "url": p.get("url") or p.get("html_url") or "",
        "merged_ts": ts(p.get("mergedAt") or p.get("merged_at")),
    } for p in snap.get("merged") or [] if p.get("mergedAt") or p.get("merged_at")]
    merged.sort(key=lambda p: -(p["merged_ts"] or 0))
    return {"repo": snap.get("repo") or REPO, "issues": issues, "pulls": pulls, "merged": merged[:30]}


def ingest(board, snap, source):
    data = normalize(snap)
    data["source"] = source
    board.kv_set("github", data)
    board.publish("github", {**data, "updated_at": time.time()})
    announce(board, data)
    return {"ok": True, "issues": len(data["issues"]), "pulls": len(data["pulls"]), "merged": len(data["merged"])}


def announce(board, data):
    seen, _ = board.kv_get("github:announced", None)
    numbers = [p["number"] for p in data["merged"]]
    if seen is None:
        # First snapshot: don't announce the backlog.
        board.kv_set("github:announced", numbers)
        return
    fresh = [p for p in data["merged"] if p["number"] not in set(seen)]
    if not fresh:
        return
    board.kv_set("github:announced", sorted(set(seen) | set(numbers))[-500:])
    if not ANNOUNCE:
        return
    for p in reversed(fresh):
        branch = f" (`{p['branch']}`)" if p["branch"] else ""
        board.post_message(BOT, {"channel": "general", "body": f"Merged [#{p['number']}]({p['url']}) **{p['title']}** by {p['author']}{branch}"})


def get(path):
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/{path}",
        headers={"Authorization": f"Bearer {GITHUB_TOKEN}", "Accept": "application/vnd.github+json", "User-Agent": "agent-board"},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def poll(board):
    while True:
        try:
            closed = get("pulls?state=closed&sort=updated&direction=desc&per_page=30")
            ingest(board, {
                "issues": get("issues?state=open&per_page=100"),
                "pulls": get("pulls?state=open&per_page=100"),
                "merged": [p for p in closed if p.get("merged_at")],
            }, "server")
        except Exception as e:  # network or rate limit; try again next round
            print(f"github poll failed: {e}", flush=True)
        time.sleep(POLL_SECONDS)


def start(board):
    if GITHUB_TOKEN:
        threading.Thread(target=poll, args=(board,), daemon=True).start()
        return True
    return False
