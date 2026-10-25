# Demo video takes

The console footage for the demo video, as scripts. Each `takes/*.take` file is one segment: it sets up the engine, preps the console off camera, records its scenes with Recordly (which drives the real mouse and keyboard), then adds zooms and exports. Edit a line, re-run that take, and commit the change. The shot list and voiceover live in the video plan; these files are only the screen recordings.

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
| `engine send <json>` | Any client message, e.g. `engine send {"type":"set_wind","speed_ms":12,"from_deg":90}` |

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
| `zoom <from>..<to> [follow] [depth=2] [at=cx,cy]` | Zoom in. Depth 1–6 is 1.25× to 5×; `at` is the focus as a fraction of the frame (wallpaper included). `follow` tracks the pointer instead |
| `look wallpaper=/wallpapers/tahoe-dark.jpg padding=20` | Change this take's frame: `wallpaper` (a Recordly wallpaper, image path or colour), `padding` (0–100, damped to 0–20% a side), `borderRadius`, `shadowIntensity`, `backgroundBlur`. Defaults are `LOOK` in `run.py` |
| `trim <from>..<to>` | Keep only this span |
| `label "0.5× · 5 sim-min/s" <from>..<to> [at=x,y]` | A text plate pinned to the frame (top right by default; `at` in percent), so zooms can't crop it. Used for the sim-speed badge: caption every speed change so nobody thinks the footage is sped up behind their back |
| `caption "text" <from>..<to>` | A caption along the bottom (one at a time) |
| `card title\|end "text" [sub="second line"] [ms=2.5]` | A title or end card; it adds time to the video, so it's applied last |
| `export <file>.mp4` | Output name (default: the take's name) |

Times (for zooms, labels, captions and trim) are `0`, `end`, or `<scene>@<seconds>` counted from that scene's start (scenes from 1), e.g. `2@1.5`, `1@end`, `1@end-3`. Scene times come from the recording, so zooms stay on their moment when a take runs longer or shorter.

## Gotchas

- Recordly cuts idle stretches and adds click zooms and captions when a recording loads. The runner undoes all of that, because most of this footage is the fire moving, and applies only the take's own zooms and text. It also turns off zoom motion blur, which smears the map's labels.
- Every take reloads the console and fits the map in `prep`, so the last take's selection, zoom, plan drafts, commander dock and autopilot don't leak into it.
- Move sliders with `drag`, not a click and arrow keys: with keys the thumb jumps while the pointer sits still. Thumb x for a value is about `36 + 308 × fraction` in the Plan panel at 1668 wide; check the value with `--rehearse`.
- Recordly's `type` has dropped letters in this window. Prefer clicking the commander's suggestion buttons.
- Above 1× the Paradise fire outruns every decision. Most takes run at 0.25–0.5×.
