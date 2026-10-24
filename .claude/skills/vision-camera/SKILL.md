---
name: vision-camera
description: Turn on the webcam for token tracking, pick the right camera index, test vision without the table, or debug ArUco marker detection (tokens not appearing, wrong positions, "Show all four corners"). Use when touching engine/vision/ or the console's Camera tab.
---

Pipeline (all in `engine/vision/`, on its own thread): `camera.py` capture → `markers.py` detect (DICT_4X4_50) → `calibration.py` `H_cam→map` from the 4 corner markers → `tracking.py` debounce/smooth → `TokenTracker` as source `vision`. Design: PLAN.md, Calibration and Token tracking.

**Marker IDs** (`markers.py`, keep in sync with the printed sheets): corners NW/NE/SE/SW = 0/1/2/3; crew 10–19, firebreak 20–29, water 30–39, bus 40–49. Token id on the wire is `m<marker id>`.

**Turn it on:** set `CAMERA=` in the root `.env`, restart the engine, open the console's **Camera** tab.
- `CAMERA=0` / `1` / …: AVFoundation index. The built-in camera, a USB webcam and an iPhone (Continuity Camera) all get indices, and the order isn't stable. Check one with `cd engine && uv run python -m vision.camera 1`. It prints the markers it sees and writes `camera-1.jpg` with the overlay.
- `CAMERA=path/to/board.png` (or a video): looped as if it were a camera, so you can work with no hardware. Relative paths are from the repo root.
- Empty: vision off, virtual table only (the default).

**No hardware test image:** `render_camera_image()` in `engine/tests/test_vision.py` draws a warped board with corner and token markers. `cv2.imwrite` its output and point `CAMERA` at it.

**Debugging** (bottom bar of the Camera tab):
- "No signal": the index doesn't exist, or macOS denied camera access. Allow your terminal (or the Tauri app) under System Settings → Privacy & Security → Camera, then restart it.
- "Show all four corners": the homography is solved only when all four corner markers are visible at once. After that it's kept while some are covered. A green map outline means locked this frame; orange means it's reusing an older solve.
- A marker is outlined but no token appears: it has to sit inside the map grid and be seen for `APPEAR_FRAMES` frames in a row. Unknown IDs are drawn grey with `?`.
- Positions slightly off on tall hills: parallax, because the homography is for the plane of the corner markers. Expected; see PLAN.md, Height parallax.
- Washed out under projector light: rely on the white halos. Lower ambient light before you lower detection thresholds.

Tests: `cd engine && uv run pytest tests/test_vision.py`.
