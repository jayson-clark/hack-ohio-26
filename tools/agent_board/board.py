"""Agent board CLI: how agents read and post to the board (see server.py).

    python3 tools/agent_board/board.py brief                 # start of a session
    python3 tools/agent_board/board.py search "aruco corner"
    python3 tools/agent_board/board.py add finding "Title" --body "..." --tags vision
    python3 tools/agent_board/board.py ask "Who owns X?" --to jayson-clark --wait 300
    python3 tools/agent_board/board.py inbox

Run `board.py -h` for every command. Pass "-" as a body to read it from stdin.

Identity: the person is BOARD_USER, else your `gh` login (cached), else
`git config user.name`. The agent is AGENT_NAME, else a stable two-word name
derived from the Claude Code session, so one session keeps one name. The
board URL is BOARD_URL (default: the team board, https://hack.apps.jaysonc.dev); BOARD_* settings are
also read from the repo's .env, including the main checkout's from a worktree.

Stdlib only, so it runs with any python3.
"""

import argparse
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


load_env()
URL = os.environ.get("BOARD_URL", "https://hack.apps.jaysonc.dev").rstrip("/")
USER = person()
AGENT = agent_name()


# --- http ------------------------------------------------------------------


def call(method, path, body=None, params=None, timeout=15):
    url = URL + path + ("?" + urllib.parse.urlencode(params) if params else "")
    headers = {
        "X-Board-User": USER,
        "X-Board-Agent": AGENT,
        "X-Board-Branch": git("branch", "--show-current"),
        "X-Board-Host": socket.gethostname().split(".")[0],
        "Content-Type": "application/json",
    }
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


def fmt_entry(e, full=False):
    tags = " ".join(f"#{t}" for t in e["tags"])
    head = f"[{e['id']}] {e['kind'].upper():8} {e['title']}  — {who(e['author_user'], e['author_agent'])}, {ago(e['updated_at'])}"
    if tags:
        head += f"  {tags}"
    if full and e["body"]:
        head += "\n\n" + e["body"].rstrip() + "\n"
    return head


def fmt_msg(m, indent=""):
    mark = ""
    if m["kind"] == "question":
        mark = "✓ resolved " if m["resolved"] else "? OPEN "
    to = f" → @{m['to_target']}" if m.get("to_target") else ""
    replies = f"  ({m['reply_count']} replies)" if m.get("reply_count") else ""
    head = f"{indent}#{m['channel']} [{m['id']}] {mark}{who(m['author_user'], m['author_agent'])}{to}, {ago(m['created_at'])}{replies}"
    body = "\n".join(indent + "  " + line for line in m["body"].rstrip().splitlines())
    return f"{head}\n{body}"


def out(args, data, render):
    if args.json:
        print(json.dumps(data, indent=2))
    else:
        render(data)


# --- commands --------------------------------------------------------------


def cmd_whoami(args):
    out(args, {"user": USER, "agent": AGENT, "url": URL},
        lambda d: print(f"{d['user']}/{d['agent']} on {d['url']}"))


def cmd_brief(args):
    s = call("GET", "/api/state")
    box = call("GET", "/api/inbox", params={"mark": "0"})
    if args.json:
        return print(json.dumps({"state": s, "inbox": box}, indent=2))
    print(f"You are {USER}/{AGENT} on {URL}\n")
    online = [a for a in s["agents"] if a["online"] and a["id"] != f"{USER}/{AGENT}"]
    print("Other agents online:" if online else "No other agents online.")
    for a in online:
        print(f"  {a['id']:32} {a['branch'] or '-':28} {a['status']}")
    if box["messages"] or box["open_questions"]:
        print(f"\nInbox: {len(box['messages'])} new, {len(box['open_questions'])} open questions for you "
              "(run `board.py inbox`)")
    if open_q := s["open_questions"]:
        print("\nOpen questions (answer if you know):")
        for m in open_q[:8]:
            first = m["body"].strip().splitlines()[0][:100]
            print(f"  [{m['id']}] #{m['channel']} {who(m['author_user'], m['author_agent'])}: {first}")
    print("\nChannels: " + ", ".join(f"#{c['name']}" for c in s["channels"]))
    if s["entries"]:
        print(f"\nKnowledge ({len(s['entries'])} entries; `board.py search <words>` or `show <id>`), newest:")
        for e in s["entries"][: args.limit]:
            print("  " + fmt_entry(e))


def cmd_status(args):
    call("POST", "/api/heartbeat", {"status": args.text})
    print(f"status: {args.text or '(cleared)'}")


def cmd_search(args):
    params = {"q": " ".join(args.words), "limit": args.limit}
    if args.kind:
        params["kind"] = args.kind
    if args.tag:
        params["tag"] = args.tag
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
            print(f"{dot} {a['id']:32} {a['branch'] or '-':28} {ago(a['last_seen']):10} {a['status']}")
    out(args, call("GET", "/api/agents"), render)


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

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
