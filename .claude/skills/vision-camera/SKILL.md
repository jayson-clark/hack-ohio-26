---
name: vision-camera
description: Turn on the webcam for token tracking, pick the right camera index, test vision without the table, or debug ArUco marker detection (tokens not appearing, wrong positions, "Show all four corners"). Use when touching engine/vision/, exercise control's Camera view or the console's drone basemap.
---

Pipeline (all in `engine/vision/`, on its own thread): `camera.py` capture → `markers.py` detect (DICT_4X4_50) → `calibration.py` `H_cam→map` from the 4 corner markers → `tracking.py` debounce/smooth → `TokenTracker` as source `vision`. Design: PLAN.md, Calibration and Token tracking.

**Marker IDs** (`markers.py`): corners NW/NE/SE/SW = 0/1/2/3; crew 10–14, firebreak 20–24, water 30–34, bus 40–44 (`TOKENS_PER_TYPE = 5`; other IDs are ignored). Token id on the wire is `m<marker id>`.

**Printing markers:** `uv run tools/make_markers.py` regenerates `assets/markers/markers.pdf` (page 1 corners, page 2 tokens; `--token-mm` sets the token piece size, default 20). Regenerate after changing IDs or the corner size in `terrain.yaml`. Print at 100% / Actual size and check the 100 mm bar with a ruler. Each piece includes a 1-cell white margin; cut on the dashed line. Keep it vector: a rasterised sheet printed with corner borders eaten away and never decoded.

**Turn it on:** set `CAMERA=` in the root `.env`, restart the engine, open exercise control (`?view=control`, or "Exercise control" in the console header) and pick the **Camera** view.
- `CAMERA=0` / `1` / …: AVFoundation index. The built-in camera, a USB webcam and an iPhone (Continuity Camera) all get indices, and the order isn't stable. Check one with `cd engine && uv run python -m vision.camera 1`. It prints the markers it sees and writes `camera-1.jpg` with the overlay.
- `CAMERA=path/to/board.png` (or a video): looped as if it were a camera, so you can work with no hardware. Relative paths are from the repo root.
- Empty: vision off, virtual table only (the default).

**No hardware test image:** `render_camera_image()` in `engine/tests/test_vision.py` draws a warped board with corner and token markers. `cv2.imwrite` its output and point `CAMERA` at it. To see the UI without disturbing a running engine, start a second one with `ENGINE_PORT=8766 CAMERA=<img> ENGINE_ORIGINS=http://localhost:1421 uv run server.py` and a second Vite with `VITE_ENGINE_URL=ws://localhost:8766 pnpm exec vite --port 1421`.

**Debugging** (bottom bar of the Camera tab):
- "No signal": the index doesn't exist, or macOS denied camera access. Allow your terminal (or the Tauri app) under System Settings → Privacy & Security → Camera, then restart it.
- "Show all four corners": the homography is solved only when all four corner markers are visible at once. After that it's kept while some are covered. A green map outline means locked this frame; orange means it's reusing an older solve.
- Tokens detect but a marker never does, however you tune it: the print or the paper. On a sheet held in your hands, the corners curl, so a corner marker's border gets squashed on one side and it's rejected as a non-square. Lay the sheet flat, and check the border measures 1 cell (marker / 6) with a ruler. Don't loosen the detector: looser settings start reading IDs that aren't there.
- A marker is outlined but no token appears: it has to sit inside the map grid and be seen for `APPEAR_FRAMES` frames in a row. Unknown IDs are drawn grey with `?`.
- Positions off on tall hills: the height correction (PLAN.md, Height parallax) places the camera from the corner markers and an assumed focal length, and assumes tokens are `tracking.TOKEN_TOP_MM` tall. `uv run python -m vision.camera 0` prints the camera position it solved; compare with a tape. Synthetic flat renders (tests/test_vision.py) turn it off with `geometry.CAMERA_FOCAL = None`.
- Washed out under projector light (the Camera view is all white): auto-exposure meters the dark table and blows out the lit board. Set `CAMERA_EXPOSURE=10` (100 µs units) and `CAMERA_FOCUS=0` in `.env`; `vision/uvc.py` applies them via `npx uvcc` after every open (OpenCV can't on macOS, and opening resets them). On the real rig, 10 gives 0% clipped and all four corners still lock; at 5 the corners stop decoding. Retune with `npx -y uvcc@8.0.0 set absolute_exposure_time N` while the engine runs. Don't lower detection thresholds.
- Once locked, the feed is a top-down orthophoto cropped to the map grid (`draw_ortho`, `VisionStatus.feed_rectified`); exercise control's Camera view draws the map layers over it (toggles top right), the console uses it as the incident map's basemap (Map/Drone switch, `console/map/IncidentMap.tsx`), and the engine draws nothing on it. An engine started before #202 never sends `feed_rectified`, so neither appears until it's restarted. The projector itself shows only ground and fire (#198; `?view=projector&overlays=1` for the old annotated projection). `python -m vision.camera 0` also writes `camera-0-ortho.jpg`. `SteadyOrtho` holds one warp until the board outline moves more than `ORTHO_DEADBAND_PX` (2 px), because re-warping on every frame made the feed shimmer. If a small real nudge doesn't show up, lower the deadband.
- Sharpness: the real limit is resolution. With the camera at ~730 mm the board covers only 636×478 of the 1920×1080 frame (2.5 px per cell). Lowering or tilting the camera so the board fills more of the frame is the only big gain, and it means recalibrating the projector. The feed already uses cubic sampling, an unsharp mask (`ORTHO_SHARPEN`) and JPEG q85. Tried and rejected: C920 digital zoom (no new pixels, and changing it upsets the lock), focus above 0 (softer, loses the lock by 4), and frame averaging (noise is only ~2 grey levels, and it smears moving fire).

Projector calibration (map → projector, the projected ring): see the calibrate-projector skill.

Tests: `cd engine && uv run pytest tests/test_vision.py`.
