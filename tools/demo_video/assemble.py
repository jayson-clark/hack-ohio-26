"""Cut the demo video together on SCRIPT.md's clock: a rough cut to record
the voiceover against and fix in post.

    cd engine && uv run --with pillow python ../tools/demo_video/assemble.py [OUT.mp4] [--no-captions]

Each read-along row's slot is filled from the shot in SHOTS below (a take
export, the synced split, the phone or a card) starting at its in-point, and
runs until the next row starts, so the breaths between lines keep a picture.
The line itself is burned in as a caption (judges often watch muted), and
the opening gets the Fireline lower third. Silent: mux the voiceover in once
it's recorded. Footage is read from DEMO_OUT_DIR (~/Movies/fireline-demo).
"""

import os
import re
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
FOOTAGE = Path(os.environ.get("DEMO_OUT_DIR", "~/Movies/fireline-demo")).expanduser()
W, H, FPS = 1920, 1080, 30
FONT = "/System/Library/Fonts/SFNS.ttf"
FADE_S = 0.25  # a short dip between different sources, not between rows of one shot

# Row start ("m:ss") -> (file in FOOTAGE or an absolute path, in-point
# seconds, crop as x,y,w,h fractions or None). For a card the in-point is how
# far into its slow push-in to start, so rows on one card don't jump. In-points
# are picked from contact sheets of each export; re-pick them after re-recording.
PHONE = os.environ.get("DEMO_PHONE", str(Path("~/Downloads/IMG_0780.MOV").expanduser()))
PHONE_WIDE = (0.03, 0.2, 0.8, 0.8)  # the rig and the print, without the projector top or the room's right side
SHOTS: dict[str, tuple[str, float, tuple[float, float, float, float] | None]] = {
    "0:00": ("A-see-it.mp4", 0, None),             # wide: the fire leaving Pulga
    "0:08": ("A-see-it.mp4", 8, None),             # the fire and its bands
    "0:18": ("A-see-it.mp4", 18, None),            # bands growing, Paradise's clock
    "0:29": ("cards/card-replay.png", 0, None),
    "0:37": ("cards/card-replay.png", 8, None),
    "0:44": ("cards/card-replay.png", 15, None),
    "0:52": ("B1-order-evacuation.mp4", 2, None),  # the queue's cards, 17 of 32
    "1:02": ("B2-dispatch-crew.mp4", 3, None),     # the crew card
    "1:11": ("G-calibration-wind-shift.mp4", 2, None),   # Concow's range, then the legend
    "1:22": ("G-calibration-wind-shift.mp4", 13, None),  # the shift arrives
    "1:32": ("G-calibration-wind-shift.mp4", 23, None),  # misses jump, Widening
    "1:41": ("cards/card-limits.png", 0, None),
    "1:51": ("cards/card-limits.png", 10, None),
    "2:01": ("B1-order-evacuation.mp4", 5, None),  # Order evacuation, the re-sort
    "2:10": ("B2-dispatch-crew.mp4", 13, None),    # Dispatch, the drive-in
    "2:17": (PHONE, 40, PHONE_WIDE),               # the table, wide
    "2:26": ("F-split-synced.mp4", 4, None),       # the table beside the camera view
    "2:34": ("F-table-camera.mp4", 26, None),      # overlays on the photo, then the console
    "2:44": ("agent-board.mp4", 0, (0.06, 0.06, 0.88, 0.88)),  # the board, live, a little closer
    "2:55": ("cards/card-end.png", 0, None),
}
GRADED = {PHONE}  # sources that get split.py's grade (the washed-out phone)


def load_rows() -> list[dict]:
    md = (HERE / "SCRIPT.md").read_text()
    part = md.split("## Read-along")[1].split("\n## ")[0]
    rows = []
    for line in part.splitlines():
        if not re.match(r"\|\s*\d+:\d\d", line):
            continue
        c = [x.strip().replace("`", "") for x in line.strip("|").split("|")]
        t = lambda s: int(s.split(":")[0]) * 60 + int(s.split(":")[1])
        rows.append({"start": t(c[0]), "end": t(c[1]), "picture": c[2], "line": c[3], "onscreen": c[4]})
    return rows


class Source:
    """Frames from a video (read forward from one seek) or a still card."""

    def __init__(self, path: Path, t0: float):
        self.still, self.luts = None, None
        if path.suffix.lower() in (".png", ".jpg"):
            self.still, self.t0 = cv2.imread(str(path)), t0
            return
        if str(path) in GRADED:
            from split import grade_luts
            ref = cv2.VideoCapture(str(path))
            ref.set(cv2.CAP_PROP_POS_MSEC, t0 * 1000)
            self.luts = grade_luts(ref.read()[1])
        self.cap = cv2.VideoCapture(str(path))
        if not self.cap.isOpened():
            raise SystemExit(f"can't open {path}")
        self.fps = self.cap.get(cv2.CAP_PROP_FPS)
        self.cap.set(cv2.CAP_PROP_POS_MSEC, t0 * 1000)
        self.t0, self.i, self.f = t0, 0, None

    def at(self, dt: float) -> np.ndarray:
        if self.still is not None:
            # A slow push-in, so a card doesn't sit dead still.
            s = 1 + 0.03 * min((self.t0 + dt) / 25, 1)
            h, w = self.still.shape[:2]
            cw, ch = int(w / s), int(h / s)
            x, y = (w - cw) // 2, (h - ch) // 2
            return self.still[y:y + ch, x:x + cw]
        want = int(dt * self.fps)
        while self.i <= want or self.f is None:
            ok, f = self.cap.read()
            if not ok:
                break
            self.f, self.i = f, self.i + 1
        if self.luts:
            from split import grade
            return grade(self.f, self.luts)
        return self.f


def fit(img: np.ndarray, crop) -> np.ndarray:
    if crop:
        h, w = img.shape[:2]
        x, y, cw, ch = crop
        img = img[int(y * h):int((y + ch) * h), int(x * w):int((x + cw) * w)]
    s = max(W / img.shape[1], H / img.shape[0])
    big = cv2.resize(img, (round(img.shape[1] * s), round(img.shape[0] * s)), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC)
    y, x = (big.shape[0] - H) // 2, (big.shape[1] - W) // 2
    return big[y:y + H, x:x + W]


def overlay(text: str, kind: str) -> tuple[np.ndarray, np.ndarray]:
    """A caption (bottom centre) or lower third (bottom left), as BGR + alpha."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    size = 34 if kind == "caption" else 40
    font = ImageFont.truetype(FONT, size)
    if kind == "caption":
        # Wrap to two lines at most.
        words, lines, cur = text.split(), [], ""
        for w in words:
            if d.textlength(f"{cur} {w}".strip(), font=font) > 1500 and cur:
                lines.append(cur)
                cur = w
            else:
                cur = f"{cur} {w}".strip()
        lines.append(cur)
        y = H - 70 - len(lines) * (size + 14)
        for ln in lines:
            tw = d.textlength(ln, font=font)
            d.rounded_rectangle(((W - tw) / 2 - 18, y - 8, (W + tw) / 2 + 18, y + size + 10), 10, fill=(14, 17, 19, 215))
            d.text(((W - tw) / 2, y), ln, font=font, fill=(255, 255, 255, 255))
            y += size + 14
    else:
        tw = d.textlength(text, font=font)
        top = H - 290  # clear of the captions below it
        d.rounded_rectangle((70, top, 70 + tw + 56, top + size + 34), 12, fill=(14, 17, 19, 225))
        d.rectangle((70, top, 76, top + size + 34), fill=(255, 140, 60, 255))
        d.text((98, top + 15), text, font=font, fill=(255, 255, 255, 255))
    a = np.asarray(img).astype(np.float32)
    return a[..., 2::-1].copy(), a[..., 3:] / 255


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    captions = "--no-captions" not in sys.argv
    out_path = Path(args[0] if args else FOOTAGE / "fireline-demo-rough.mp4").expanduser()
    rows = load_rows()
    missing = [r["start"] for r in rows if f"{r['start'] // 60}:{r['start'] % 60:02d}" not in SHOTS]
    if missing:
        raise SystemExit(f"no shot for rows starting at {missing}; add them to SHOTS")
    total = rows[-1]["end"]
    out = cv2.VideoWriter(str(out_path), cv2.VideoWriter_fourcc(*"avc1"), FPS, (W, H))
    for k, r in enumerate(rows):
        key = f"{r['start'] // 60}:{r['start'] % 60:02d}"
        name, t_in, crop = SHOTS[key]
        until = rows[k + 1]["start"] if k + 1 < len(rows) else total
        src = Source(FOOTAGE / name if not Path(name).is_absolute() else Path(name), t_in)
        new_source = k == 0 or SHOTS[f"{rows[k - 1]['start'] // 60}:{rows[k - 1]['start'] % 60:02d}"][0] != name
        # A card that already says the line doesn't need it again underneath.
        cap = overlay(r["line"], "caption") if captions and "card-end" not in name else None
        lower = overlay("Fireline · decision support for wildfire incident command", "lower") if k == 0 else None
        n = int((until - r["start"]) * FPS)
        for i in range(n):
            dt = i / FPS
            frame = fit(src.at(dt), crop).astype(np.float32)
            t_row = r["start"] + dt
            if cap and t_row < r["end"]:
                frame = frame * (1 - cap[1]) + cap[0] * cap[1]
            if lower and dt < 6:
                a = lower[1] * min(1, dt / 0.5, (6 - dt) / 0.5)
                frame = frame * (1 - a) + lower[0] * a
            if new_source and dt < FADE_S:
                frame *= dt / FADE_S
            out.write(frame.clip(0, 255).astype(np.uint8))
        print(f"{key}  {name} @ {t_in:.1f}s  ({until - r['start']} s)")
    out.release()
    print(f"wrote {out_path}: {total // 60}:{total % 60:02d}")


if __name__ == "__main__":
    main()
