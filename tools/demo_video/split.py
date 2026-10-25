"""The synced table shot: the phone's view of the table (left) beside the
camera view (right), framed like the other takes (SCRIPT.md, "The synced
table shot").

    cd engine && uv run --with pillow python ../tools/demo_video/split.py \
        SCREEN.mp4 PHONE.mov OUT.mp4 --from 6.6 --to 41

SCREEN is take F's raw Recordly recording (in Recordly's recordings folder,
not the export). PHONE is either the phone's own video or Recordly's
`...-webcam.mp4` (add --mirror: Recordly saves it mirrored). The two are lined
up on take F's slate, the test grid's first frame in each, unless --offset
gives the phone's lead in seconds (0 for Recordly's webcam, which shares its
clock). --from and --to are seconds in SCREEN: after the slate, before the
cut to the console.

The crops are for this rig: the camera view in exercise control's 1668x991
Chrome window on a 1728x1117 point screen, and a phone on a tripod in front
of the table. Check a frame and pass --view / --phone-crop if yours differ.
Pillow draws the labels; without it they're left off.
"""

import argparse
from pathlib import Path

import cv2
import numpy as np

OUT_W, OUT_H, FPS = 1920, 1080, 30
WALLPAPER = Path("~/Recordly-mcp/public/wallpapers/sequoia-blue-orange.jpg").expanduser()
FONT = "/System/Library/Fonts/SFNS.ttf"
PANEL_W, GAP, RADIUS = 810, 36, 16  # two 4:3 panels across about 86% of the frame
PANEL_H = round(PANEL_W * 3 / 4)
PLATE = (19, 17, 14)  # the takes' label plate, #0e1113, in BGR


def rect(s: str) -> tuple[int, int, int, int]:
    x, y, w, h = (int(v) for v in s.split(","))
    return x, y, w, h


def cyan(img: np.ndarray) -> float:
    """How cyan the picture is on average: the test grid's colour. A mean, not
    a count of very cyan pixels, so a washed-out projection on the phone
    still registers."""
    v = cv2.resize(img, (320, round(320 * img.shape[0] / img.shape[1]))).astype(np.float32)
    return float(((v[..., 0] + v[..., 1]) / 2 - v[..., 2]).mean())


def flash_onset(path: str, crop: tuple[int, int, int, int], within_s: float, mirror: bool = False) -> float:
    """Time of the biggest jump in cyan inside crop: the test grid coming on."""
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    x, y, w, h = crop
    prev, best, best_t = None, 0.0, None
    for i in range(int(fps * within_s)):
        ok, f = cap.read()
        if not ok:
            break
        if mirror:
            f = cv2.flip(f, 1)
        c = cyan(f[y:y + h, x:x + w])
        if prev is not None and c - prev > best:
            best, best_t = c - prev, i / fps
        prev = c
    if best_t is None or best < 2:
        raise SystemExit(f"{path}: no test-grid flash in the first {within_s:.0f} s; pass --offset")
    return best_t


class Reader:
    """Frames by time, reading forward only (seeking these files is slow)."""

    def __init__(self, path: str, mirror: bool = False):
        self.cap = cv2.VideoCapture(path)
        self.fps = self.cap.get(cv2.CAP_PROP_FPS)
        self.mirror, self.i, self.f = mirror, 0, None

    def at(self, t: float) -> np.ndarray:
        want = max(0, int(t * self.fps))
        while self.i <= want or self.f is None:
            ok, f = self.cap.read()
            if not ok:
                break
            self.f = cv2.flip(f, 1) if self.mirror else f
            self.i += 1
        return self.f


def cover(img: np.ndarray, w: int, h: int) -> np.ndarray:
    """Scale to fill w x h, cropping the overflow from the centre."""
    s = max(w / img.shape[1], h / img.shape[0])
    big = cv2.resize(img, (round(img.shape[1] * s), round(img.shape[0] * s)), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC)
    y, x = (big.shape[0] - h) // 2, (big.shape[1] - w) // 2
    return big[y:y + h, x:x + w]


def rounded_mask(w: int, h: int, r: int) -> np.ndarray:
    m = np.zeros((h, w), np.uint8)
    cv2.rectangle(m, (r, 0), (w - r - 1, h - 1), 255, -1)
    cv2.rectangle(m, (0, r), (w - 1, h - r - 1), 255, -1)
    for cx, cy in ((r, r), (w - r - 1, r), (r, h - r - 1), (w - r - 1, h - r - 1)):
        cv2.circle(m, (cx, cy), r, 255, -1, cv2.LINE_AA)
    return (m.astype(np.float32) / 255)[..., None]


def text_layer(items: list[tuple[str, int, int, int]]) -> tuple[np.ndarray, np.ndarray] | None:
    """Labels on plates, as a BGR image and its alpha: (text, centre x, top y, size).
    None without Pillow."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("Pillow isn't installed, so no labels (uv run --with pillow ...)")
        return None
    img = Image.new("RGBA", (OUT_W, OUT_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for text, x, y, size in items:
        font = ImageFont.truetype(FONT, size)
        l, t, r, b = d.textbbox((0, 0), text, font=font)
        w, h = r - l, b - t
        px, py = round(size * 0.6), round(size * 0.4)
        left = x - w // 2 - px
        d.rounded_rectangle((left, y, left + w + 2 * px, y + h + 2 * py), radius=round(size * 0.35), fill=(14, 17, 19, 235))
        d.text((left + px - l, y + py - t), text, font=font, fill=(255, 255, 255, 255))
    a = np.asarray(img).astype(np.float32)
    return a[..., 2::-1].copy(), a[..., 3:] / 255


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("screen")
    ap.add_argument("phone")
    ap.add_argument("out")
    ap.add_argument("--from", dest="t_from", type=float, required=True, help="seconds into SCREEN")
    ap.add_argument("--to", dest="t_to", type=float, required=True)
    ap.add_argument("--offset", type=float, help="seconds the phone runs ahead of SCREEN (default: from the slate)")
    ap.add_argument("--mirror", action="store_true", help="the phone file is mirrored (Recordly's webcam)")
    ap.add_argument("--view", type=rect, default=(376, 380, 2040, 1528), help="camera view in SCREEN: x,y,w,h px")
    ap.add_argument("--phone-crop", type=rect, default=(550, 540, 720, 540), help="4:3 crop of the phone frame: x,y,w,h px")
    ap.add_argument("--speed", default="0.5× · 5 sim-min/s", help="the sim-speed badge; empty for none")
    a = ap.parse_args()

    if a.offset is None:
        s_on = flash_onset(a.screen, a.view, 15)
        p_on = flash_onset(a.phone, a.phone_crop, 90, a.mirror)
        a.offset = p_on - s_on
        print(f"slate: screen {s_on:.3f} s, phone {p_on:.3f} s -> phone leads by {a.offset:.3f} s")

    bg = cover(cv2.imread(str(WALLPAPER)), OUT_W, OUT_H) if WALLPAPER.exists() else np.full((OUT_H, OUT_W, 3), PLATE, np.uint8)
    bg = bg.astype(np.float32)
    x_left = (OUT_W - 2 * PANEL_W - GAP) // 2
    xs = (x_left, x_left + PANEL_W + GAP)
    y0 = (OUT_H - PANEL_H) // 2 - 20
    mask = rounded_mask(PANEL_W, PANEL_H, RADIUS)
    # Soft shadows under both panels, baked into the background.
    shadow = np.zeros((OUT_H, OUT_W), np.float32)
    for x in xs:
        shadow[y0 + 10:y0 + 10 + PANEL_H, x:x + PANEL_W] = mask[..., 0]
    bg = bg * (1 - cv2.GaussianBlur(shadow, (0, 0), 18)[..., None] * 0.55)

    labels = [("The table", xs[0] + PANEL_W // 2, y0 + PANEL_H + 22, 30),
              ("What the camera sees", xs[1] + PANEL_W // 2, y0 + PANEL_H + 22, 30)]
    if a.speed:
        labels.append((a.speed, OUT_W - 210, 24, 30))
    text = text_layer(labels)

    scr, ph = Reader(a.screen), Reader(a.phone, a.mirror)
    vx, vy, vw, vh = a.view
    px, py, pw, phh = a.phone_crop
    out = cv2.VideoWriter(a.out, cv2.VideoWriter_fourcc(*"avc1"), FPS, (OUT_W, OUT_H))
    n = int((a.t_to - a.t_from) * FPS)
    for k in range(n):
        t = a.t_from + k / FPS
        frame = bg.copy()
        panels = (cover(ph.at(t + a.offset)[py:py + phh, px:px + pw], PANEL_W, PANEL_H),
                  cover(scr.at(t)[vy:vy + vh, vx:vx + vw], PANEL_W, PANEL_H))
        for x, p in zip(xs, panels):
            region = frame[y0:y0 + PANEL_H, x:x + PANEL_W]
            frame[y0:y0 + PANEL_H, x:x + PANEL_W] = region * (1 - mask) + p.astype(np.float32) * mask
        if text:
            frame = frame * (1 - text[1]) + text[0] * text[1]
        out.write(frame.clip(0, 255).astype(np.uint8))
    out.release()
    print(f"wrote {a.out}: {n / FPS:.1f} s, SCREEN {a.t_from}-{a.t_to} s, phone +{a.offset:.3f} s")


if __name__ == "__main__":
    main()
