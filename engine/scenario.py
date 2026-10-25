"""Scenario assets, loaded once and shared read-only by every engine module.

Everything here comes from assets/scenarios/<name>/, written by
tools/dem_to_assets.py. The map grid is `width` x `height` cells with row 0 at
north; it is not square (Paradise is 512 x 480), so never assume it is. The
printed terrain covers only part of it (`print_window`).
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

    @property
    def print_window(self) -> tuple[int, int, int, int]:
        """The printed terrain in map cells, (x0, y0, width, height). The sim map
        reaches past it on some scenarios (terrain.json `print`)."""
        p = self.terrain.get("print")
        if not p:
            return 0, 0, self.width, self.height
        x0, y0 = p["offset_cells"]
        return x0, y0, p["width"], p["height"]


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
