---
name: generate-road-layers
description: Regenerate a scenario's road graph and towns (roads.json, towns.json) from OpenStreetMap with tools/osm_to_layers.py. Use when roads or towns look wrong, when changing which road classes the evacuation router sees, when adding a town or safe zone, or for a new scenario.
---

```sh
uv run tools/osm_to_layers.py paradise              # uses the cached Overpass response if present
uv run tools/osm_to_layers.py paradise --refresh    # re-download
uv run tools/osm_to_layers.py paradise --classes motorway,trunk,primary,secondary,tertiary   # smaller graph
uv run tools/osm_to_layers.py paradise --stations-only   # just fire stations (stations.json)
```

- Writes `assets/scenarios/<name>/roads.json` (`nodes` [[x, y]], `edges` [[i, j, length_m, class]], map coords) and `towns.json` (`towns`, `safe_zones`). Commit both.
- Towns (population, structures, radius) and safe zones (road name + map edge) are typed into `TOWNS` / `SAFE_ZONES` at the top of the script. Figures are approximate.
- Projection is linear in lon/lat from `terrain.json` bounds; `engine/tests/test_routing.py` checks it against `places`.
- Dead-end residential stubs are pruned and degree-2 chains simplified to 0.5 cell; Paradise is ~1.5k nodes / 1.8k edges.
- Overpass needs a User-Agent (406 otherwise) and often 502s under load; the script retries two mirrors. Responses cache in `tools/.cache/overpass/` (gitignored).
- Check alignment by drawing the edges over `preview.png`.
- After changing the script's dependency header run `uv lock --script tools/osm_to_layers.py`.
- `stations.json` (`stations`: name, x, y, kind ground|air, units {token type: count}) lists the fire stations dispatch sends units from (#104). Ground stations come from OSM `amenity=fire_station` on the map; air bases are typed into `AIR_BASES` and may sit off the map. Units per station are `GROUND_UNITS` / `AIR_UNITS`.
