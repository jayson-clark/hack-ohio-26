"""Stitch the prompter's per-line voiceover takes into one 3:00 track.

    python3 tools/demo_video/stitch_vo.py [CLIPS_DIR] [-o OUT.m4a] [--pad-tail]

The prompter (prompter.html, record mode) records one audio clip per read-along
line and saves them as vo_<index>_<start>.webm next to a manifest.json. This
places each clip at its line's start time on SCRIPT.md's clock and pads the gaps
between lines with silence, so the result lines up with the burned-in captions
in the rough cut and runs exactly as long as the script (3:00).

CLIPS_DIR defaults to ~/Downloads (where the browser drops the clips). It reads
manifest.json if present (authoritative cue times); otherwise it falls back to
SCRIPT.md and the vo_<index>_<start>.<ext> filenames. A take that runs past its
line's window would overlap the next line: we warn and (by default) hard-trim it
to its slot. Pass --no-trim to let it run long instead (it can then push the
total past 3:00). Needs ffmpeg on PATH (brew install ffmpeg).
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SR = 48000  # output sample rate


def parse_script_cues() -> list[dict]:
    """Fallback cue list from SCRIPT.md's Read-along table."""
    md = (HERE / "SCRIPT.md").read_text()
    part = md.split("## Read-along")[1].split("\n## ")[0]
    cues = []
    for line in part.splitlines():
        if not re.match(r"\|\s*\d+:\d\d", line):
            continue
        c = [x.strip().replace("`", "") for x in line.strip("|").split("|")]
        t = lambda s: int(s.split(":")[0]) * 60 + int(s.split(":")[1])
        cues.append({"start": t(c[0]), "end": t(c[1]), "line": c[3]})
    return cues


def load_plan(clips_dir: Path) -> tuple[list[dict], float]:
    """Return (clips, total). Each clip: {index, path, start, end, line}."""
    manifest = clips_dir / "manifest.json"
    if manifest.exists():
        data = json.loads(manifest.read_text())
        total = float(data["total"])
        out = []
        for c in data["clips"]:
            p = clips_dir / c["file"]
            if not p.exists():
                print(f"  ! missing clip for line {c['index']}: {p.name}", file=sys.stderr)
                continue
            out.append({"index": c["index"], "path": p, "start": float(c["start"]), "end": float(c["end"]), "line": c.get("line", "")})
        return out, total

    # No manifest: match vo_<index>_<start>.<ext> against SCRIPT.md.
    cues = parse_script_cues()
    total = cues[-1]["end"] if cues else 180.0
    out = []
    for p in sorted(clips_dir.glob("vo_*.*")):
        m = re.match(r"vo_(\d+)_\d+\.", p.name)
        if not m:
            continue
        i = int(m.group(1))
        if i >= len(cues):
            print(f"  ! {p.name}: line {i} is past the script", file=sys.stderr)
            continue
        out.append({"index": i, "path": p, "start": cues[i]["start"], "end": cues[i]["end"], "line": cues[i]["line"]})
    out.sort(key=lambda c: c["index"])
    return out, float(total)


def duration(path: Path) -> float:
    """Seconds, via ffprobe."""
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def build(clips: list[dict], total: float, out: Path, trim: bool, pad_tail: bool) -> None:
    if not clips:
        sys.exit("No clips found. Record lines in the prompter and Save clips first.")

    # One ffmpeg call: each clip is an input, delayed to its start with adelay,
    # then all are mixed over a silent 'total'-second base. amix keeps them
    # aligned; the base fixes the length so gaps stay silent and the tail holds.
    inputs, filters, labels = [], [], []
    inputs += ["-f", "lavfi", "-t", f"{total:.3f}", "-i", f"anullsrc=r={SR}:cl=mono"]
    overruns = []
    for n, c in enumerate(clips):  # input indices 1..N (0 is the silent base)
        inputs += ["-i", str(c["path"])]
        slot = c["end"] - c["start"]
        dur = duration(c["path"])
        if dur > slot + 0.05:
            overruns.append((c["index"], dur, slot))
        delay_ms = int(round(c["start"] * 1000))
        chain = f"[{n + 1}:a]aresample={SR},aformat=channel_layouts=mono"
        if trim:
            chain += f",atrim=0:{slot:.3f}"
        chain += f",adelay={delay_ms}|{delay_ms}[d{n}]"
        filters.append(chain)
        labels.append(f"[d{n}]")

    base = f"[0:a]aresample={SR},aformat=channel_layouts=mono[base]"
    mix = f"[base]{''.join(labels)}amix=inputs={len(labels) + 1}:normalize=0:duration=longest[mixed]"
    tail = ""
    outlabel = "[mixed]"
    if not pad_tail:
        # amix duration=longest already holds to the base's length; apad+atrim
        # guarantees an exact total even if the base is a hair short.
        tail = f"[mixed]apad,atrim=0:{total:.3f}[out]"
        outlabel = "[out]"

    graph = ";".join([base, *filters, mix] + ([tail] if tail else []))
    codec = ["-c:a", "aac", "-b:a", "192k"] if out.suffix.lower() in (".m4a", ".mp4", ".aac") else []
    cmd = ["ffmpeg", "-y", *inputs, "-filter_complex", graph, "-map", outlabel, *codec, str(out)]

    print(f"Placing {len(clips)} line takes on a {total:.0f}s timeline -> {out}")
    for c in clips:
        print(f"  line {c['index']:>2}  @{c['start']:>5.1f}s  {c['line'][:56]}")
    if overruns:
        print("\n  Overran their slot (re-record for a tighter read, or --no-trim to keep):", file=sys.stderr)
        for i, dur, slot in overruns:
            print(f"    line {i}: take {dur:.1f}s > slot {slot:.1f}s", file=sys.stderr)

    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("ffmpeg failed:\n" + r.stderr[-2000:])
    got = duration(out)
    print(f"\nWrote {out} ({got:.1f}s). Mux it into the cut: "
          f"ffmpeg -i rough.mp4 -i {out.name} -c:v copy -map 0:v -map 1:a -shortest final.mp4")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("clips_dir", nargs="?", default="~/Downloads", help="folder with the vo_*.webm clips + manifest.json")
    ap.add_argument("-o", "--out", default=str(Path("~/Movies/fireline-demo/fireline-vo.m4a")), help="output audio file")
    ap.add_argument("--no-trim", dest="trim", action="store_false", help="let overrunning takes run long instead of trimming to the slot")
    ap.add_argument("--pad-tail", action="store_true", help="don't force the exact total length (debug)")
    a = ap.parse_args()

    for tool in ("ffmpeg", "ffprobe"):
        if subprocess.run(["which", tool], capture_output=True).returncode != 0:
            sys.exit(f"{tool} not found. brew install ffmpeg")

    clips_dir = Path(a.clips_dir).expanduser()
    out = Path(a.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    clips, total = load_plan(clips_dir)
    build(clips, total, out, a.trim, a.pad_tail)


if __name__ == "__main__":
    main()
