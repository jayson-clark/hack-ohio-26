// Binary frame header. Mirrors BINARY_HEADER in engine/protocol.py by hand:
// type: u8, 3 pad bytes, tick: u32, width: u16, height: u16 (little-endian).
//
// Payloads (see the protocol.py docstring):
// - SimGrid: width*height uint8 cell states (Cell in engine.ts), row 0 = north.
// - ForecastGrid: one width*height uint8 grid per Hello.forecast_horizons_min
//   entry, stacked in that order; P(burned by the horizon) as 0-255. The
//   header's tick is the sim tick the forecast started from.
// - CameraFrame: one JPEG of the webcam with the vision overlay drawn in;
//   width/height are the JPEG's, tick counts feed frames.

export const BinaryType = {
  SimGrid: 1,
  ForecastGrid: 2,
  CameraFrame: 3,
} as const;

export const HEADER_BYTES = 12;

export interface BinaryFrame {
  type: number;
  tick: number;
  width: number;
  height: number;
  payload: Uint8Array;
}

export function parseBinaryFrame(buf: ArrayBuffer): BinaryFrame {
  const view = new DataView(buf);
  return {
    type: view.getUint8(0),
    tick: view.getUint32(4, true),
    width: view.getUint16(8, true),
    height: view.getUint16(10, true),
    payload: new Uint8Array(buf, HEADER_BYTES),
  };
}
