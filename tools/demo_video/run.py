"""Record the demo video's console takes from .take scripts (#168).

    make demo-video                    # every take in takes/, in name order
    make demo-video TAKES="B2 C"       # takes whose names start with these
    cd engine && uv run python ../tools/demo_video/run.py --rehearse B2   # run it, don't record
    cd engine && uv run python ../tools/demo_video/run.py --check         # parse only

Each take sets up the engine, preps the console off camera, records its
scenes with Recordly (real mouse and keyboard), then adds zooms and exports.
The command language is in README.md. Needs the engine on ENGINE_URL, Vite on
:1420, and Recordly running with "Let agents use the mouse and keyboard" on.
Runs in the engine's env for websockets.
"""

import argparse
import asyncio
import json
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

import websockets

HERE = Path(__file__).resolve().parent
ENGINE_URL = os.environ.get("ENGINE_URL", f"ws://{os.environ.get('ENGINE_HOST', 'localhost')}:{os.environ.get('ENGINE_PORT', '8765')}")
CONSOLE_URL = os.environ.get("DEMO_CONSOLE_URL", "http://localhost:1420/?view=console&demo=1")
OUT_DIR = Path(os.environ.get("DEMO_OUT_DIR", "~/Movies/fireline-demo")).expanduser()
WINDOW_TITLE = "Fireline"
TITLEBAR_PT = 28  # a Chrome app window's title bar, cropped out of the video
# The frame around the window: dark, a little padding, barely rounded.
LOOK = {"wallpaper": "#0e1113", "padding": 6, "borderRadius": 1.5, "shadowIntensity": 0.5}
# No motion blur on zooms (it smears the map's text), and a smaller cursor so
# it covers less of what it points at.
MOTION = {"zoomMotionBlur": 0, "cursorSize": 2.0}
# A label's plate (the sim-speed badge): top right of the frame, in percent.
LABEL_AT, LABEL_SIZE, LABEL_PLATE, LABEL_FONT = (79.0, 4.0), (18.0, 5.5), "#0e1113", 26


class TakeError(Exception):
    pass


# --- Recordly (MCP over HTTP) -------------------------------------------------


class Recordly:
    """A minimal MCP client for Recordly's local HTTP server. The URL and
    token come from RECORDLY_MCP_URL / RECORDLY_MCP_TOKEN, or else from the
    recordly entry Claude Code keeps in ~/.claude.json."""

    def __init__(self) -> None:
        url, token = os.environ.get("RECORDLY_MCP_URL"), os.environ.get("RECORDLY_MCP_TOKEN")
        if not url:
            try:
                cfg = json.loads(Path("~/.claude.json").expanduser().read_text())["mcpServers"]["recordly"]
            except (OSError, KeyError, ValueError):
                raise TakeError("No Recordly server: set RECORDLY_MCP_URL and RECORDLY_MCP_TOKEN") from None
            url = cfg["url"]
            token = cfg.get("headers", {}).get("Authorization", "").removeprefix("Bearer ")
        self.url, self.token, self.session, self.seq = url, token, None, 0
        self._rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "fireline-demo", "version": "1"}})
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def _post(self, body: dict) -> dict | None:
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        try:
            resp = urllib.request.urlopen(urllib.request.Request(self.url, json.dumps(body).encode(), headers), timeout=600)
        except OSError as e:
            raise TakeError(f"Can't reach Recordly at {self.url} ({e}). Is the app open?") from None
        self.session = resp.headers.get("Mcp-Session-Id") or self.session
        raw = resp.read().decode()
        if "id" not in body:
            return None
        # Either a JSON body or an SSE stream of data: lines; take our answer.
        chunks = [raw] if resp.headers.get_content_type() == "application/json" else [l[5:] for l in raw.splitlines() if l.startswith("data:")]
        for c in chunks:
            msg = json.loads(c)
            if msg.get("id") == body["id"]:
                if "error" in msg:
                    raise TakeError(f"Recordly: {msg['error'].get('message')}")
                return msg["result"]
        raise TakeError("Recordly sent no answer")

    def _rpc(self, method: str, params: dict) -> dict:
        self.seq += 1
        return self._post({"jsonrpc": "2.0", "id": self.seq, "method": method, "params": params})

    def call(self, tool: str, **args):
        res = self._rpc("tools/call", {"name": tool, "arguments": args})
        text = "".join(c.get("text", "") for c in res.get("content", []) if c.get("type") == "text")
        if res.get("isError"):
            raise TakeError(f"{tool}: {text}")
        try:
            return json.loads(text)
        except ValueError:
            return text

    def perform(self, steps: list[dict], pace: str) -> None:
        if not steps:
            return
        res = self.call("perform", steps=steps, pace=pace)
        # Past a minute perform answers early and the steps carry on.
        if isinstance(res, dict) and res.get("status") == "still-running":
            while (self.call("get_status").get("input") or {}).get("running"):
                time.sleep(1)


# --- Engine -------------------------------------------------------------------


async def _engine(msgs: list[dict], until=None, timeout: float = 120) -> dict:
    """Send messages to the engine, then (optionally) wait for until(state).
    A fresh connection each time, so a long Recordly call can't time it out."""
    state: dict = {}
    async with websockets.connect(ENGINE_URL, origin="http://localhost:1420", max_size=None) as ws:
        async def read(seconds: float):
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                try:
                    m = await asyncio.wait_for(ws.recv(), max(0.05, end - time.monotonic()))
                except asyncio.TimeoutError:
                    return
                if isinstance(m, str):
                    d = json.loads(m)
                    state[d["type"]] = d
                    if until and until(state):
                        return True

        await read(1.0)  # the connect snapshot: tokens, score, scenario_state
        for m in msgs(state) if callable(msgs) else msgs:
            await ws.send(json.dumps(m))
            await asyncio.sleep(0.15)
        if until and not await read(timeout):
            raise TakeError("engine: timed out waiting")
    return state


def engine(args: list[str]) -> None:
    cmd, rest = args[0], args[1:]
    if cmd == "fresh":
        # A clean round: no tokens left from the last take, the clock at 0.
        speed = float(rest[0]) if rest else 1.0

        def msgs(state):
            out = [{"type": "virtual_token_remove", "id": t["id"]} for t in state.get("tokens", {}).get("tokens", [])]
            out += [{"type": "reset"}, {"type": "set_speed", "speed": speed}, {"type": "start_round"}]
            if "paused" in rest:
                out.append({"type": "set_running", "running": False})
            return out

        asyncio.run(_engine(msgs))
    elif cmd == "advance":
        # Run the fire this many sim-minutes, then pause.
        minutes = float(rest[0])
        start = asyncio.run(_engine([]))["score"]["elapsed_min"]
        asyncio.run(_engine([{"type": "set_running", "running": True}], until=lambda s: s.get("score", {}).get("elapsed_min", 0) >= start + minutes))
        asyncio.run(_engine([{"type": "set_running", "running": False}]))
    elif cmd == "speed":
        asyncio.run(_engine([{"type": "set_speed", "speed": float(rest[0])}]))
    elif cmd in ("pause", "resume"):
        asyncio.run(_engine([{"type": "set_running", "running": cmd == "resume"}]))
    elif cmd == "send":
        asyncio.run(_engine([json.loads(" ".join(rest))]))
    else:
        raise TakeError(f"unknown engine command: {cmd}")


# --- Take scripts ---------------------------------------------------------------


@dataclass
class Block:
    kind: str  # "prep" or "scene"
    title: str
    pace: str
    items: list = field(default_factory=list)  # step dicts, or ("engine", args)


@dataclass
class Take:
    name: str
    setup: list = field(default_factory=list)  # engine commands before the first block
    blocks: list[Block] = field(default_factory=list)
    zooms: list[dict] = field(default_factory=list)
    labels: list[dict] = field(default_factory=list)
    captions: list[dict] = field(default_factory=list)
    cards: list[dict] = field(default_factory=list)
    trim: tuple[str, str] | None = None
    export: str | None = None

    @property
    def scenes(self) -> list[str]:
        return [b.title for b in self.blocks if b.kind == "scene"]


def opts(tokens: list[str]) -> tuple[list[str], dict]:
    pos, kw = [], {}
    for t in tokens:
        if re.fullmatch(r"[a-z]+=.*", t):
            k, v = t.split("=", 1)
            kw[k] = v
        else:
            pos.append(t)
    return pos, kw


def target(text: str, kw: dict) -> dict:
    t = {"text": text}
    if "role" in kw:
        t["role"] = kw["role"]
    if "index" in kw:
        t["index"] = int(kw["index"])
    return t


def point_or_target(arg: str, kw: dict) -> dict:
    m = re.fullmatch(r"(\d+(?:\.\d+)?),(\d+(?:\.\d+)?)", arg)
    return {"x": float(m[1]), "y": float(m[2])} if m else {"target": target(arg, kw)}


def step(cmd: str, rest: list[str]) -> dict:
    pos, kw = opts(rest)
    ms = lambda s: int(float(s) * 1000)
    if cmd in ("click", "move"):
        s = {"action": cmd, **point_or_target(pos[0], kw)}
        if "ms" in kw:
            s["durationMs"] = int(kw["ms"])
        return s
    if cmd == "key":
        s = {"action": "key", "key": pos[0]}
        if len(pos) > 1:  # key right x9
            s["repeat"] = int(pos[1].lstrip("x"))
        if "mods" in kw:
            s["modifiers"] = kw["mods"].split("+")
        return s
    if cmd == "type":
        s = {"action": "type", "text": pos[0].replace("\\n", "\n")}
        if "into" in kw:
            s["into"] = {"text": kw["into"]}
        return s
    if cmd in ("hold", "wait"):
        return {"action": cmd, "ms": ms(pos[0])}
    if cmd == "waitfor":
        s = {"action": "waitFor", "timeoutMs": ms(kw.get("timeout", "10"))}
        if pos[0] == "settled":
            s.update(settled=True, quietMs=ms(kw.get("quiet", "0.4")))
        else:
            s["text"] = pos[0]
            if "gone" in pos[1:]:
                s["gone"] = True
        return s
    raise TakeError(f"unknown step: {cmd}")


def parse(path: Path) -> Take:
    take = Take(name=path.stem)
    block: Block | None = None
    for n, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip() or line.strip().startswith("#"):
            continue
        try:
            words = shlex.split(line, comments=True)
            cmd, rest = words[0], words[1:]
            pos, kw = opts(rest)
            if cmd == "engine":
                (block.items if block else take.setup).append(("engine", rest))
            elif cmd in ("prep", "scene"):
                block = Block(cmd, pos[0] if pos else "", kw.get("pace", "brisk" if cmd == "prep" else "relaxed"))
                take.blocks.append(block)
            elif cmd == "zoom":
                start, end = pos[0].split("..")
                at = [float(v) for v in kw.get("at", "0.5,0.5").split(",")]
                take.zooms.append({"start": start, "end": end, "depth": int(kw.get("depth", 2)), "focus": {"cx": at[0], "cy": at[1]}})
                block = None
            elif cmd in ("label", "caption"):
                start, end = pos[1].split("..")
                item = {"text": pos[0], "start": start, "end": end}
                if cmd == "label" and "at" in kw:
                    item["at"] = [float(v) for v in kw["at"].split(",")]
                (take.labels if cmd == "label" else take.captions).append(item)
                block = None
            elif cmd == "card":
                take.cards.append({"op": pos[0], "text": pos[1], "subtitle": kw.get("sub", ""), "ms": int(float(kw.get("ms", "2.5")) * 1000)})
                block = None
            elif cmd == "trim":
                start, end = pos[0].split("..")
                take.trim, block = (start, end), None
            elif cmd == "export":
                take.export, block = pos[0], None
            elif block is None:
                raise TakeError("a step outside prep or scene")
            else:
                block.items.append(step(cmd, rest))
        except (TakeError, IndexError, ValueError) as e:
            raise TakeError(f"{path.name}:{n}: {e}") from None
    if not take.scenes:
        raise TakeError(f"{path.name}: no scene to record")
    return take


def resolve(t: str, scenes: list[dict], duration: float) -> float:
    """A time in ms on the recording: 0, end, or <scene>@<seconds> (scenes from
    1; @end and @end-2 count from that scene's end)."""
    if t == "0":
        return 0.0
    if t == "end":
        return duration
    m = re.fullmatch(r"(\d+)@(end)?([+-]?\d*(?:\.\d+)?)", t)
    if not m:
        raise TakeError(f"bad time {t!r}: use 0, end or <scene>@<seconds>")
    sc = scenes[int(m[1]) - 1]
    base = sc["endMs"] if m[2] else sc["startMs"]
    return min(duration, max(0.0, base + float(m[3] or 0) * 1000))


# --- Running a take -------------------------------------------------------------


def find_window(rec: Recordly) -> tuple[dict, dict]:
    def look():
        sources = rec.call("list_sources")
        wins = [s for s in sources if s.get("type") == "window" and s.get("appName") == "Google Chrome" and s.get("windowTitle") == WINDOW_TITLE]
        return sources, wins

    sources, wins = look()
    if not wins:
        # The console as a Chrome app window: no tabs or address bar on camera.
        subprocess.run(["open", "-na", "Google Chrome", "--args", f"--app={CONSOLE_URL}"], check=True)
        time.sleep(4)
        sources, wins = look()
    if not wins:
        raise TakeError(f"No Chrome window titled {WINDOW_TITLE!r}; open {CONSOLE_URL} as an app window")
    win = wins[0]
    screens = [s for s in sources if s.get("type") == "screen"]
    screen = next((s for s in screens if s["x"] <= win["x"] < s["x"] + s["width"] and s["y"] <= win["y"] < s["y"] + s["height"]), screens[0])
    return win, screen


def run_items(rec: Recordly, block: Block) -> None:
    steps: list[dict] = []
    for item in block.items:
        if isinstance(item, tuple):
            rec.perform(steps, block.pace)
            steps = []
            engine(item[1])
        else:
            steps.append(item)
    rec.perform(steps, block.pace)


def editor_ready(rec: Recordly, video: str) -> dict:
    for _ in range(30):
        try:
            st = rec.call("get_editor_state", include=["clips", "zooms", "captions", "scenes"], clips="summary")
            if st.get("videoPath") == video:
                return st
        except TakeError:
            pass
        time.sleep(1)
    raise TakeError("the Recordly editor didn't load the recording")


def run_take(rec: Recordly, take: Take, rehearse: bool, out_dir: Path) -> None:
    print(f"== {take.name}")
    win, screen = find_window(rec)
    # Record the whole screen and drive the window; recording a Chrome window
    # directly loses track of it.
    rec.call("select_source", id=screen["id"])
    rec.call("select_source", id=win["id"])
    for item in take.setup:
        engine(item[1])

    recording = False
    try:
        for block in take.blocks:
            if block.kind == "scene" and not recording and not rehearse:
                rec.call("start_recording", countdownSeconds=0, scenes=take.scenes)
                recording = True
            print(f"   {block.kind}: {block.title}" if block.title else f"   {block.kind}")
            run_items(rec, block)
    except TakeError:
        if recording:
            rec.call("cancel_recording")
        raise
    if rehearse:
        return

    video = rec.call("stop_recording")["videoPath"]
    st = editor_ready(rec, video)
    # Recordly cuts idle stretches and adds click zooms and scene captions on
    # load. Our footage is mostly the fire moving, so keep it whole and add
    # only the zooms the take asks for.
    for _ in range(3):
        if not st["zooms"] and not st["captions"] and st["clips"]["count"] == 1 and st["durationMs"] == st["sourceDurationMs"]:
            break
        rec.call("history", op="undo")
        st = editor_ready(rec, video)

    sw, sh = screen["width"], screen["height"]
    x, y = win["x"] - screen["x"], win["y"] - screen["y"] + TITLEBAR_PT
    crop = {"x": x / sw, "y": y / sh, "width": min(win["width"], sw - x) / sw, "height": min(win["height"] - TITLEBAR_PT, sh - y) / sh}
    rec.call("set_look", op="set", fields={**LOOK, "crop": crop})
    rec.call("set_look", op="motion", fields=MOTION)

    # Trim first, then place everything on the trimmed timeline's scene times.
    if take.trim:
        scenes, dur = st["scenes"], st["durationMs"]
        rec.call("edit_timeline", op="trim", clipIndex=0, startMs=resolve(take.trim[0], scenes, dur), endMs=resolve(take.trim[1], scenes, dur))
        st = editor_ready(rec, video)
    scenes, dur = st["scenes"], st["durationMs"]
    span = lambda it: (resolve(it["start"], scenes, dur), resolve(it["end"], scenes, dur))
    for z in take.zooms:
        a, b = span(z)
        rec.call("edit_zoom", op="add", startMs=a, endMs=b, depth=z["depth"], focus=z["focus"])
    for lb in take.labels:
        # Pinned to the output frame, so a zoom can't crop it.
        a, b = span(lb)
        x, y = lb.get("at", LABEL_AT)
        rec.call("annotate", op="add", kind="text", text=lb["text"], startMs=a, endMs=b, x=x, y=y, width=LABEL_SIZE[0], height=LABEL_SIZE[1],
                 space="screen", backgroundColor=LABEL_PLATE, color="#ffffff", fontSize=LABEL_FONT, textAlign="center")
    if take.captions:
        rec.call("edit_captions", op="set", cues=[{"startMs": a, "endMs": b, "text": c["text"]} for c in take.captions for a, b in [span(c)]])
    # Cards add time, so they go last.
    for c in take.cards:
        rec.call("add_card", op=c["op"], text=c["text"], subtitle=c["subtitle"], durationMs=c["ms"], background="#0e1113")
    check = rec.call("check_edits")
    for p in check.get("problems", []) if isinstance(check, dict) else []:
        print(f"   check: {p.get('severity')}: {p.get('message')}")

    out_dir.mkdir(parents=True, exist_ok=True)
    path = str(out_dir / (take.export or f"{take.name}.mp4"))
    out = rec.call("export_video", outputPath=path, quality="high", overwrite=True)
    if isinstance(out, dict) and out.get("status") == "still-exporting":
        while (export := rec.call("get_status").get("export") or {}).get("state") not in ("done", "failed", "idle"):
            time.sleep(2)
        if export.get("state") == "failed":
            raise TakeError(f"export failed: {export.get('error')}")
    print(f"   -> {path}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("takes", nargs="*", help="take name prefixes (default: all)")
    ap.add_argument("--rehearse", action="store_true", help="run the takes without recording")
    ap.add_argument("--check", action="store_true", help="parse the takes and print them")
    ap.add_argument("--out", type=Path, default=OUT_DIR, help=f"export folder (default {OUT_DIR})")
    a = ap.parse_args()

    files = sorted((HERE / "takes").glob("*.take"))
    if a.takes:
        files = [f for f in files if any(f.stem.startswith(p) for p in a.takes)]
    if not files:
        print("no takes match", file=sys.stderr)
        return 1
    try:
        takes = [parse(f) for f in files]
        if a.check:
            for t in takes:
                print(f"{t.name}: {len(t.scenes)} scene(s), {len(t.zooms)} zoom(s) -> {t.export}")
            return 0
        rec = Recordly()
        for t in takes:
            run_take(rec, t, a.rehearse, a.out)
    except TakeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
