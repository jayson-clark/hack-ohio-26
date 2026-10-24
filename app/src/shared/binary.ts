// Binary frame header. Mirrors BINARY_HEADER in engine/protocol.py by hand:
// type: u8, 3 pad bytes, tick: u32, width: u16, height: u16 (little-endian).

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
