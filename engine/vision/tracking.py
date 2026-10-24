"""Raw per-frame marker sightings -> steady tokens.

- Debounce: a token counts as placed after APPEAR_FRAMES frames in a row, and
  as removed after VANISH_FRAMES frames missing (a hand passing over it, or
  fire light washing out the marker, doesn't remove it).
- Smoothing: positions and angles are low-passed, but a jump larger than
  SNAP_CELLS (picked up and set down elsewhere) is taken at once.
- Deadband: the reported pose only changes when the smoothed one moves past
  DEADBAND_*, so a token sitting still doesn't re-broadcast every frame.

Token IDs are "m<marker id>", stable across sightings, so sim effects (a crew
digging in, a water cooldown) survive a token briefly going missing.
"""

import math
from dataclasses import dataclass


from protocol import Token, TokenSource
from vision.calibration import BoardHomography
from vision.markers import Detection, token_type_for

APPEAR_FRAMES = 3
VANISH_FRAMES = 15  # ~0.5 s at 30 fps
SMOOTHING = 0.35  # weight of each new sighting
SNAP_CELLS = 3.0
DEADBAND_CELLS = 0.1
DEADBAND_RAD = math.radians(1.5)


@dataclass
class Sighting:
    x: float  # map coords
    y: float
    angle: float  # radians clockwise from +x, as Token.angle


def measure(detections: list[Detection], board: BoardHomography) -> dict[int, Sighting]:
    """Token markers in this frame, in map coords. Needs a solved homography."""
    out = {}
    for d in detections:
        if token_type_for(d.id) is None:
            continue
        tl, tr, br, bl = board.to_map(d.corners)
        cx, cy = board.to_map(d.center[None])[0]
        # The marker's +x edge direction. Map y points south, so atan2 gives
        # the angle clockwise from +x, which is Token's convention.
        vx, vy = (tr - tl) + (br - bl)
        out[d.id] = Sighting(float(cx), float(cy), math.atan2(vy, vx))
    return out


@dataclass
class _Track:
    x: float
    y: float
    ux: float  # smoothed unit direction of the angle
    uy: float
    hits: int = 1
    misses: int = 0
    reported: Sighting | None = None


class MarkerTracker:
    def __init__(self, width: int, height: int) -> None:
        self.width, self.height = width, height
        self._tracks: dict[int, _Track] = {}

    def reset(self) -> None:
        self._tracks.clear()

    def update(self, sightings: dict[int, Sighting]) -> list[Token]:
        """Feed one frame's sightings; returns the tokens currently placed."""
        seen = {i: s for i, s in sightings.items() if 0 <= s.x < self.width and 0 <= s.y < self.height}
        for marker_id, s in seen.items():
            t = self._tracks.get(marker_id)
            ux, uy = math.cos(s.angle), math.sin(s.angle)
            if t is None or math.hypot(s.x - t.x, s.y - t.y) > SNAP_CELLS:
                hits = t.hits + 1 if t is not None else 1
                self._tracks[marker_id] = _Track(s.x, s.y, ux, uy, hits=hits)
                continue
            a = SMOOTHING
            t.x += a * (s.x - t.x)
            t.y += a * (s.y - t.y)
            t.ux += a * (ux - t.ux)
            t.uy += a * (uy - t.uy)
            t.hits += 1
            t.misses = 0
        for marker_id in list(self._tracks.keys() - seen.keys()):
            t = self._tracks[marker_id]
            t.misses += 1
            # Not yet placed: any gap starts the count again.
            if t.hits < APPEAR_FRAMES or t.misses > VANISH_FRAMES:
                del self._tracks[marker_id]

        tokens = []
        for marker_id, t in sorted(self._tracks.items()):
            if t.hits < APPEAR_FRAMES:
                continue
            t.reported = _deadband(t.reported, Sighting(t.x, t.y, math.atan2(t.uy, t.ux)))
            r = t.reported
            tokens.append(
                Token(
                    id=f"m{marker_id}",
                    token_type=token_type_for(marker_id),
                    x=r.x,
                    y=r.y,
                    angle=r.angle,
                    source=TokenSource.VISION,
                )
            )
        return tokens


def _deadband(prev: Sighting | None, cur: Sighting) -> Sighting:
    if prev is None:
        return cur
    moved = math.hypot(cur.x - prev.x, cur.y - prev.y) > DEADBAND_CELLS
    turned = abs(_wrap(cur.angle - prev.angle)) > DEADBAND_RAD
    if moved or turned:
        return cur
    return prev


def _wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi

