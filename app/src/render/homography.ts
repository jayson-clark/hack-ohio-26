// The projector calibration's map -> projector homography (Calibration.map_to_proj):
// a row-major 3x3 from map cells to the projector window, normalised so
// (0, 0) is its top-left and (1, 1) its bottom-right.

export type Mat3 = number[]; // 9 entries, row-major

export function apply(h: Mat3, x: number, y: number): [number, number] {
  const w = h[6] * x + h[7] * y + h[8];
  return [(h[0] * x + h[1] * y + h[2]) / w, (h[3] * x + h[4] * y + h[5]) / w];
}

export function invert(h: Mat3): Mat3 {
  const [a, b, c, d, e, f, g, i, k] = h;
  const A = e * k - f * i;
  const B = f * g - d * k;
  const C = d * i - e * g;
  const det = a * A + b * B + c * C;
  return [
    A / det,
    (c * i - b * k) / det,
    (b * f - c * e) / det,
    B / det,
    (a * k - c * g) / det,
    (c * d - a * f) / det,
    C / det,
    (b * g - a * i) / det,
    (a * e - b * d) / det,
  ];
}

/** Scale the normalised output to a w x h pixel window. */
export function toPixels(h: Mat3, w: number, hgt: number): Mat3 {
  return [h[0] * w, h[1] * w, h[2] * w, h[3] * hgt, h[4] * hgt, h[5] * hgt, h[6], h[7], h[8]];
}

/** CSS matrix3d() for an element whose local px are map cells (transform-origin 0 0). */
export function cssMatrix3d(h: Mat3): string {
  const [a, b, c, d, e, f, g, i, k] = h;
  // Column-major 4x4, with the homography's w in the 4th row.
  return `matrix3d(${[a, d, 0, g, b, e, 0, i, 0, 0, 1, 0, c, f, 0, k].join(",")})`;
}
