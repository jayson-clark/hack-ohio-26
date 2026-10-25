# Demo video takes

The console footage for the demo video, as scripts. The video itself (lines, timing, shots) is `SCRIPT.md`; `make prompter` plays it as a karaoke prompter for the voiceover. Each `takes/*.take` file is one segment: it sets up the engine, preps the console off camera, records its scenes with Recordly (which drives the real mouse and keyboard), then adds zooms and exports. Edit a line, re-run that take, and commit the change. The shot list and voiceover are in [`SCRIPT.md`](SCRIPT.md); these files are only the screen recordings.

```sh
make engine && make web            # in two terminals; Recordly open, agent control on
make demo-video                    # every take, in name order
make demo-video TAKES="B2 C"       # only takes whose names start with B2 or C
cd engine && uv run python ../tools/demo_video/run.py --rehearse C   # run it, don't record
cd engine && uv run python ../tools/demo_video/run.py --check        # parse every take
```

Exports land in `~/Movies/fireline-demo/` (`DEMO_OUT_DIR` or `--out` to change), overwriting the last version. Recordly keeps every raw capture in its library.

Hands off the mouse and keyboard while it runs. If you touch them, Recordly stops that scene and the take fails; run it again.

## The window

The runner records the whole screen and drives a Chrome app window titled "Fireline" (no tabs or address bar). If none is open it opens one at `http://localhost:1420/?view=console&demo=1`. The video is cropped to that window minus its title bar and framed on a wallpaper, so a shot with no zoom shows the whole window like a Mac screenshot and the zooms move in from there. The window fills about 78% of the frame, so `depth=3` (1.8×) is roughly the old full-window framing. Takes that click by coordinates (C's sliders and map point) assume the 1668×1084 window this was written on; re-aim them with `--rehearse` if yours differs.

## Commands

One command per line; `#` starts a comment. Quote text with spaces.

**Engine** (any time; inside a block they run between that block's steps)

| | |
|---|---|
| `engine fresh <speed> [paused]` | Remove every virtual token, reset, set the speed and start the round at the Camp Fire origin |
| `engine advance <minutes>` | Run the fire this many sim-minutes, then pause |
| `engine speed <x>` / `engine pause` / `engine resume` | |
| `engine send <json>` | Any client message, e.g. `engine send '{"type":"set_wind","speed_ms":12,"from_deg":90}'` (single quotes, or the line's quoting eats the JSON's) |

**Windows.** `window console` or `window control` (exercise control) picks the window the steps drive. The first one named is where the take starts; inside a block it cuts to the other window mid-take. Both are Chrome app windows, opened if missing and moved onto the console's bounds, so the crop holds across the cut. `reload` reloads whichever window is being driven.

**Blocks.** `prep` runs steps without recording; `scene "title"` records them. Recording starts at the first scene and runs to the end of the take. Each block is one Recordly `perform` call, so keep a scene under a minute. `pace=brisk|normal|relaxed` sets how fast the pointer glides (default: `brisk` for prep, `relaxed` for scenes).

**Steps** (inside a block)

| | |
|---|---|
| `click "text" [role=button] [index=0]` | Click an element by its visible text. `index` picks among several matches, top to bottom |
| `click 75,514` | Click a window point |
| `drag 75,514 114,514 [ms=900]` | Press, glide and release, e.g. a slider's thumb to a new value. Either end can be text instead of a point |
| `move "text"` / `move 1200,560 [ms=1500]` | Glide the pointer there |
| `key period` / `key right x9` / `key k mods=cmd+shift` | Press a key, optionally repeated or with modifiers |
| `reload` | Reload the console page (prep only). Done through AppleScript, because keys don't reach the Chrome app window's menu |
| `type "text" [into="placeholder"]` | Type text (`\n` presses Return) |
| `hold 4` | Keep 4 s in the video, for reading |
| `wait 1` | Pause 1 s |
| `waitfor "text" [gone] [timeout=20]` / `waitfor settled [quiet=3]` | Wait for an element to appear or go, or for the screen to settle |

Console keys worth knowing in demo mode: `.` pauses, `[` `]` change speed, `A` toggles Autopilot, `M` `P` `R` switch modes, `Esc` closes the inspector.

**After recording**

| | |
|---|---|
| `zoom <from>..<to> [follow] [depth=2] [at=cx,cy]` | Zoom in. Depth 1–6 is 1.25× to 5×; `at` is the focus as a fraction of the window (see Aiming zooms). `follow` tracks the pointer instead |
| `look wallpaper=/wallpapers/tahoe-dark.jpg padding=20` | Change this take's frame: `wallpaper` (a Recordly wallpaper, image path or colour), `padding` (0–100, damped to 0–20% a side), `borderRadius`, `shadowIntensity`, `backgroundBlur`. Defaults are `LOOK` in `run.py` |
| `trim <from>..<to>` | Keep only this span |
| `label "0.5× · 5 sim-min/s" <from>..<to> [at=x,y]` | A text plate pinned to the frame (top right by default; `at` in percent), so zooms can't crop it. Used for the sim-speed badge: caption every speed change so nobody thinks the footage is sped up behind their back |
| `caption "text" <from>..<to>` | A caption along the bottom (one at a time) |
| `card title\|end "text" [sub="second line"] [ms=2.5]` | A title or end card; it adds time to the video, so it's applied last |
| `export <file>.mp4` | Output name (default: the take's name) |

Times (for zooms, labels, captions and trim) are `0`, `end`, or `<scene>@<seconds>` counted from that scene's start (scenes from 1), e.g. `2@1.5`, `1@end`, `1@end-3`. Scene times come from the recording, so zooms stay on their moment when a take runs longer or shorter.

## Aiming zooms

`at` is a fraction of the recorded window (title bar excluded), not of the framed video: take a point from a Recordly window screenshot and divide by the window's size. The zoom is centred there, and a zoom near the window's edge shows the wallpaper past it. To keep a zoom inside the window, `at` must stay within these limits:

| Depth | Scale | `cx` | `cy` |
|---|---|---|---|
| 3 | 1.8× | 0.36–0.64 | 0.32–0.68 |
| 4 | 2.2× | 0.29–0.71 | 0.26–0.74 |
| 5 | 3.5× | 0.19–0.81 | 0.17–0.83 |

Landmarks at 1668×1084 with the map fitted:

| What | `at` |
|---|---|
| Queue: the first card, to read it | 0.19, 0.36 (depth 5) |
| Left panel and the map's west edge: the queue, Plan's outcome, Review | 0.29, 0.45 |
| Inspector on the right (town, recommendation), with the map beside it | 0.71, 0.40 |
| Commander dock, opened | 0.71, 0.74 |
| Fire origin near Pulga, Concow and Magalia | 0.71, 0.40 |
| The map's middle | 0.62, 0.50 |

What reads well (see `SCRIPT.md`):
- Open each take wide for a couple of seconds, so the viewer gets their bearings.
- Use depth 4 for any UI text, and depth 5 to read one card. At depth 3 or below the console's text can't be read at 1080p.
- To go from one target to the next, let the zooms touch (`..2@0.8` then `2@0.8..`) so the camera pans instead of zooming out and back in.
- Hold each zoom for the whole sentence about it.

## Gotchas

- Recordly cuts idle stretches and adds click zooms and captions when a recording loads. The runner undoes all of that, because most of this footage is the fire moving, and applies only the take's own zooms and text. It also turns off zoom motion blur, which smears the map's labels. On a busy machine Recordly's suggestions can land after the runner has placed its zooms, so it checks the edit after a pause and puts its zooms and captions back.
- Every take reloads the console and fits the map in `prep`, so the last take's selection, zoom, plan drafts, commander dock and autopilot don't leak into it.
- Move sliders with `drag`, not a click and arrow keys: with keys the thumb jumps while the pointer sits still. Thumb x for a value is about `36 + 308 × fraction` in the Plan panel at 1668 wide; check the value with `--rehearse`.
- Recordly's `type` has dropped letters in this window. Prefer clicking the commander's suggestion buttons.
- A tiling window manager (AeroSpace here) moves the window when Recordly takes focus at the start of a take, so the first frames slid against the crop. The runner floats the window with `aerospace layout floating` when AeroSpace is installed. With another tiler, float the Chrome app window by hand.
- Record with `FIRE_SEED=7` in `.env`: without a seed the real fire dies out early in some rounds, and with one every take starts from the same fire, which is what the zooms and click points were aimed on.
- The calibrated outline's miss rates carry over between rounds on a map, so restart the engine before a take that reads them (G); a previous round's wind shift leaves the legend orange.
- Recordly caps one `hold` or `waitfor` at 30 s. Split longer ones.
- Above 1× the Paradise fire outruns every decision. Most takes run at 0.25–0.5×.
