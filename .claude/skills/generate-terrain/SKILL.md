---
name: generate-terrain
description: Generate or change scenario terrain (sim heightmap.npy, printable STL tiles, preview) from real elevation data with tools/dem_to_assets.py. Use when asked to make 3D print files, change the board size, tiling, relief or region, add a new real-world scenario, or regenerate terrain assets.
---

# Generate terrain

```sh
uv run tools/dem_to_assets.py assets/scenarios/paradise/terrain.yaml            # everything
uv run tools/dem_to_assets.py assets/scenarios/paradise/terrain.yaml --no-stl   # heightmap + preview only, fast
uv run tools/dem_to_assets.py assets/scenarios/paradise/terrain.yaml --board    # also the untiled board.stl
uv run tools/dem_to_assets.py assets/scenarios/paradise/terrain.yaml \
    --set model.width_mm=300 --set tiles.cols=3 --set model.max_relief_mm=25    # try values without editing the yaml
```

uv installs the dependencies from `tools/dem_to_assets.py.lock`. Run `uv lock --script tools/dem_to_assets.py` after changing the script's dependency header.

## Inputs and outputs

- **Input:** `assets/scenarios/<name>/terrain.yaml`. Unset keys fall back to `DEFAULTS` at the top of the script, which documents every knob.
- `assets/scenarios/<name>/heightmap.npy` is a float32 `(H, W)` array in metres above sea level, with row 0 at north. Commit it.
- `assets/scenarios/<name>/terrain.json` holds the grid size, cell size, bounds, vertical exaggeration, marker centres (mm and map coords, outside the grid) and holder placement, tile list, places in map coords, and the resolved config. Commit it.
- `assets/scenarios/<name>/preview.png` shows hillshade, tile seams and places. Check it after every change. Commit it.
- `assets/stl/<name>/tile_r{row}_c{col}.stl` are the print tiles. Row 0 is north. `marker_holder.stl` is the calibration marker holder: print 4, one per corner. They're gitignored (about 12 MB each), so regenerate them.

## Viewing the tiles

`tools/terrain_viewer/index.html` is a three.js page that shows the STL tiles assembled, with per-tile on/off toggles, an explode slider (to see the pin holes), wireframe, and `preview.png` draped on top as a stand-in for the projection.

```sh
python3 -m http.server 8000   # from the repo root
open "http://localhost:8000/tools/terrain_viewer/?scenario=paradise"
```

## Gotchas

- North-south extent isn't a setting. It follows `width_km × height_mm / width_mm`, so the print can't be stretched.
- Changing anything under `model`, `region` or `markers` changes the heightmap, so commit the new `heightmap.npy` with it. Once printing starts, the config is frozen.
- `max_relief_mm` sets the vertical exaggeration automatically. Set `model.vertical_exaggeration` to fix it instead.
- Calibration markers sit on separate L-shaped holders outside the terrain. Each holder pins into the two outer walls of a corner tile (with pins of `markers.arm_width_mm + pins.depth_mm` length, 14 mm by default). Corner order is NW, NE, SE, SW.
- Pin holes take 1.75 mm filament (2.0 mm holes, 6 mm deep per side). They need `base_mm >= hole_diameter + 2`.
- Tiles larger than `tiles.bed_mm` print a warning but are still written.
- The full `board.stl` contains closed voids where the pins go. That's expected; print the tiles, not the board.
- New region: copy `paradise/terrain.yaml`, change `region.center` and `width_km`, and keep `zoom` at 13 or 14 (each step up is 4× the tiles). Tiles cache in `tools/.cache/`.
