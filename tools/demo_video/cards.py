"""The demo video's cards, framed like the takes (SCRIPT.md): the Camp Fire
replay over the real perimeters, the limits card and the end card, as
1920x1080 PNGs.

    cd engine && uv run --with pillow python ../tools/demo_video/cards.py OUT_DIR

The replay runs the fire model as `eval.campfire` does at its defaults
(8 rollouts, 12 h), so its numbers are the default replay's, not the
best of the parameter search. Takes a minute or two.
"""

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "engine"))

W, H = 1920, 1080
WALLPAPER = Path("~/Recordly-mcp/public/wallpapers/sequoia-blue-orange.jpg").expanduser()
FONT, FONT_BOLD = "/System/Library/Fonts/SFNS.ttf", "/System/Library/Fonts/SFNS.ttf"
PLATE = (14, 17, 19, 235)
TEAM = "Adarsh Muralidharan · Aditya Vadlamani · Jayson Clark · Jalen Francis"
REPO = "github.com/jayson-clark/hack-ohio-26"


def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT, size)


def background() -> Image.Image:
    if not WALLPAPER.exists():
        return Image.new("RGB", (W, H), PLATE[:3])
    img = Image.open(WALLPAPER).convert("RGB")
    s = max(W / img.width, H / img.height)
    img = img.resize((round(img.width * s), round(img.height * s)), Image.LANCZOS)
    x, y = (img.width - W) // 2, (img.height - H) // 2
    return img.crop((x, y, x + W, y + H))


def panel(base: Image.Image, box: tuple[int, int, int, int], radius: int = 16) -> None:
    """A dark rounded panel with a soft shadow, like the split's."""
    x0, y0, x1, y1 = box
    shadow = Image.new("L", base.size, 0)
    ImageDraw.Draw(shadow).rounded_rectangle((x0, y0 + 10, x1, y1 + 10), radius, fill=140)
    base.paste((0, 0, 0), mask=shadow.filter(ImageFilter.GaussianBlur(18)))
    ImageDraw.Draw(base, "RGBA").rounded_rectangle(box, radius, fill=PLATE)


def text(d: ImageDraw.ImageDraw, xy: tuple[int, int], s: str, size: int, fill=(255, 255, 255), anchor: str = "la") -> None:
    d.text(xy, s, font=font(size), fill=fill, anchor=anchor)


def hillshade(z: np.ndarray, cell_m: float) -> np.ndarray:
    gy, gx = np.gradient(z.astype(np.float64), cell_m)
    slope = np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    az, alt = np.radians(315), np.radians(45)
    shade = np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(az - aspect)
    return np.clip(shade, 0, 1)


def outline(mask: np.ndarray) -> np.ndarray:
    m = mask.astype(bool)
    edge = np.zeros_like(m)
    edge[1:-1, 1:-1] = m[1:-1, 1:-1] & ~(m[:-2, 1:-1] & m[2:, 1:-1] & m[1:-1, :-2] & m[1:-1, 2:])
    return edge


def replay_card(out: Path) -> dict:
    import sim.fire as fire
    from eval.campfire import load_truth, replay, score, wind_at
    from scenario import load_scenario

    scen = load_scenario("paradise")
    cells, times, origin, masks, mask_t, _ = load_truth(12.0)
    ticks = int(12 * 60 / fire.SIM_MINUTES_PER_TICK)
    first = replay(scen, origin, lambda t: wind_at(t, 19.0, 6.0, 65.0), ticks, 8)
    res = score(first, cells, times, masks, mask_t)
    print("replay:", res)

    shade = hillshade(scen.heightmap, scen.cell_size_m)
    base_rgb = (np.stack([0.30 + 0.45 * shade] * 3, -1) * np.array([0.80, 0.86, 0.74]) * 255).astype(np.uint8)
    picks = [i for i, t in enumerate(mask_t) if round(t / 60, 1) in (7.1, 11.5)] or list(range(min(2, len(mask_t))))
    # Crop to the fire: everything either one burned, with a margin, at 16:10.
    last = (np.isfinite(first) & (first <= mask_t[picks[-1]] / fire.SIM_MINUTES_PER_TICK)).mean(axis=0) >= 0.5
    ys, xs_ = np.nonzero(last | masks[picks].any(axis=0))
    y0c, y1c, x0c, x1c = ys.min() - 12, ys.max() + 12, xs_.min() - 12, xs_.max() + 12
    cw = max(x1c - x0c, round((y1c - y0c) * 1.6))
    ch = round(cw / 1.6)
    cx, cy = (x0c + x1c) // 2, (y0c + y1c) // 2
    x0c, y0c = int(np.clip(cx - cw // 2, 0, scen.width - cw)), int(np.clip(cy - ch // 2, 0, scen.height - ch))
    win = (slice(y0c, y0c + ch), slice(x0c, x0c + cw))

    img = background()
    d = ImageDraw.Draw(img, "RGBA")
    text(d, (W // 2, 64), "The Camp Fire, replayed against the real perimeters", 44, anchor="mm")
    text(d, (W // 2, 112), "Default replay settings, simulator only: no tuning to these perimeters", 26, fill=(230, 232, 235), anchor="mm")
    pw = 820
    ph = round(pw / 1.6)
    xs = ((W - 2 * pw - 40) // 2, (W - 2 * pw - 40) // 2 + pw + 40)
    y0 = 170
    for x, i in zip(xs, picks):
        t = mask_t[i]
        burned = (np.isfinite(first) & (first <= t / fire.SIM_MINUTES_PER_TICK)).mean(axis=0) >= 0.5
        rgb = base_rgb.astype(np.float32)
        rgb[burned] = rgb[burned] * 0.45 + np.array([235, 110, 40]) * 0.55
        edge = outline(masks[i])
        edge = edge | np.roll(edge, 1, 0) | np.roll(edge, 1, 1)
        rgb[edge] = (255, 255, 255)
        tile = Image.fromarray(rgb[win].astype(np.uint8)).resize((pw, ph), Image.NEAREST)
        panel(img, (x - 8, y0 - 8, x + pw + 8, y0 + ph + 64))
        mask = Image.new("L", (pw, ph), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, pw - 1, ph - 1), 12, fill=255)
        img.paste(tile, (x, y0), mask)
        hours = t / 60
        iou, area = res.get(f"iou_{hours:.1f}h"), res.get(f"area_ratio_{hours:.1f}h")
        d = ImageDraw.Draw(img, "RGBA")
        text(d, (x + 4, y0 + ph + 16), f"{hours:.1f} h after ignition", 28)
        text(d, (x + pw - 4, y0 + ph + 16), f"IoU {iou:.2f} · {area:.1f}× the area", 28, fill=(255, 200, 150), anchor="ra")
    # Legend and the Marshall row.
    ly = y0 + ph + 100
    d.rounded_rectangle((xs[0], ly, xs[0] + 24, ly + 24), 4, fill=(235, 110, 40))
    text(d, (xs[0] + 36, ly - 2), "Simulated (half or more of 8 runs burned)", 26)
    d.rectangle((xs[0] + 640, ly + 10, xs[0] + 676, ly + 14), fill=(255, 255, 255))
    text(d, (xs[0] + 688, ly - 2), "Real perimeter (NIFC / NASA FEDS)", 26)
    text(d, (W // 2, ly + 70), "Marshall Fire, 2.5 h: burned area 1.01× · IoU 0.45", 30, fill=(255, 220, 190), anchor="mm")
    img.save(out)
    return res


def lines_card(out: Path, title: str, rows: list[str], sub: str = "") -> None:
    img = background()
    d = ImageDraw.Draw(img, "RGBA")
    box_w, row_h = 1320, 96
    box_h = 150 + row_h * len(rows) + (60 if sub else 0)
    x0, y0 = (W - box_w) // 2, (H - box_h) // 2
    panel(img, (x0, y0, x0 + box_w, y0 + box_h), 22)
    d = ImageDraw.Draw(img, "RGBA")
    text(d, (x0 + 60, y0 + 50), title, 46)
    for k, r in enumerate(rows):
        y = y0 + 140 + k * row_h
        d.ellipse((x0 + 64, y + 14, x0 + 80, y + 30), fill=(255, 170, 90))
        text(d, (x0 + 104, y), r, 36)
    if sub:
        text(d, (x0 + 60, y0 + box_h - 70), sub, 26, fill=(200, 205, 210))
    img.save(out)


def end_card(out: Path) -> None:
    img = background()
    d = ImageDraw.Draw(img, "RGBA")
    panel(img, (360, 300, W - 360, 780), 28)
    d = ImageDraw.Draw(img, "RGBA")
    text(d, (W // 2, 420), "Fireline", 110, anchor="mm")
    text(d, (W // 2, 520), "Know when to act, and how far to trust the forecast.", 38, fill=(230, 232, 235), anchor="mm")
    text(d, (W // 2, 640), TEAM, 30, fill=(210, 214, 218), anchor="mm")
    text(d, (W // 2, 700), REPO, 30, fill=(255, 190, 140), anchor="mm")
    img.save(out)


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else ".").expanduser()
    out.mkdir(parents=True, exist_ok=True)
    lines_card(out / "card-limits.png", "Where it falls short", [
        "Town arrival ranges: 95% in steady wind, 67% after a shift",
        "No wind forecast and no fuel moisture",
        "Fire doesn't spread house to house",
        "Ranges cover the simulator, not its error against real fires",
    ], sub="Measured on the extended Paradise map, simulator only (EMULATOR=off)")
    end_card(out / "card-end.png")
    replay_card(out / "card-replay.png")
    print(f"cards in {out}")


if __name__ == "__main__":
    main()
