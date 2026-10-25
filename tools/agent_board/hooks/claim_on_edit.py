"""Claude Code PostToolUse hook: claim each file an agent edits, and tell the agent if someone else has it.

Opt in from your own .claude/settings.local.json (see the agent-board skill):

    {"hooks": {"PostToolUse": [{"matcher": "Edit|Write|MultiEdit|NotebookEdit",
      "hooks": [{"type": "command", "command": "python3 tools/agent_board/hooks/claim_on_edit.py"}]}]}}

A file is claimed for 60 minutes and re-claimed at most every 20, so most edits
don't touch the network. Overlaps come back to the agent through exit code 2
(stderr is shown to it); everything else, including the board being down,
stays silent.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE = Path.home() / ".cache" / "agent-board" / "hook-claims"
RECLAIM_SECONDS = 20 * 60


def main():
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return 0
    path = (event.get("tool_input") or {}).get("file_path") or (event.get("tool_input") or {}).get("notebook_path")
    session = event.get("session_id") or ""
    if not path:
        return 0
    CACHE.mkdir(parents=True, exist_ok=True)
    stamp = CACHE / f"{session}.json"
    try:
        seen = json.loads(stamp.read_text())
    except (OSError, ValueError):
        seen = {}
    if time.time() - seen.get(path, 0) < RECLAIM_SECONDS:
        return 0
    env = {**os.environ}
    if session:
        env.setdefault("CLAUDE_CODE_SESSION_ID", session)
    try:
        out = subprocess.run(
            [sys.executable, str(HERE.parent / "board.py"), "--json", "claim", path, "--ttl", "60", "--note", "editing"],
            capture_output=True, text=True, timeout=10, env=env, cwd=event.get("cwd") or None,
        )
        result = json.loads(out.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return 0
    seen[path] = time.time()
    stamp.write_text(json.dumps(seen))
    conflicts = result.get("conflicts") or []
    if not conflicts:
        return 0
    lines = [f"Agent board: {c['wanted']} overlaps {c['path']}, claimed by {c['agent_id']}"
             + (f" ({c['note']})" if c.get("note") else "") for c in conflicts]
    lines.append("Check with them before going further: python3 tools/agent_board/board.py ask \"...\" --to <them>")
    print("\n".join(lines), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
