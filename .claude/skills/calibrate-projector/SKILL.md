---
name: calibrate-projector
description: Calibrate the projector so the map lands on the printed terrain (projected ring pattern, H_map→proj, calibration.json), check alignment with the test grid, or debug a projection that's offset, keystoned, or won't calibrate. Use when setting up the table, after the projector or camera moves, or when touching engine/vision/projector.py or the projector's homography.
---

Design: PLAN.md, Calibration. Engine: `engine/vision/projector.py` (`Calibrator` wizard, `PatternFinder`). UI: `app/src/control/CalibrationPanel.tsx`, the `CALIBRATED` path in `render/shaders.ts`, and `render/ProjectionView.tsx`.

## On the real table

1. Set `CAMERA=<index>` in the root `.env` (see the vision-camera skill) and start the engine and app (`make dev`, or `make engine` + `make web`).
2. Open the projector on the projector display and make it **fullscreen** (Tauri does this; in a browser press F). Calibration is in window-normalised coords, so a window that changes size afterwards is off.
3. Corner markers: each centred about 18 mm outside its terrain corner in both directions (`terrain.json` `center_map`), with a white margin all round. If the terrain or a sheet overlaps a marker's border it won't decode, and a misplaced marker shifts the whole map.
4. The terrain stays on. Projector panel → **Calibrate** (or Shift+C). The projector goes black until the camera sees all four corners, then shows a dim ring; the camera feed marks the 8 ring corners in magenta. It needs 8 frames, about a second. Then a grid of ~100 dots goes up for another second; the engine solves the projector lens position from them (log: `projector dot fit: N dots, X px RMS (Y px flat); lens Z mm up`). No tape needed; `PROJECTOR_MM` in `.env` is only a starting guess.
5. Review: the cyan crosses should sit on the four corner markers, and the cyan border (drawn on the terrain, height-corrected) on the print's top edge. **Save** writes `calibration.json` (repo root, gitignored). **Redo** or **Cancel** if not.
6. Later: **Test grid** shows the check again, **Clear** goes back to the letterboxed map.

A bumped table fixes itself: once the board has moved by more than 4 pattern px for half a second, the engine re-derives map→projector from the saved camera→projector. Moving the camera or projector on its own needs a recalibration.

## Gotchas

- "The camera can't see all four corner markers" (after 30 s, projector black): a marker is covered, overlapped by the sheet, or out of view. Two swapped corner markers never lock (the engine logs "corner markers out of order").
- "The camera can't see the pattern" (after 30 s): the projector window isn't on the table or isn't fullscreen, or the ring falls off the board (it's drawn in the middle 60% of the frame). Room light is fine: the black frame is subtracted.
- Projector window is a browser and the map shows through the pattern: the map isn't rendered during the pattern phase for exactly this reason (Chrome on macOS composited the WebGL canvas over the image); keep it that way.
- Fit error (`fit N px`, in 1920-wide pattern px) is the dots' residual after taking the terrain out; the log also prints the flat fit's. ~4 px is what the first table got. "Couldn't see the dot grid, so this uses the ring alone": the dots were too dim or the projector window lagged; the result is usable but worse on hills, so redo. "dot grid couldn't place the projector" in the log: the solve was no better than straight overhead, so it fell back to `PROJECTOR_MM` (or no correction).
- Ring corners are biased on terrain (lines fitted along whole edges that cross hills), so don't judge the lens or the height model by the ring's error; only the dots are point measurements.
- The camera's position comes from the corner markers and an assumed C920 focal length (`geometry.CAMERA_FOCAL`). `uv run python -m vision.camera 0` prints where it thinks the lens is; if that's far from a tape measurement, the focal length is off.
- Every calibration re-locks the board under the black screen, so the pose is fresh. Tokens and the board freeze while the pattern is up.
- A saved calibration for another scenario keeps camera→projector and re-derives the map part as soon as the board is seen.
- No hardware: point `CAMERA` at a still image (vision-camera skill). The pattern search then times out, but you can check the UI. `engine/tests/test_projector.py` renders a synthetic camera view of the projected pattern, and it can write a fake `calibration.json` for the projector view.
- Don't leave a test `calibration.json` in the repo root: the engine loads it on start.

Tests: `cd engine && uv run pytest tests/test_projector.py`.
