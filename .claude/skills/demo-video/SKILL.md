---
name: demo-video
description: Re-record, edit or add the demo video's console takes (tools/demo_video/*.take, make demo-video), or record new console footage with Recordly. Use when asked to redo a demo segment, change what a take shows or zooms on, or fix a take that fails.
---

The takes and their command language are in `tools/demo_video/README.md`. Read it first.

- Prereqs: `make engine`, `make web`, and the Recordly app open with "Let agents use the mouse and keyboard" on. The runner finds Recordly through its entry in `~/.claude.json` (or `RECORDLY_MCP_URL`/`RECORDLY_MCP_TOKEN`).
- Change a take: edit its `.take` file, run `--check`, then `--rehearse <take>` (drives the UI, records nothing), then `make demo-video TAKES=<take>`.
- To see an export without opening it: the Recordly editor still holds the last take, so its `render_preview` shows frames (no ffmpeg on this Mac).
- Find a click target: Recordly's `find_elements` (or a `perform` dry run) lists what's clickable. Text targets beat coordinates; coordinates are window points for the 1668×1084 Chrome app window.
- A failed step means the page didn't match the script, usually because the queue's order or timing changed. Add a `waitfor` before the click, or an `index=`.
- Exercise control or the camera: `window control` in a take drives exercise control, `window console` cuts back (`F-table-camera` does both). The camera must be live with the board locked; if the feed looks washed out, see the vision-camera skill (gain).
- Safari upgrades `localhost` to https here. The runner uses a Chrome app window.
- The frame (wallpaper, padding, corners) is `LOOK` in `run.py`, or `look` in a take. To try one without recording: `open_editor` on a recent take, `set_look`, then `render_preview count=4`.
