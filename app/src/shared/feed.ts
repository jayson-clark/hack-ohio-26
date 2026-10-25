// The camera_frame JPEG as an image URL, for the camera feed and the console's
// drone basemap. Each frame is decoded before it replaces the last, so an SVG
// <image> swapping its href ten times a second never flashes blank.

import { useEffect, useState } from "react";
import type { BinaryFrame } from "./binary";
import type { VisionStatus } from "./protocol";

export function useFeedUrl(frame: BinaryFrame | null): string | null {
  const [url, setUrl] = useState<string | null>(null);

  useEffect(() => {
    if (!frame) return;
    const next = URL.createObjectURL(new Blob([frame.payload as Uint8Array<ArrayBuffer>], { type: "image/jpeg" }));
    let live = true;
    const img = new Image();
    img.src = next;
    img
      .decode()
      .catch(() => {})
      .then(() => (live ? setUrl(next) : URL.revokeObjectURL(next)));
    return () => {
      live = false;
    };
  }, [frame]);

  // Free each URL once the next one is showing.
  useEffect(() => () => void (url && URL.revokeObjectURL(url)), [url]);
  return url;
}

/** The feed is the live top-down orthophoto, covering exactly the map grid. */
export function droneFeedLive(vision: VisionStatus | null): boolean {
  return vision?.camera === "ok" && vision.feed_rectified;
}
