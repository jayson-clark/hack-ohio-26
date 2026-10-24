// Minimal .npy reader: little-endian float32, C order. Enough for the
// heightmaps written by tools/dem_to_assets.py.

export interface NpyArray {
  data: Float32Array;
  shape: number[];
}

export function parseNpy(buf: ArrayBuffer): NpyArray {
  const bytes = new Uint8Array(buf);
  if (bytes[0] !== 0x93 || String.fromCharCode(...bytes.slice(1, 6)) !== "NUMPY") {
    throw new Error("not a .npy file");
  }
  const major = bytes[6];
  const view = new DataView(buf);
  const headerLen = major >= 2 ? view.getUint32(8, true) : view.getUint16(8, true);
  const headerStart = major >= 2 ? 12 : 10;
  const header = new TextDecoder().decode(bytes.slice(headerStart, headerStart + headerLen));

  const descr = /'descr':\s*'([^']+)'/.exec(header)?.[1];
  if (descr !== "<f4") throw new Error(`unsupported dtype ${descr}`);
  if (/'fortran_order':\s*True/.test(header)) throw new Error("fortran order not supported");
  const shape = (/'shape':\s*\(([^)]*)\)/.exec(header)?.[1] ?? "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean)
    .map(Number);

  const offset = headerStart + headerLen;
  const count = shape.reduce((a, b) => a * b, 1);
  // Copy so the data is 4-byte aligned regardless of header length.
  return { data: new Float32Array(buf.slice(offset, offset + count * 4)), shape };
}
