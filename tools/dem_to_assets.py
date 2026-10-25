# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "manifold3d>=3.0",
#     "numpy>=2.0",
#     "opencv-python-headless>=4.7",
#     "pillow>=10.0",
#     "pydantic>=2.0",
#     "pyyaml>=6.0",
#     "scipy>=1.13",
# ]
# ///
"""DEM -> scenario terrain assets: sim heightmap, printable STL tiles, preview.

This is the single source of truth for terrain (PLAN.md, Pre-Event Prep). The
sim heightmap and the STLs are cut from the same processed height field, so the
sim and the print can't drift apart. Never edit the outputs by hand.

    uv run tools/dem_to_assets.py assets/scenarios/paradise/terrain.yaml
    uv run tools/dem_to_assets.py assets/scenarios/paradise/terrain.yaml \\
        --set model.width_mm=300 --set tiles.cols=3 --no-stl

Elevation comes from AWS Terrain Tiles (Terrarium PNGs, no API key; USGS 3DEP
in the US). Tiles are cached in tools/.cache/.

The sim map can reach past the print (sim.margin_km): fire, roads and towns
carry on beyond the printed terrain, so the fire doesn't stop dead at the
board's edge. `region` and `model` describe only the print, so the print stays
the same when the margins change; the print is a window in the sim grid at
terrain.json's `print.offset_cells`. Inside it the sim heightmap is cut from
the print's own height field, outside it from the same DEM processed the same
way.

Frames:
  board mm  x east, y north, z up; origin at the print's south-west bottom corner.
  map grid  col = ox + x_mm / width_mm * w, row = oy + (height_mm - y_mm) / height_mm * h,
            where (ox, oy) is print.offset_cells and w x h the print's size in cells.
            Row 0 is north. Cell (r, c) spans [c, c+1) x [r, r+1).
"""

import argparse
import copy
import io
import json
import math
import sys
import urllib.request
import uuid
import zipfile
from pathlib import Path

import cv2
import manifold3d as mf
import numpy as np
import yaml
from PIL import Image, ImageDraw
from scipy import ndimage

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))
from vision.markers import CORNER_IDS, DICTIONARY  # noqa: E402

CACHE = REPO / "tools" / ".cache" / "terrarium"
TILE_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
EARTH_R = 6371008.8

DEFAULTS = {
    "name": None,
    "region": {
        "center": None,  # [lat, lon]
        "width_km": None,  # east-west extent; north-south follows the model aspect
        "zoom": 13,  # Terrarium zoom; 13 is ~15 m/px at 40° lat
    },
    "model": {
        "width_mm": 400,
        "height_mm": 300,
        "base_mm": 6.0,  # solid floor under the lowest terrain point
        "max_relief_mm": 35.0,  # lowest -> highest point; sets vertical exaggeration
        "vertical_exaggeration": None,  # set to override max_relief_mm
        "resolution_mm": 0.5,  # mesh vertex spacing
        "smooth_mm": 0.75,  # gaussian sigma, removes DEM noise and stair-stepping
    },
    "tiles": {
        "cols": 2,
        "rows": 2,
        "bed_mm": [256, 256],  # only used to warn when a tile won't fit
        "pins": {
            "per_edge": 2,  # per tile edge on each seam; 0 disables
            "hole_diameter_mm": 2.0,  # fits 1.75 mm filament as pins
            "depth_mm": 6.0,  # into each tile
        },
    },
    "markers": {
        # Calibration markers sit on separate corner holders outside the terrain,
        # pinned into the board's outer walls. One holder STL fits every corner.
        "enabled": True,
        "size_mm": 30.0,  # ArUco square, including its one-cell white border
        # true: the marker is printed into the holder top (white body, black cells
        # inlaid flush), one two-colour 3MF for an AMS. false: a pocket for paper.
        "printed": True,
        "inlay_mm": 0.6,  # depth of the black cells, a few layers so white can't show through
        "clearance_mm": 0.4,  # per side of the paper pocket
        "depth_mm": 1.0,  # paper pocket depth
        "rim_mm": 3.0,  # holder pad around the pocket
        "arm_length_mm": 30.0,  # along each board wall from the corner
        "arm_width_mm": 8.0,
    },
    "sim": {
        "grid_width": 256,  # cells across the print, which sets the cell size; its height follows the model aspect
        # How far the sim map reaches past the print on each side, rounded to
        # whole cells. Zero: the sim map is the print.
        "margin_km": {"north": 0, "east": 0, "south": 0, "west": 0},
    },
    "places": [],  # [{name, lat, lon}], reported in map coords and drawn on the preview
}


# ---------------------------------------------------------------- config


def deep_merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        out[k] = deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def apply_override(cfg, expr):
    key, sep, raw = expr.partition("=")
    if not sep:
        sys.exit(f"--set expects key=value, got {expr!r}")
    *parents, leaf = key.split(".")
    node = cfg
    for p in parents:
        node = node.setdefault(p, {})
    node[leaf] = yaml.safe_load(raw)


def load_config(path, overrides):
    cfg = deep_merge(DEFAULTS, yaml.safe_load(Path(path).read_text()))
    for expr in overrides:
        apply_override(cfg, expr)
    if not cfg["name"]:
        cfg["name"] = Path(path).parent.name
    if cfg["region"]["center"] is None or cfg["region"]["width_km"] is None:
        sys.exit("region.center and region.width_km are required")
    m, t = cfg["model"], cfg["tiles"]
    pinned = t["pins"]["per_edge"] or cfg["markers"]["enabled"]
    if pinned and m["base_mm"] < t["pins"]["hole_diameter_mm"] + 2:
        sys.exit("model.base_mm must be at least pin hole diameter + 2 mm")
    mk = cfg["markers"]
    if mk["enabled"] and m["base_mm"] <= (mk["inlay_mm"] if mk["printed"] else mk["depth_mm"]):
        sys.exit("model.base_mm must be deeper than the marker inlay or pocket")
    return cfg


# ---------------------------------------------------------------- DEM


def mercator_px(lat, lon, zoom):
    n = 256 * 2**zoom
    lat_r = np.radians(lat)
    x = (np.asarray(lon) + 180.0) / 360.0 * n
    y = (1.0 - np.log(np.tan(lat_r) + 1.0 / np.cos(lat_r)) / math.pi) / 2.0 * n
    return x, y


def fetch_tile(z, x, y):
    path = CACHE / str(z) / str(x) / f"{y}.png"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(TILE_URL.format(z=z, x=x, y=y), headers={"User-Agent": "fireline-dem"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
        path.write_bytes(data)
    rgb = np.asarray(Image.open(io.BytesIO(path.read_bytes())).convert("RGB"), dtype=np.float64)
    return rgb[..., 0] * 256 + rgb[..., 1] + rgb[..., 2] / 256 - 32768


def sample_dem(lat, lon, zoom):
    """Bilinear elevation (m) at arrays of lat/lon, from Terrarium tiles."""
    px, py = mercator_px(lat, lon, zoom)
    tx0, tx1 = int(px.min() // 256), int(px.max() // 256)
    ty0, ty1 = int(py.min() // 256), int(py.max() // 256)
    count = (tx1 - tx0 + 1) * (ty1 - ty0 + 1)
    print(f"  {count} tiles at zoom {zoom}")
    mosaic = np.block([[fetch_tile(zoom, tx, ty) for tx in range(tx0, tx1 + 1)] for ty in range(ty0, ty1 + 1)])
    # Pixel centers sit at +0.5.
    coords = [py - ty0 * 256 - 0.5, px - tx0 * 256 - 0.5]
    return ndimage.map_coordinates(mosaic, coords, order=1, mode="nearest")


def mm_to_latlon(x_mm, y_mm, cfg, m_per_mm):
    lat0, lon0 = cfg["region"]["center"]
    east = (x_mm - cfg["model"]["width_mm"] / 2) * m_per_mm
    north = (y_mm - cfg["model"]["height_mm"] / 2) * m_per_mm
    lat = lat0 + np.degrees(north / EARTH_R)
    lon = lon0 + np.degrees(east / (EARTH_R * math.cos(math.radians(lat0))))
    return lat, lon


def latlon_to_mm(lat, lon, cfg, m_per_mm):
    lat0, lon0 = cfg["region"]["center"]
    north = math.radians(lat - lat0) * EARTH_R
    east = math.radians(lon - lon0) * EARTH_R * math.cos(math.radians(lat0))
    return east / m_per_mm + cfg["model"]["width_mm"] / 2, north / m_per_mm + cfg["model"]["height_mm"] / 2


# ---------------------------------------------------------------- height field


def build_height_field(cfg, window=None):
    """The print's height field, or with `window` (x0, y0, x1, y1 in board mm)
    the DEM over that rectangle at the same spacing and smoothing, elevation
    only."""
    m = cfg["model"]
    W, H = m["width_mm"], m["height_mm"]
    m_per_mm = cfg["region"]["width_km"] * 1000 / W
    nx = round(W / m["resolution_mm"]) + 1
    ny = round(H / m["resolution_mm"]) + 1
    res = W / (nx - 1)
    if window is not None:
        x0, y0, x1, y1 = window
        nx, ny = round((x1 - x0) / res) + 1, round((y1 - y0) / res) + 1
        xs, ys = np.meshgrid(np.linspace(x0, x1, nx), np.linspace(y1, y0, ny))
        lat, lon = mm_to_latlon(xs, ys, cfg, m_per_mm)
        print(f"Sampling the sim margins over {lat.min():.4f}..{lat.max():.4f} N, {lon.min():.4f}..{lon.max():.4f} E")
        elev = sample_dem(lat, lon, cfg["region"]["zoom"])
        if m["smooth_mm"] > 0:
            elev = ndimage.gaussian_filter(elev, m["smooth_mm"] / ((x1 - x0) / (nx - 1)), mode="nearest")
        return {"elev": elev, "res": (x1 - x0) / (nx - 1), "origin_mm": (x0, y1)}
    xs, ys = np.meshgrid(np.linspace(0, W, nx), np.linspace(H, 0, ny))  # row 0 = north

    lat, lon = mm_to_latlon(xs, ys, cfg, m_per_mm)
    print(f"Sampling DEM over {lat.min():.4f}..{lat.max():.4f} N, {lon.min():.4f}..{lon.max():.4f} E")
    elev = sample_dem(lat, lon, cfg["region"]["zoom"])
    if m["smooth_mm"] > 0:
        elev = ndimage.gaussian_filter(elev, m["smooth_mm"] / res, mode="nearest")

    lo, hi = float(elev.min()), float(elev.max())
    if m["vertical_exaggeration"]:
        exaggeration = float(m["vertical_exaggeration"])
    else:
        exaggeration = m["max_relief_mm"] * m_per_mm / max(hi - lo, 1e-6)
    z_per_m = exaggeration / m_per_mm
    z_mm = m["base_mm"] + (elev - lo) * z_per_m
    return {
        "elev": elev, "z_mm": z_mm, "xs": xs, "ys": ys, "res": res,
        "m_per_mm": m_per_mm, "exaggeration": exaggeration, "z_per_m": z_per_m,
        "elev_min": lo, "elev_max": hi, "origin_mm": (0.0, H),
    }  # fmt: skip


# ---------------------------------------------------------------- mesh


def heightfield_solid(z_mm, xs, ys):
    """Watertight solid: terrain top, vertical walls, flat bottom at z=0."""
    ny, nx = z_mm.shape
    top = np.column_stack([xs.ravel(), ys.ravel(), z_mm.ravel()])
    idx = np.arange(ny * nx).reshape(ny, nx)
    a, b = idx[:-1, :-1].ravel(), idx[:-1, 1:].ravel()
    c, d = idx[1:, :-1].ravel(), idx[1:, 1:].ravel()
    tris = [np.column_stack([a, c, d]), np.column_stack([a, d, b])]

    # Boundary loop, counter-clockwise seen from above (row 0 is north).
    loop = np.concatenate([
        idx[-1, :],  # south, west -> east
        idx[-2::-1, -1],  # east, south -> north
        idx[0, -2::-1],  # north, east -> west
        idx[1:-1, 0],  # west, north -> south
    ])  # fmt: skip
    n = len(top)
    bottom = top[loop].copy()
    bottom[:, 2] = 0
    centre = [[xs.max() / 2, ys.max() / 2, 0]]
    t0, t1 = loop, np.roll(loop, -1)
    b0 = n + np.arange(len(loop))
    b1 = np.roll(b0, -1)
    cb = np.full_like(b0, n + len(loop))
    tris += [np.column_stack([t0, b0, b1]), np.column_stack([t0, b1, t1]), np.column_stack([cb, b1, b0])]

    verts = np.vstack([top, bottom, centre]).astype(np.float32)
    solid = mf.Manifold(mf.Mesh(vert_properties=verts, tri_verts=np.vstack(tris).astype(np.uint32)))
    if solid.status() != mf.Error.NoError:
        sys.exit(f"terrain mesh is not manifold: {solid.status()}")
    return solid


def pin_holes(cfg):
    m, t = cfg["model"], cfg["tiles"]
    pins = t["pins"]
    if not pins["per_edge"]:
        return []
    tw, th = m["width_mm"] / t["cols"], m["height_mm"] / t["rows"]
    r, length, z = pins["hole_diameter_mm"] / 2, 2 * pins["depth_mm"], m["base_mm"] / 2
    fracs = (np.arange(pins["per_edge"]) + 0.5) / pins["per_edge"]
    cyl = mf.Manifold.cylinder(length, r, circular_segments=24, center=True)
    holes = []
    for j in range(1, t["cols"]):  # vertical seams: holes run east-west
        for i in range(t["rows"]):
            for f in fracs:
                holes.append(cyl.rotate([0, 90, 0]).translate([j * tw, (i + f) * th, z]))
    for i in range(1, t["rows"]):  # horizontal seams: holes run north-south
        for j in range(t["cols"]):
            for f in fracs:
                holes.append(cyl.rotate([90, 0, 0]).translate([(j + f) * tw, i * th, z]))
    return holes


def corners(cfg):
    """(name, rotation_deg, corner_xy) per board corner, ordered NW, NE, SE, SW.

    Holder geometry is modelled at the SW corner (board in +x, +y); rotating it
    about z by rotation_deg and moving it to corner_xy fits it to that corner.
    """
    W, H = cfg["model"]["width_mm"], cfg["model"]["height_mm"]
    return [("NW", 270, (0, H)), ("NE", 180, (W, H)), ("SE", 90, (W, 0)), ("SW", 0, (0, 0))]


def corner_to_board(xy, rot, corner):
    a = math.radians(rot)
    x, y = xy
    return corner[0] + x * math.cos(a) - y * math.sin(a), corner[1] + x * math.sin(a) + y * math.cos(a)


def holder_dims(cfg):
    mk = cfg["markers"]
    pocket = mk["size_mm"] + 2 * mk["clearance_mm"]
    return pocket, pocket + 2 * mk["rim_mm"]  # pocket side, pad side


def marker_centre_local(cfg):
    _, pad = holder_dims(cfg)
    return -pad / 2, -pad / 2


def holder_pin_holes_local(cfg, length):
    """Two horizontal holes at the SW corner: one into each outer wall."""
    mk, z = cfg["markers"], cfg["model"]["base_mm"] / 2
    r = cfg["tiles"]["pins"]["hole_diameter_mm"] / 2
    cyl = mf.Manifold.cylinder(length, r, circular_segments=24, center=True)
    along = mk["arm_length_mm"] / 2
    return [cyl.rotate([90, 0, 0]).translate([along, 0, z]), cyl.rotate([0, 90, 0]).translate([0, along, z])]


def board_holder_holes(cfg):
    depth = cfg["tiles"]["pins"]["depth_mm"]
    holes = []
    for _, rot, corner in corners(cfg):
        for h in holder_pin_holes_local(cfg, 2 * depth):
            holes.append(h.rotate([0, 0, rot]).translate([corner[0], corner[1], 0]))
    return holes


def build_holder(cfg):
    """L-shaped bracket that hugs a board corner from outside, with a marker pad on the diagonal."""
    mk, h = cfg["markers"], cfg["model"]["base_mm"]
    pocket, pad = holder_dims(cfg)
    L, w = mk["arm_length_mm"], mk["arm_width_mm"]
    body = mf.Manifold.batch_boolean([
        mf.Manifold.cube([pad, pad, h]).translate([-pad, -pad, 0]),
        mf.Manifold.cube([L, w, h]).translate([0, -w, 0]),  # along the south wall
        mf.Manifold.cube([w, L, h]).translate([-w, 0, 0]),  # along the west wall
    ], mf.OpType.Add)  # fmt: skip
    # Through-holes across each arm (and a little past, into the air beside the board).
    cuts = holder_pin_holes_local(cfg, 2 * w + 2)
    if not mk["printed"]:
        cuts.append(mf.Manifold.cube([pocket, pocket, mk["depth_mm"] + 1]).translate([-pad + mk["rim_mm"], -pad + mk["rim_mm"], h - mk["depth_mm"]]))
    return body - mf.Manifold.batch_boolean(cuts, mf.OpType.Add)


def marker_inlay(cfg, marker_id, rot):
    """The black cells of an ArUco marker as a solid flush with the holder top, in holder-local mm.

    Drawn upright in the board frame (top edge to the north), so it's turned by
    -rot here and the holder's rotation brings it back.
    """
    mk, h = cfg["markers"], cfg["model"]["base_mm"]
    cells = 6  # 4x4 data bits plus the black border, inside a one-cell white quiet zone
    bits = cv2.aruco.generateImageMarker(cv2.aruco.getPredefinedDictionary(DICTIONARY), marker_id, cells) < 128
    cell = mk["size_mm"] / (cells + 2)
    cx, cy = marker_centre_local(cfg)
    a = math.radians(-rot)
    eps = 1e-3  # cells that only touch diagonally would otherwise share a non-manifold edge
    squares = []
    for r, c in zip(*np.nonzero(bits)):
        u, v = (c + 0.5 - cells / 2) * cell, (cells / 2 - r - 0.5) * cell  # row 0 is the top (north)
        x, y = cx + u * math.cos(a) - v * math.sin(a), cy + u * math.sin(a) + v * math.cos(a)
        squares.append(mf.CrossSection.square([cell + eps, cell + eps], center=True).translate([x, y]))
    return mf.CrossSection.batch_boolean(squares, mf.OpType.Add).extrude(mk["inlay_mm"]).translate([0, 0, h - mk["inlay_mm"]])


def write_3mf(path, objects, bed_mm):
    """Bambu Studio project: one object per (name, [(part name, solid, filament)]), laid out on the plate.

    The layout follows what Bambu Studio itself writes (meshes in 3D/Objects,
    filament per part in Metadata/model_settings.config). Other slicers read it
    as a plain 3MF with multi-part objects.
    """
    files, root_objs, items, settings, instances = {}, [], [], [], []
    cols = math.ceil(math.sqrt(len(objects)))
    boxes = [np.array([s.bounding_box() for _, s, _ in parts]) for _, parts in objects]
    lo_all = [b[:, :3].min(axis=0) for b in boxes]
    hi_all = [b[:, 3:].max(axis=0) for b in boxes]
    step = max(float((hi - lo)[:2].max()) for lo, hi in zip(lo_all, hi_all)) + 8
    # Packed together, a little toward the front left: the wipe tower sits at the back right.
    x0, y0 = bed_mm[0] / 2 - 20 - (cols - 1) * step / 2, bed_mm[1] / 2 - 20 + (cols - 1) * step / 2
    next_id = 1  # Bambu Studio shares meshes by sub-object id across files, so ids must be unique
    for k, (name, parts) in enumerate(objects):
        sub, comps, part_cfg = [], [], []
        sub_path = f"/3D/Objects/object_{k + 1}.model"
        lo, hi = lo_all[k], hi_all[k]
        for part_name, solid, filament in parts:
            part_id, next_id = next_id, next_id + 1
            mesh = solid.to_mesh()
            verts = np.asarray(mesh.vert_properties)[:, :3]
            tris = np.asarray(mesh.tri_verts)
            vx = "\n".join(f'     <vertex x="{x:.4f}" y="{y:.4f}" z="{z:.4f}"/>' for x, y, z in verts)
            tx = "\n".join(f'     <triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in tris)
            sub.append(f'  <object id="{part_id}" p:UUID="{uuid.uuid4()}" type="model">\n   <mesh>\n    <vertices>\n{vx}\n    </vertices>\n    <triangles>\n{tx}\n    </triangles>\n   </mesh>\n  </object>')
            comps.append(f'    <component p:path="{sub_path}" objectid="{part_id}" p:UUID="{uuid.uuid4()}" transform="1 0 0 0 1 0 0 0 1 0 0 0"/>')
            part_cfg.append(
                f'    <part id="{part_id}" subtype="normal_part">\n'
                f'      <metadata key="name" value="{part_name}"/>\n'
                f'      <metadata key="matrix" value="1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"/>\n'
                f'      <metadata key="extruder" value="{filament}"/>\n'
                "    </part>"
            )  # fmt: skip
        files[sub_path] = sub
        oid = 1000 + k
        root_objs.append(f'  <object id="{oid}" p:UUID="{uuid.uuid4()}" type="model">\n   <components>\n' + "\n".join(comps) + "\n   </components>\n  </object>")
        r, c = divmod(k, cols)
        tx_, ty_ = x0 + c * step - (lo[0] + hi[0]) / 2, y0 - r * step - (lo[1] + hi[1]) / 2
        items.append(f'  <item objectid="{oid}" p:UUID="{uuid.uuid4()}" transform="1 0 0 0 1 0 0 0 1 {tx_:.3f} {ty_:.3f} {0.0 - lo[2]:.3f}" printable="1"/>')
        instances.append(f'    <model_instance>\n      <metadata key="object_id" value="{oid}"/>\n      <metadata key="instance_id" value="0"/>\n    </model_instance>')
        settings.append(f'  <object id="{oid}">\n    <metadata key="name" value="{name}"/>\n    <metadata key="extruder" value="1"/>\n' + "\n".join(part_cfg) + "\n  </object>")
    ns = 'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" xmlns:BambuStudio="http://schemas.bambulab.com/package/2021" xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06" requiredextensions="p"'
    head = '<?xml version="1.0" encoding="UTF-8"?>\n'
    root = (
        f'{head}<model unit="millimeter" xml:lang="en-US" {ns}>\n'
        # Bambu Studio only reads the per-part filaments from files it thinks it wrote.
        ' <metadata name="Application">BambuStudio-02.08.02.61</metadata>\n <metadata name="BambuStudio:3mfVersion">1</metadata>\n <resources>\n'
        + "\n".join(root_objs) + f'\n </resources>\n <build p:UUID="{uuid.uuid4()}">\n' + "\n".join(items) + "\n </build>\n</model>\n"
    )  # fmt: skip
    rel = '<Relationship Target="{}" Id="rel-{}" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>'
    rels = head + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n {}\n</Relationships>\n'
    types = (
        f'{head}<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
        ' <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n'
        ' <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>\n'
        " <Default Extension=\"config\" ContentType=\"text/xml\"/>\n</Types>\n"
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", types)
        z.writestr("_rels/.rels", rels.format(rel.format("/3D/3dmodel.model", 1)))
        z.writestr("3D/_rels/3dmodel.model.rels", rels.format("\n ".join(rel.format(f, i) for i, f in enumerate(files, 1))))
        z.writestr("3D/3dmodel.model", root)
        for f, sub in files.items():
            z.writestr(f[1:], f'{head}<model unit="millimeter" xml:lang="en-US" {ns}>\n <resources>\n' + "\n".join(sub) + "\n </resources>\n <build/>\n</model>\n")
        plate = '  <plate>\n    <metadata key="plater_id" value="1"/>\n' + "\n".join(instances) + "\n  </plate>"
        z.writestr("Metadata/model_settings.config", f"{head}<config>\n" + "\n".join(settings) + f"\n{plate}\n</config>\n")


def write_stl(path, solid):
    mesh = solid.to_mesh()
    tri = np.asarray(mesh.vert_properties)[:, :3][np.asarray(mesh.tri_verts)]
    normal = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    normal /= np.linalg.norm(normal, axis=1, keepdims=True) + 1e-12
    rec = np.zeros(len(tri), dtype=[("n", "<f4", 3), ("v", "<f4", (3, 3)), ("attr", "<u2")])
    rec["n"], rec["v"] = normal, tri
    with open(path, "wb") as f:
        f.write(b"fireline dem_to_assets".ljust(80, b" "))
        f.write(np.uint32(len(tri)).tobytes())
        f.write(rec.tobytes())
    return len(tri)


def tile_layout(cfg):
    """The print tiles, row 0 = north, matching the map grid."""
    m, t = cfg["model"], cfg["tiles"]
    tw, th = m["width_mm"] / t["cols"], m["height_mm"] / t["rows"]
    return [
        {"file": f"tile_r{i}_c{j}.stl", "row": i, "col": j, "origin_mm": [j * tw, m["height_mm"] - (i + 1) * th], "size_mm": [tw, th]}
        for i in range(t["rows"]) for j in range(t["cols"])
    ]  # fmt: skip


def build_tiles(cfg, hf, out_dir, write_board):
    m, t = cfg["model"], cfg["tiles"]
    print("Building mesh")
    board = heightfield_solid(hf["z_mm"], hf["xs"], hf["ys"])
    cutters = pin_holes(cfg) + (board_holder_holes(cfg) if cfg["markers"]["enabled"] else [])
    if cutters:
        board = board - mf.Manifold.batch_boolean(cutters, mf.OpType.Add)

    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.stl"):
        old.unlink()
    if write_board:
        write_stl(out_dir / "board.stl", board)

    tw, th = m["width_mm"] / t["cols"], m["height_mm"] / t["rows"]
    tall = m["base_mm"] + m["max_relief_mm"] * 10 + 100
    bx, by = t["bed_mm"]
    if not ((tw <= bx and th <= by) or (tw <= by and th <= bx)):
        print(f"  WARNING: {tw:.0f}x{th:.0f} mm tiles may not fit a {t['bed_mm']} mm bed")
    tiles = tile_layout(cfg)
    for tile in tiles:
        x0, y0 = tile["origin_mm"]
        box = mf.Manifold.cube([tw, th, tall]).translate([x0, y0, -1])
        n = write_stl(out_dir / tile["file"], (board ^ box).translate([-x0, -y0, 0]))
        print(f"  {tile['file']}: {n:,} triangles")
    if cfg["markers"]["enabled"]:
        holder = build_holder(cfg)
        write_stl(out_dir / "marker_holder.stl", holder)
        if cfg["markers"]["printed"]:
            objects = []
            for name, rot, _ in corners(cfg):
                inlay = marker_inlay(cfg, CORNER_IDS[name], rot)
                objects.append((f"holder_{name}", [("white", holder - inlay, 1), (f"marker {CORNER_IDS[name]}", inlay, 2)]))
            write_3mf(out_dir / "marker_holders.3mf", objects, t["bed_mm"])
            print("  marker_holders.3mf: the four corner holders, white body (filament 1) + black marker (filament 2)")
        else:
            print("  marker_holder.stl: print 4")
    return tiles


# ---------------------------------------------------------------- sim + preview


def print_cells(cfg):
    """The print's size in sim cells (w, h), and the cell size in mm."""
    m = cfg["model"]
    w = cfg["sim"]["grid_width"]
    return w, round(w * m["height_mm"] / m["width_mm"]), m["width_mm"] / w


def margin_cells(cfg, m_per_mm):
    """sim.margin_km in whole cells: {north, east, south, west}."""
    _, _, cell_mm = print_cells(cfg)
    km = cfg["sim"]["margin_km"]
    return {side: round(km.get(side, 0) * 1000 / (cell_mm * m_per_mm)) for side in ("north", "east", "south", "west")}


def sample_grid(hf, shape, cell_mm, origin_mm):
    """Elevation at the centres of a `shape` grid of cells whose north-west
    corner sits at `origin_mm` (board mm)."""
    smooth = ndimage.gaussian_filter(hf["elev"], 0.5 * cell_mm / hf["res"], mode="nearest")
    hx, hy = hf["origin_mm"]  # the height field's north-west corner
    rows = (hy - origin_mm[1] + (np.arange(shape[0]) + 0.5) * cell_mm) / hf["res"]
    cols = (origin_mm[0] - hx + (np.arange(shape[1]) + 0.5) * cell_mm) / hf["res"]
    rr, cc = np.meshgrid(rows, cols, indexing="ij")
    return ndimage.map_coordinates(smooth, [rr, cc], order=1, mode="nearest").astype(np.float32)


def sim_heightmap(cfg, hf):
    """Elevation in metres on the sim grid, sampled at cell centres: the print
    window from the print's height field, the margins from the DEM around it.
    Returns the heightmap, the cell size in mm, the print's offset in cells
    (ox, oy), and the margins' height field (None without margins)."""
    m = cfg["model"]
    w, h, cell_mm = print_cells(cfg)
    inner = sample_grid(hf, (h, w), cell_mm, (0.0, m["height_mm"]))
    mc = margin_cells(cfg, hf["m_per_mm"])
    if not any(mc.values()):
        return inner, cell_mm, (0, 0), None
    W, H = w + mc["west"] + mc["east"], h + mc["north"] + mc["south"]
    x0, y1 = -mc["west"] * cell_mm, m["height_mm"] + mc["north"] * cell_mm
    window = (x0, y1 - H * cell_mm, x0 + W * cell_mm, y1)
    outer = build_height_field(cfg, window)
    heightmap = sample_grid(outer, (H, W), cell_mm, (x0, y1))
    ox, oy = mc["west"], mc["north"]
    heightmap[oy:oy + h, ox:ox + w] = inner
    return heightmap, cell_mm, (ox, oy), outer


def to_map(x_mm, y_mm, cfg, offset):
    m = cfg["model"]
    w, h, _ = print_cells(cfg)
    return [offset[0] + x_mm / m["width_mm"] * w, offset[1] + (m["height_mm"] - y_mm) / m["height_mm"] * h]


def hillshade(elev, cell_m, azimuth=315, altitude=45):
    gy, gx = np.gradient(elev, cell_m)
    slope = np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    az, alt = np.radians(azimuth), np.radians(altitude)
    return np.clip(np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(az - aspect), 0, 1)


def write_preview(path, cfg, hf, tiles, places, outer=None, px_per_mm=2):
    """Hillshade with tile seams and places; with sim margins (`outer`), the
    whole sim map with the print's outline on it."""
    m = cfg["model"]
    src = outer if outer is not None else hf
    step = max(1, round(1 / (px_per_mm * src["res"])))
    elev = src["elev"][::step, ::step]
    shade = hillshade(elev, src["res"] * step * hf["m_per_mm"] / hf["exaggeration"])
    lo, hi = float(src["elev"].min()), float(src["elev"].max())
    t = (elev - lo) / max(hi - lo, 1e-6)
    stops = np.array([[0.36, 0.55, 0.36], [0.78, 0.74, 0.50], [0.62, 0.45, 0.32], [0.95, 0.95, 0.95]])
    pos = np.linspace(0, 1, len(stops))
    tint = np.stack([np.interp(t, pos, stops[:, k]) for k in range(3)], axis=-1)
    rgb = (tint * (0.35 + 0.65 * shade[..., None]) * 255).astype(np.uint8)

    img = Image.fromarray(rgb)
    draw = ImageDraw.Draw(img)
    hx, hy = src["origin_mm"]  # north-west corner, board mm
    s = 1 / (src["res"] * step)

    def px(x, y):
        return (x - hx) * s, (hy - y) * s

    if outer is not None:
        draw.rectangle([px(0, m["height_mm"]), px(m["width_mm"], 0)], outline=(255, 255, 255), width=3)

    for tile in tiles:
        x0, y0 = tile["origin_mm"]
        w, h = tile["size_mm"]
        draw.rectangle([px(x0, y0 + h), px(x0 + w, y0)], outline=(40, 40, 40), width=1)
    for p in places:
        x, y = px(*p["mm"])
        draw.ellipse([x - 4, y - 4, x + 4, y + 4], fill=(220, 40, 30), outline=(255, 255, 255))
        draw.text((x + 7, y - 6), p["name"], fill=(15, 15, 15))
    img.save(path)


# ---------------------------------------------------------------- main


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("config", help="scenario terrain.yaml")
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE", help="override a config value, e.g. tiles.cols=3")
    ap.add_argument("--no-stl", action="store_true", help="skip mesh generation (fast iteration on the sim side)")
    ap.add_argument("--board", action="store_true", help="also write the untiled board.stl")
    args = ap.parse_args()

    cfg = load_config(args.config, args.set)
    scenario_dir = REPO / "assets" / "scenarios" / cfg["name"]
    stl_dir = REPO / "assets" / "stl" / cfg["name"]
    scenario_dir.mkdir(parents=True, exist_ok=True)

    hf = build_height_field(cfg)
    m = cfg["model"]
    print(
        f"Relief {hf['elev_max'] - hf['elev_min']:.0f} m -> "
        f"{(hf['elev_max'] - hf['elev_min']) * hf['z_per_m']:.1f} mm, "
        f"horizontal 1 mm = {hf['m_per_mm']:.1f} m, vertical exaggeration {hf['exaggeration']:.2f}x"
    )

    heightmap, cell_mm, offset, outer = sim_heightmap(cfg, hf)
    np.save(scenario_dir / "heightmap.npy", heightmap)
    pw, ph, _ = print_cells(cfg)
    if outer is not None:
        print(f"Sim map {heightmap.shape[1]}x{heightmap.shape[0]} cells, the print at {offset} ({pw}x{ph})")

    tiles = tile_layout(cfg) if args.no_stl else build_tiles(cfg, hf, stl_dir, args.board)

    places = []
    for p in cfg["places"]:
        x, y = latlon_to_mm(p["lat"], p["lon"], cfg, hf["m_per_mm"])
        places.append({**p, "mm": [round(x, 2), round(y, 2)], "map": [round(v, 2) for v in to_map(x, y, cfg, offset)]})

    markers = {}
    if cfg["markers"]["enabled"]:
        mk = cfg["markers"]
        markers = {
            "holder_file": "marker_holder.stl",
            "marker_size_mm": mk["size_mm"],
            "printed": mk["printed"],
            "marker_top_z_mm": float(m["base_mm"] if mk["printed"] else m["base_mm"] - mk["depth_mm"]),
            "pin_length_mm": mk["arm_width_mm"] + cfg["tiles"]["pins"]["depth_mm"],
            "note": "Centres are outside the terrain, so map coords fall outside the grid.",
            "corners": [],
        }
        for name, rot, corner in corners(cfg):
            cx, cy = corner_to_board(marker_centre_local(cfg), rot, corner)
            markers["corners"].append({
                "corner": name,
                "center_mm": [round(cx, 3), round(cy, 3)],
                "center_map": [round(v, 3) for v in to_map(cx, cy, cfg, offset)],
                "holder_rotation_deg": rot,
                "holder_origin_mm": list(corner),
            })  # fmt: skip

    def corners_latlon(x0, y0, x1, y1):
        (s, w), (n, e) = (mm_to_latlon(x, y, cfg, hf["m_per_mm"]) for x, y in [(x0, y0), (x1, y1)])
        return {"south": s, "west": w, "north": n, "east": e}

    ox, oy = offset
    H, W = heightmap.shape
    top = m["height_mm"] + oy * cell_mm
    sim_bounds = corners_latlon(-ox * cell_mm, top - H * cell_mm, (W - ox) * cell_mm, top)
    elev_all = outer["elev"] if outer is not None else hf["elev"]
    meta = {
        "name": cfg["name"],
        "generated_by": "tools/dem_to_assets.py",
        "source": "AWS Terrain Tiles (Terrarium), USGS 3DEP in the US",
        # The sim map. With sim margins it reaches past the print (`print`).
        "bounds": sim_bounds,
        "grid": {"width": W, "height": H, "cell_size_m": cell_mm * hf["m_per_mm"], "cell_size_mm": cell_mm},
        "heightmap": {"file": "heightmap.npy", "dtype": "float32", "units": "m above sea level", "row0": "north"},
        "elevation_m": {"min": float(elev_all.min()), "max": float(elev_all.max())},
        # The printed terrain: a window of the sim grid.
        "print": {
            "offset_cells": [ox, oy], "width": pw, "height": ph,
            "bounds": corners_latlon(0, 0, m["width_mm"], m["height_mm"]),
        },  # fmt: skip
        "model": {
            "width_mm": m["width_mm"], "height_mm": m["height_mm"], "base_mm": m["base_mm"],
            "relief_mm": (hf["elev_max"] - hf["elev_min"]) * hf["z_per_m"],
            "m_per_mm": hf["m_per_mm"], "vertical_exaggeration": hf["exaggeration"],
            # The print's lowest and highest points: base_mm and base_mm + relief_mm.
            "elevation_m": {"min": hf["elev_min"], "max": hf["elev_max"]},
        },  # fmt: skip
        "frames": {
            "board_mm": "x east, y north, origin at the print's south-west corner",
            "map": "col = print.offset_cells[0] + x_mm / width_mm * print.width, "
                   "row = print.offset_cells[1] + (height_mm - y_mm) / height_mm * print.height",
        },
        "markers": markers,
        "tiles": tiles,
        "places": places,
        "config": cfg,
    }
    (scenario_dir / "terrain.json").write_text(json.dumps(meta, indent=2) + "\n")
    write_preview(scenario_dir / "preview.png", cfg, hf, tiles, places, outer)

    print(f"Wrote {scenario_dir.relative_to(REPO)}/{{heightmap.npy, terrain.json, preview.png}}")
    if not args.no_stl:
        print(f"Wrote {len(tiles)} tiles to {stl_dir.relative_to(REPO)}/")


if __name__ == "__main__":
    main()
