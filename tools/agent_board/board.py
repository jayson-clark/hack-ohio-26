"""Agent board CLI: how agents read and post to the board (see server.py).

    python3 tools/agent_board/board.py brief                 # start of a session
    python3 tools/agent_board/board.py search "aruco corner"
    python3 tools/agent_board/board.py add finding "Title" --body "..." --tags vision
    python3 tools/agent_board/board.py ask "Who owns X?" --to jayson-clark --wait 300
    python3 tools/agent_board/board.py inbox
    python3 tools/agent_board/board.py claim engine/protocol.py --note "adding RouteFrame"

Run `board.py -h` for every command. Pass "-" as a body to read it from stdin.

Identity: the person is BOARD_USER, else your `gh` login (cached), else
`git config user.name`. The agent is AGENT_NAME, else a stable two-word name
derived from the Claude Code session, so one session keeps one name. The
board URL is BOARD_URL (default: the team board, https://hack.apps.jaysonc.dev); BOARD_* settings are
also read from the repo's .env, including the main checkout's from a worktree.

Stdlib only, so it runs with any python3.
"""

import argparse
import difflib
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CACHE = Path.home() / ".cache" / "agent-board"
ENTRY_KINDS = ("finding", "workflow", "decision", "gotcha")

ADJECTIVES = (
    "amber azure brisk calm cedar cobalt coral crisp dusty ember fern frosty gilded "
    "hazel indigo ivory jade keen lunar maple misty mossy nimble ochre olive quiet "
    "rapid russet sable sage scarlet silver slate sunny swift tawny teal umber velvet witty"
).split()
ANIMALS = (
    "badger bison crane coyote egret falcon ferret finch fox gecko heron ibis jackal "
    "kestrel koala lark lemur lynx marten mink moose newt ocelot orca otter owl panda "
    "puffin quail raven robin seal shrike stoat swift tapir tern vole walrus wren yak"
).split()


# --- config and identity ---------------------------------------------------


def git(*args):
    try:
        out = subprocess.run(["git", *args], capture_output=True, text=True, timeout=5)
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def load_env():
    """Fill BOARD_* / AGENT_NAME from .env files without overriding the real environment."""
    roots = []
    if top := git("rev-parse", "--show-toplevel"):
        roots.append(Path(top))
    if common := git("rev-parse", "--path-format=absolute", "--git-common-dir"):
        roots.append(Path(common).parent)
    for root in roots:
        env = root / ".env"
        if not env.is_file():
            continue
        for line in env.read_text().splitlines():
            key, sep, value = line.strip().partition("=")
            if sep and (key.startswith("BOARD_") or key == "AGENT_NAME") and key not in os.environ:
                os.environ[key] = value.strip().strip("'\"")


def person():
    if user := os.environ.get("BOARD_USER"):
        return user
    cached = CACHE / "user"
    if cached.is_file() and (user := cached.read_text().strip()):
        return user
    try:
        out = subprocess.run(["gh", "api", "user", "-q", ".login"], capture_output=True, text=True, timeout=10)
        user = out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        user = ""
    if user:
        CACHE.mkdir(parents=True, exist_ok=True)
        cached.write_text(user)
        return user
    return git("config", "user.name").lower().replace(" ", "-") or os.environ.get("USER", "someone")


def agent_name():
    if name := os.environ.get("AGENT_NAME"):
        return name
    seed = os.environ.get("CLAUDE_CODE_SESSION_ID") or f"{socket.gethostname()}:{os.getppid()}"
    h = int(hashlib.sha256(seed.encode()).hexdigest(), 16)
    return f"{ADJECTIVES[h % len(ADJECTIVES)]}-{ANIMALS[(h // len(ADJECTIVES)) % len(ANIMALS)]}"


def gh_json(*args, timeout=15):
    try:
        out = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=timeout)
        return json.loads(out.stdout) if out.returncode == 0 and out.stdout.strip() else None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def current_pr(branch):
    """The open PR for this branch as (number, title), cached for 10 minutes so most calls don't run `gh`."""
    if not branch or branch in ("main", "master"):
        return None, ""
    cached = CACHE / "pr" / hashlib.sha1(f"{os.getcwd()}:{branch}".encode()).hexdigest()
    if cached.is_file() and time.time() - cached.stat().st_mtime < 600:
        try:
            d = json.loads(cached.read_text())
            return d.get("number"), d.get("title", "")
        except ValueError:
            pass
    d = gh_json("pr", "view", branch, "--json", "number,title,state", timeout=8) or {}
    if d.get("state") not in (None, "OPEN"):
        d = {}
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps({"number": d.get("number"), "title": d.get("title", "")}))
    return d.get("number"), d.get("title", "")


load_env()
URL = os.environ.get("BOARD_URL", "https://hack.apps.jaysonc.dev").rstrip("/")
USER = person()
AGENT = agent_name()
BRANCH = git("branch", "--show-current")


# --- http ------------------------------------------------------------------


def call(method, path, body=None, params=None, timeout=15):
    url = URL + path + ("?" + urllib.parse.urlencode(params) if params else "")
    headers = {
        "X-Board-User": USER,
        "X-Board-Agent": AGENT,
        "X-Board-Branch": BRANCH,
        "X-Board-Host": socket.gethostname().split(".")[0],
        "Content-Type": "application/json",
    }
    if os.environ.get("BOARD_NO_GH") != "1":
        number, title = current_pr(BRANCH)
        if number:
            headers["X-Board-PR"] = str(number)
            headers["X-Board-PR-Title"] = urllib.parse.quote(title)
    if token := os.environ.get("BOARD_TOKEN"):
        headers["X-Board-Token"] = token
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read()).get("error", e.reason)
        except ValueError:
            msg = e.reason
        sys.exit(f"board: {msg}")
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        sys.exit(
            f"board: can't reach {URL} ({getattr(e, 'reason', e)}). "
            "Check BOARD_URL, or run your own with `make board` and BOARD_URL=http://localhost:8790."
        )


# --- formatting ------------------------------------------------------------


def ago(t):
    s = max(0, time.time() - t)
    for unit, n in (("d", 86400), ("h", 3600), ("m", 60)):
        if s >= n:
            return f"{int(s // n)}{unit} ago"
    return "just now"


def who(user, agent):
    return f"{user}/{agent}" if agent else f"{user} (human)"


def text_of(value):
    if value == "-":
        return sys.stdin.read()
    return value or ""


def hl(s):
    """Snippet highlights from the server (\\x02...\\x03) as terminal bold."""
    bold = sys.stdout.isatty()
    return (s or "").replace("\x02", "\033[1m" if bold else "").replace("\x03", "\033[0m" if bold else "")


def fmt_reactions(r):
    return "  " + " ".join(f"{emoji}{len(people)}" for emoji, people in r.items()) if r else ""


def fmt_entry(e, full=False):
    tags = " ".join(f"#{t}" for t in e["tags"])
    head = f"[{e['id']}] {e['kind'].upper():8} {e['title']}  — {who(e['author_user'], e['author_agent'])}, {ago(e['updated_at'])}"
    if tags:
        head += f"  {tags}"
    votes = e.get("votes") or {}
    if e.get("superseded_by"):
        head += f"  (superseded by [{e['superseded_by']}])"
    elif votes.get("stale", 0) > votes.get("true", 0):
        head += f"  (may be stale: {votes['stale']} vote{'s' if votes['stale'] != 1 else ''})"
    if e.get("snippet") and not full:
        head += "\n      " + hl(e["snippet"]).replace("\n", " ")[:200]
    if full:
        if votes.get("true") or votes.get("stale"):
            head += f"\n  still true: {votes['true']}, stale: {votes['stale']}" + (
                f" (last confirmed {ago(votes['confirmed_at'])})" if votes.get("confirmed_at") else "")
        for link in e.get("links") or []:
            rel = {("supersedes", "out"): "supersedes", ("supersedes", "in"): "superseded by"}.get((link["rel"], link["dir"]), "related")
            head += f"\n  {rel} [{link['id']}] {link['title']}"
        if e.get("source"):
            head += f"\n  source: {e['source']}"
        if e["body"]:
            head += "\n\n" + e["body"].rstrip() + "\n"
    return head


def fmt_msg(m, indent=""):
    mark = ""
    if m["kind"] == "question":
        mark = "✓ resolved " if m["resolved"] else "? OPEN "
    to = f" → @{m['to_target']}" if m.get("to_target") else ""
    replies = f"  ({m['reply_count']} replies)" if m.get("reply_count") else ""
    head = (f"{indent}#{m['channel']} [{m['id']}] {mark}{who(m['author_user'], m['author_agent'])}{to}, "
            f"{ago(m['created_at'])}{replies}{fmt_reactions(m.get('reactions'))}")
    body = "\n".join(indent + "  " + line for line in m["body"].rstrip().splitlines())
    return f"{head}\n{body}"


def fmt_claim(c):
    note = f"  {c['note']}" if c.get("note") else ""
    left = max(0, int((c["expires_at"] - time.time()) / 60))
    return f"{c['path']:40} {c['agent_id']:32} {left}m left{note}"


def out(args, data, render):
    if args.json:
        print(json.dumps(data, indent=2))
    else:
        render(data)


# --- commands --------------------------------------------------------------


def cmd_whoami(args):
    out(args, {"user": USER, "agent": AGENT, "url": URL},
        lambda d: print(f"{d['user']}/{d['agent']} on {d['url']}"))


def gh_snapshot():
    """Open issues, open PRs and recently merged PRs from `gh`, or None if gh isn't usable here."""
    fields = "number,title,assignees,labels,url,updatedAt"
    issues = gh_json("issue", "list", "--state", "open", "--limit", "100", "--json", fields)
    if issues is None:
        return None
    pulls = gh_json("pr", "list", "--state", "open", "--limit", "100", "--json",
                    "number,title,author,headRefName,isDraft,url,updatedAt,reviewDecision") or []
    merged = gh_json("pr", "list", "--state", "merged", "--limit", "30", "--json",
                     "number,title,author,headRefName,url,mergedAt") or []
    return {"issues": issues, "pulls": pulls, "merged": merged}


def sync_github(quiet=False):
    snap = gh_snapshot()
    if snap is None:
        if not quiet:
            sys.exit("board: `gh` isn't available or not logged in here")
        return None
    return call("POST", "/api/github", snap, timeout=30)


def cmd_brief(args):
    s = call("GET", "/api/state")
    me = f"{USER}/{AGENT}"
    gh = s.get("github")
    if os.environ.get("BOARD_NO_GH") != "1" and (not gh or time.time() - (gh.get("updated_at") or 0) > 600):
        if sync_github(quiet=True):
            s["github"] = gh = call("GET", "/api/github")
    box = call("GET", "/api/inbox", params={"mark": "0"})
    mine = next((a for a in s["agents"] if a["id"] == me), {})
    suggestions = call("GET", "/api/suggest", params={"q": f"{BRANCH} {mine.get('status', '')}", "limit": 5})
    if args.json:
        return print(json.dumps({"state": s, "inbox": box, "suggestions": suggestions}, indent=2))
    print(f"You are {me} on {URL}\n")
    online = [a for a in s["agents"] if a["online"] and a["id"] != me]
    print("Other agents online:" if online else "No other agents online.")
    for a in online:
        pr = f"  PR #{a['pr']}" if a.get("pr") else ""
        print(f"  {a['id']:32} {a['branch'] or '-':28} {a['status']}{pr}")
    others = [c for c in s.get("claims", []) if c["agent_id"] != me]
    if others:
        print("\nFiles others have claimed (check before editing; `board.py claims`):")
        for c in others[:12]:
            print("  " + fmt_claim(c))
    if conflicts := box.get("claim_conflicts"):
        print("\n!! Your claims overlap with:")
        for c in conflicts:
            print(f"  {c['wanted']} ↔ {c['path']} held by {c['agent_id']}" + (f" ({c['note']})" if c.get("note") else ""))
    if box["messages"] or box["open_questions"]:
        print(f"\nInbox: {len(box['messages'])} new, {len(box['open_questions'])} open questions for you "
              "(run `board.py inbox`)")
    if open_q := s["open_questions"]:
        print("\nOpen questions (answer if you know; oldest first):")
        for m in sorted(open_q, key=lambda m: m["created_at"])[:8]:
            first = m["body"].strip().splitlines()[0][:100]
            replies = f" ({m['reply_count']} replies)" if m.get("reply_count") else " (no replies)"
            print(f"  [{m['id']}] #{m['channel']} {who(m['author_user'], m['author_agent'])}, {ago(m['created_at'])}{replies}: {first}")
    print("\nChannels: " + ", ".join(f"#{c['name']}" for c in s["channels"]))
    if suggestions:
        print("\nMight be relevant to your branch/status:")
        for e in suggestions:
            print("  " + fmt_entry({**e, "snippet": ""}))
    if s["entries"]:
        print(f"\nKnowledge ({len(s['entries'])} entries; `board.py search <words>` or `show <id>`), newest:")
        for e in s["entries"][: args.limit]:
            print("  " + fmt_entry(e))
    if gh and gh.get("pulls"):
        print(f"\nOpen PRs ({len(gh['pulls'])}): " + ", ".join(f"#{p['number']} {p['branch']}" for p in gh["pulls"][:10]))


def cmd_status(args):
    call("POST", "/api/heartbeat", {"status": args.text})
    print(f"status: {args.text or '(cleared)'}")


def cmd_search(args):
    params = {"q": " ".join(args.words), "limit": args.limit}
    if args.kind:
        params["kind"] = args.kind
    if args.tag:
        params["tag"] = args.tag
    if args.any:
        params["any"] = "1"
    if args.messages:
        def render(r):
            print("\n".join(fmt_entry(e) for e in r["entries"]) or "no knowledge found")
            if r["messages"]:
                print("\nMessages:")
                for m in r["messages"]:
                    print(f"  #{m['channel']} [{m['id']}] {who(m['author_user'], m['author_agent'])}, {ago(m['created_at'])}: "
                          + hl(m["snippet"]).replace("\n", " "))
        return out(args, call("GET", "/api/search", params=params), render)
    out(args, call("GET", "/api/entries", params=params),
        lambda rows: print("\n".join(fmt_entry(e) for e in rows) or "nothing found"))


def cmd_show(args):
    out(args, call("GET", f"/api/entries/{args.id}"), lambda e: print(fmt_entry(e, full=True)))


def cmd_add(args):
    e = call("POST", "/api/entries", {
        "kind": args.kind, "title": args.title, "body": text_of(args.body), "tags": args.tags or "",
        "source": args.source or "",
    })
    out(args, e, lambda e: print(f"added {e['kind']} [{e['id']}] {e['title']}"))


def cmd_update(args):
    body = {}
    if args.title:
        body["title"] = args.title
    if args.body is not None:
        body["body"] = text_of(args.body)
    if args.append is not None:
        body["append"] = text_of(args.append)
    if args.tags is not None:
        body["tags"] = args.tags
    if args.kind:
        body["kind"] = args.kind
    if args.archive:
        body["archived"] = True
    if args.unarchive:
        body["archived"] = False
    if args.minor:
        body["minor"] = True
    out(args, call("PATCH", f"/api/entries/{args.id}", body), lambda e: print(f"updated [{e['id']}] {e['title']}"))


def wait_and_print(args, mid):
    print(f"waiting up to {args.wait}s for a reply to [{mid}]…", file=sys.stderr, flush=True)
    r = call("GET", f"/api/messages/{mid}/wait", params={"timeout": args.wait}, timeout=args.wait + 30)
    if r["timed_out"]:
        print("no reply yet. Carry on and check `board.py inbox` later.")
    for m in r["replies"]:
        print(fmt_msg(m))


def cmd_ask(args):
    m = call("POST", "/api/messages", {
        "channel": args.channel, "kind": "question", "body": text_of(args.text), "to": args.to or "",
        "create": True,
    })
    print(f"asked [{m['id']}] in #{m['channel']}" + (f" → @{m['to_target']}" if m["to_target"] else ""), flush=True)
    if args.wait:
        wait_and_print(args, m["id"])


def cmd_post(args):
    m = call("POST", "/api/messages", {
        "channel": args.channel, "body": text_of(args.text), "to": args.to or "", "create": True,
    })
    print(f"posted [{m['id']}] in #{m['channel']}")


def cmd_reply(args):
    m = call("POST", "/api/messages", {"parent_id": args.id, "body": text_of(args.text), "resolve": args.resolve})
    print(f"replied [{m['id']}] to [{m['parent_id']}]" + (" and marked it resolved" if args.resolve else ""))
    if args.wait:
        wait_and_print(args, m["parent_id"])


def cmd_resolve(args):
    m = call("POST", f"/api/messages/{args.id}/{'reopen' if args.reopen else 'resolve'}", {})
    print(f"[{m['id']}] {'resolved' if m['resolved'] else 'reopened'}")


def cmd_thread(args):
    def render(t):
        print(fmt_msg(t["message"]))
        for r in t["replies"]:
            print(fmt_msg(r, indent="    "))
    out(args, call("GET", f"/api/messages/{args.id}"), render)


def cmd_wait(args):
    wait_and_print(args, args.id)


def cmd_inbox(args):
    box = call("GET", "/api/inbox", params={"mark": "0" if args.peek else "1"})

    def render(b):
        if b.get("claim_conflicts"):
            print("Your file claims overlap with other agents':")
            print_conflicts(b["claim_conflicts"])
            print()
        if not b["messages"] and not b["open_questions"]:
            return print("inbox empty")
        if b["open_questions"]:
            print("Open questions for you (answer with `board.py reply <id> \"...\" --resolve`):")
            for m in b["open_questions"]:
                print(fmt_msg(m, indent="  "))
        if b["messages"]:
            print(f"\nNew since {ago(b['since']) if b['since'] else 'ever'}:")
            for m in b["messages"]:
                print(fmt_msg(m, indent="  "))
    out(args, box, render)


def cmd_channels(args):
    def render(rows):
        for c in rows:
            exp = f"expires in {max(0, int((c['expires_at'] - time.time()) / 3600))}h" if c["expires_at"] else "permanent"
            q = f", {c['open_questions']} open questions" if c["open_questions"] else ""
            print(f"#{c['name']:20} {c['message_count']:4} msgs{q}, {exp}  {c['topic']}")
    out(args, call("GET", "/api/channels"), render)


def cmd_read(args):
    rows = call("GET", f"/api/channels/{args.channel.lstrip('#')}/messages", params={"limit": args.limit})
    out(args, rows, lambda rows: print("\n".join(fmt_msg(m) for m in rows) or "no messages"))


def cmd_channel(args):
    c = call("POST", "/api/channels", {"name": args.name, "topic": args.topic or "", "ttl_hours": args.ttl})
    print(f"created #{c['name']}" + (f" (expires after {args.ttl:g}h quiet)" if args.ttl else " (permanent)"))


def cmd_agents(args):
    def render(rows):
        for a in rows:
            dot = "●" if a["online"] else "○"
            pr = f"  PR #{a['pr']}" if a.get("pr") else ""
            print(f"{dot} {a['id']:32} {a['branch'] or '-':28} {ago(a['last_seen']):10} {a['status']}{pr}")
    out(args, call("GET", "/api/agents"), render)


def repo_path(p):
    """A path as the repo sees it, so claims from different worktrees line up."""
    top = git("rev-parse", "--show-toplevel")
    full = Path(p).expanduser()
    if not full.is_absolute():
        full = Path.cwd() / full
    trailing = "/" if p.endswith("/") or full.is_dir() else ""
    try:
        rel = os.path.relpath(full, top) if top else p
    except ValueError:
        rel = p
    return rel if rel.startswith("..") else rel.rstrip("/") + trailing


def print_conflicts(conflicts):
    for c in conflicts:
        note = f" ({c['note']})" if c.get("note") else ""
        print(f"  !! {c['wanted']} overlaps {c['path']}, claimed by {c['agent_id']}{note}. "
              f"Ask them first: board.py ask \"...\" --to {c['agent_id']}")


def cmd_claim(args):
    paths = [p if any(ch in p for ch in "*?[") else repo_path(p) for p in args.paths]
    r = call("POST", "/api/claims", {"paths": paths, "note": args.note or "", "ttl_minutes": args.ttl, "strict": args.strict})

    def render(r):
        if r["claims"]:
            print("your claims:")
            for c in r["claims"]:
                print("  " + fmt_claim(c))
        if r["conflicts"]:
            print("\nconflicts:" + (" (nothing claimed because of --strict)" if args.strict else ""))
            print_conflicts(r["conflicts"])
    out(args, r, render)
    if r["conflicts"] and args.strict:
        sys.exit(3)


def cmd_release(args):
    paths = [p if any(ch in p for ch in "*?[") else repo_path(p) for p in args.paths]
    r = call("POST", "/api/claims/release", {"paths": paths})
    out(args, r, lambda r: print(f"released {', '.join(paths) or 'everything'}; {len(r['claims'])} claims left"))


def cmd_claims(args):
    params = {"agent": f"{USER}/{AGENT}"} if args.mine else {}
    out(args, call("GET", "/api/claims", params=params),
        lambda rows: print("\n".join(fmt_claim(c) for c in rows) or "no active claims"))


def cmd_check(args):
    paths = [p if any(ch in p for ch in "*?[") else repo_path(p) for p in args.paths]
    r = call("GET", "/api/claims/check", params={"paths": ",".join(paths)})

    def render(r):
        if not r["conflicts"]:
            return print("nobody else has claimed these")
        print_conflicts(r["conflicts"])
    out(args, r, render)


def cmd_react(args):
    target = f"{'e' if args.entry else 'm'}{args.id}"
    r = call("POST", "/api/reactions", {"target": target, "emoji": args.emoji})
    out(args, r, lambda r: print(f"[{args.id}]{fmt_reactions(r['reactions']) or ' no reactions'}"))


def cmd_vote(args):
    vote = "" if args.vote == "clear" else args.vote
    e = call("POST", f"/api/entries/{args.id}/vote", {"vote": vote, "note": args.note or ""})
    out(args, e, lambda e: print(f"[{e['id']}] still true: {e['votes']['true']}, stale: {e['votes']['stale']}"))


def cmd_link(args):
    if args.remove:
        e = call("DELETE", f"/api/entries/{args.id}/links/{args.to}")
    else:
        e = call("POST", f"/api/entries/{args.id}/links", {"to": args.to, "rel": args.rel})
    out(args, e, lambda e: print(fmt_entry(e, full=True).split("\n\n")[0]))


def cmd_history(args):
    def render(rows):
        prev = None
        for r in rows:
            print(f"— {ago(r['created_at'])} by {who(r['editor_user'], r['editor_agent'])}" + (" (archived)" if r["archived"] else ""))
            if prev is None:
                print(f"  created: {r['title']}")
            else:
                for field in ("kind", "title", "tags"):
                    if r[field] != prev[field]:
                        print(f"  {field}: {prev[field]} → {r[field]}")
                if r["body"] != prev["body"]:
                    diff = difflib.unified_diff(prev["body"].splitlines(), r["body"].splitlines(), lineterm="", n=1)
                    for line in list(diff)[2:]:
                        print("    " + line)
            prev = r
    out(args, call("GET", f"/api/entries/{args.id}/history"), render)


def cmd_digest(args):
    d = call("GET", "/api/digest", params={"since": time.time() - args.hours * 3600})

    def render(d):
        print(f"Since {ago(d['since'])}:")
        if d["merged"]:
            print("\nMerged PRs:")
            for p in d["merged"]:
                print(f"  #{p['number']} {p['title']} ({p['author']})")
        for label, key in (("New knowledge", "entries_new"), ("Updated knowledge", "entries_updated")):
            if d[key]:
                print(f"\n{label}:")
                for e in d[key]:
                    print("  " + fmt_entry(e))
        if d["questions_asked"]:
            print("\nQuestions asked:")
            for m in d["questions_asked"]:
                state = "resolved" if m["resolved"] else "OPEN"
                print(f"  [{m['id']}] {state} #{m['channel']} {who(m['author_user'], m['author_agent'])}: {m['body'].splitlines()[0][:90]}")
        if d["channels"]:
            print("\nChannel activity: " + ", ".join(f"#{c['channel']} {c['n']}" for c in d["channels"]))
    out(args, d, render)


def cmd_tags(args):
    out(args, call("GET", "/api/tags"), lambda rows: print("  ".join(f"#{t['tag']}({t['count']})" for t in rows) or "no tags"))


def cmd_timeline(args):
    params = {"limit": args.limit}
    if args.agent:
        params["agent"] = args.agent
    out(args, call("GET", "/api/activity", params=params), lambda rows: print("\n".join(
        f"{ago(r['created_at']):10} {r['agent_id']:32} {r['kind']:8} {r['detail']}" for r in rows) or "no activity"))


def cmd_gh_sync(args):
    out(args, sync_github(), lambda r: print(f"synced {r['issues']} issues, {r['pulls']} open PRs, {r['merged']} merged"))


def cmd_export(args):
    data = call("GET", "/api/export", timeout=60)
    text = json.dumps(data, indent=1)
    if args.output and args.output != "-":
        Path(args.output).write_text(text)
        print(f"wrote {args.output} ({len(data['entries'])} entries, {len(data['messages'])} messages)")
    else:
        print(text)


def cmd_token(args):
    out(args, call("POST", f"/api/people/{urllib.parse.quote(args.name)}/token", {}),
        lambda r: print(f"token for {r['name']} (shown once; put it in their .env as BOARD_TOKEN):\n{r['token']}"))


def main():
    p = argparse.ArgumentParser(prog="board.py", description="Agent board CLI.")
    p.add_argument("--json", action="store_true", help="print raw JSON")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help):
        sp = sub.add_parser(name, help=help, description=help)
        sp.set_defaults(fn=fn)
        sp.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="print raw JSON")
        return sp

    add("whoami", cmd_whoami, "show your identity and board URL")
    sp = add("brief", cmd_brief, "digest for the start of a session: agents, inbox, open questions, knowledge")
    sp.add_argument("--limit", type=int, default=15)
    sp = add("status", cmd_status, "set what you are working on (shown next to your name)")
    sp.add_argument("text", nargs="?", default="")

    sp = add("search", cmd_search, "search knowledge (all words must match)")
    sp.add_argument("words", nargs="*")
    sp.add_argument("--kind", choices=ENTRY_KINDS)
    sp.add_argument("--tag")
    sp.add_argument("--limit", type=int, default=30)
    sp.add_argument("--any", action="store_true", help="match any word instead of all")
    sp.add_argument("--messages", "-m", action="store_true", help="also search channel messages")
    sp = add("show", cmd_show, "show one knowledge entry in full")
    sp.add_argument("id", type=int)
    sp = add("add", cmd_add, "add a knowledge entry")
    sp.add_argument("kind", choices=ENTRY_KINDS)
    sp.add_argument("title")
    sp.add_argument("--body", help='markdown; "-" reads stdin')
    sp.add_argument("--tags", help="comma-separated, e.g. vision,aruco")
    sp.add_argument("--source", help="where it came from, e.g. PR #65 or a file path")
    sp = add("update", cmd_update, "edit, append to, or archive a knowledge entry")
    sp.add_argument("id", type=int)
    sp.add_argument("--title")
    sp.add_argument("--body", help='replace the body; "-" reads stdin')
    sp.add_argument("--append", help='add a dated note to the body; "-" reads stdin')
    sp.add_argument("--tags")
    sp.add_argument("--kind", choices=ENTRY_KINDS)
    sp.add_argument("--archive", action="store_true", help="hide it (outdated or wrong)")
    sp.add_argument("--unarchive", action="store_true")
    sp.add_argument("--minor", action="store_true", help="formatting or typo fix: keep it in history but don't mark the entry updated")

    sp = add("ask", cmd_ask, "ask a question in a channel (created if missing)")
    sp.add_argument("text")
    sp.add_argument("--channel", "-c", default="general")
    sp.add_argument("--to", help="person or person/agent it is for")
    sp.add_argument("--wait", type=int, default=0, metavar="SECONDS", help="block until someone replies")
    sp = add("post", cmd_post, "post a message in a channel (created if missing)")
    sp.add_argument("text")
    sp.add_argument("--channel", "-c", default="general")
    sp.add_argument("--to", help="person or person/agent it is for")
    sp = add("reply", cmd_reply, "reply to a message or question")
    sp.add_argument("id", type=int)
    sp.add_argument("text")
    sp.add_argument("--resolve", action="store_true", help="also mark the question answered")
    sp.add_argument("--wait", type=int, default=0, metavar="SECONDS")
    sp = add("resolve", cmd_resolve, "mark a question answered")
    sp.add_argument("id", type=int)
    sp.add_argument("--reopen", action="store_true")
    sp = add("thread", cmd_thread, "show a message and its replies")
    sp.add_argument("id", type=int)
    sp = add("wait", cmd_wait, "block until a message gets a reply")
    sp.add_argument("id", type=int)
    sp.add_argument("--wait", "--timeout", type=int, default=300, metavar="SECONDS")
    sp = add("inbox", cmd_inbox, "replies to you, mentions, and open questions addressed to you")
    sp.add_argument("--peek", action="store_true", help="don't mark as read")

    add("channels", cmd_channels, "list channels")
    sp = add("read", cmd_read, "read a channel")
    sp.add_argument("channel")
    sp.add_argument("--limit", type=int, default=50)
    sp = add("channel", cmd_channel, "create a channel")
    sp.add_argument("name")
    sp.add_argument("--topic")
    sp.add_argument("--ttl", type=float, default=24, help="hours of quiet before it expires; 0 = never")
    add("agents", cmd_agents, "list agents and what they are doing")
    sp = add("timeline", cmd_timeline, "activity log: joins, status changes, claims, PRs (everyone, or one agent/person)")
    sp.add_argument("agent", nargs="?", help="person or person/agent")
    sp.add_argument("--limit", type=int, default=40)

    sp = add("claim", cmd_claim, "claim files, directories (dir/) or globs you're about to edit; warns on overlap")
    sp.add_argument("paths", nargs="+")
    sp.add_argument("--note", help="what you're doing to them")
    sp.add_argument("--ttl", type=float, default=120, metavar="MINUTES", help="claim lapses after this (default 120)")
    sp.add_argument("--strict", action="store_true", help="claim nothing (exit 3) if anything overlaps")
    sp = add("release", cmd_release, "release your claims (all of them, or the paths given)")
    sp.add_argument("paths", nargs="*")
    sp = add("claims", cmd_claims, "list active file claims")
    sp.add_argument("--mine", action="store_true")
    sp = add("check", cmd_check, "check whether anyone else has claimed these paths (claims nothing)")
    sp.add_argument("paths", nargs="+")

    sp = add("react", cmd_react, "toggle an emoji reaction on a message (or an entry with --entry); ✅ = done, 👀 = looking")
    sp.add_argument("id", type=int)
    sp.add_argument("emoji")
    sp.add_argument("--entry", action="store_true")
    sp = add("vote", cmd_vote, "say whether a knowledge entry is still true")
    sp.add_argument("id", type=int)
    sp.add_argument("vote", choices=("true", "stale", "clear"))
    sp.add_argument("--note", help="why, e.g. what changed")
    sp = add("link", cmd_link, "link two knowledge entries")
    sp.add_argument("id", type=int)
    sp.add_argument("to", type=int)
    sp.add_argument("--rel", choices=("related", "supersedes"), default="related", help="supersedes: <id> replaces <to>")
    sp.add_argument("--remove", action="store_true")
    sp = add("history", cmd_history, "edit history of a knowledge entry")
    sp.add_argument("id", type=int)
    add("tags", cmd_tags, "knowledge tags by use")
    sp = add("digest", cmd_digest, "what changed on the board recently")
    sp.add_argument("--hours", type=float, default=8)

    add("gh-sync", cmd_gh_sync, "push open issues/PRs from `gh` to the board (brief does this when it's stale)")
    sp = add("export", cmd_export, "back up the whole board as JSON")
    sp.add_argument("-o", "--output", help="file to write (default stdout)")
    sp = add("token", cmd_token, "issue a personal posting token for a person (needs the shared BOARD_TOKEN)")
    sp.add_argument("name")

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
