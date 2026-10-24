---
name: generate-fuel-layer
description: Regenerate a scenario's fire fuel layer (fuel.png) from OpenStreetMap land cover with tools/osm_to_fuel.py. Use when the fire ignores terrain cover (forest vs grass vs water vs town), when adding a scenario, or when changing how land-cover classes burn.
---

```sh
uv run tools/osm_to_fuel.py paradise                       # writes assets/scenarios/paradise/fuel.png
uv run tools/osm_to_fuel.py paradise --preview /tmp/f.png  # also a colour-by-class image to eyeball
uv run tools/osm_to_fuel.py paradise --refresh             # re-download instead of tools/.cache/overpass/
```

- `fuel.png` is grayscale at the sim grid size: value / 255 × 1.5 is the fuel multiplier (`load_fuel` in `engine/sim/fire.py`). Black is unburnable. Commit it with the scenario.
- Classes and weights are `CLASSES` at the top of the script; a later class wins where areas overlap. Forest is 1.0, which is what the whole map was before, so keep the map's mean near 1.0 or retune the fire (tune-fire skill).
- Check the printed class shares and the preview against `preview.png`: rivers should sit in canyon floors and towns on their ridges.
- After changing weights, re-measure how long the fire takes to reach the towns, since `game.json`'s round length depends on it.
- Uses the same projection and Overpass mirrors as `tools/osm_to_layers.py`. Multipolygon holes are ignored, and unmapped land stays at the background fuel.
