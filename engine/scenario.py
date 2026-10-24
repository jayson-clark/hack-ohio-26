"""Scenario assets, loaded once and shared read-only by every engine module.

Everything here comes from assets/scenarios/<name>/, written by
tools/dem_to_assets.py. The map grid is `width` x `height` cells with row 0 at
north; it is not square (Paradise is 256 x 192), so never assume it is.
"""

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ASSETS = Path(__file__).resolve().parent.parent / "assets" / "scenarios"


@dataclass(frozen=True)
class Place:
    name: str
    x: float  # map coords, cell units
    y: float


@dataclass(frozen=True)
class Scenario:
    name: str
    dir: Path
    width: int
    height: int
    cell_size_m: float
    heightmap: np.ndarray  # float32 (height, width), metres above sea level
    places: tuple[Place, ...]
    terrain: dict  # the full terrain.json, for anything not lifted out above

    def in_bounds(self, x: float, y: float) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height


def load_scenario(name: str) -> Scenario:
    d = ASSETS / name
    terrain = json.loads((d / "terrain.json").read_text())
    grid = terrain["grid"]
    heightmap = np.load(d / terrain["heightmap"]["file"]).astype(np.float32)
    if heightmap.shape != (grid["height"], grid["width"]):
        raise ValueError(f"{name}: heightmap {heightmap.shape} doesn't match terrain.json grid")
    places = tuple(Place(p["name"], *p["map"]) for p in terrain.get("places", []))
    return Scenario(
        name=name,
        dir=d,
        width=grid["width"],
        height=grid["height"],
        cell_size_m=grid["cell_size_m"],
        heightmap=heightmap,
        places=places,
        terrain=terrain,
    )
