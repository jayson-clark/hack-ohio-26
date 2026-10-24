import { useEffect, type RefObject } from "react";
import type { BinaryFrame } from "../shared/binary";
import type { Token } from "../shared/protocol";
import type { Layers, Projection } from "./projection";

/** Pushes engine and UI state into a view's projection uniforms. */
export function useProjectionSync(
  ref: RefObject<Projection | null>,
  state: { tokens: Token[]; selectedId: string | null; layers: Layers; simGrid: BinaryFrame | null },
  // Bumped by the view when it (re)creates the projection.
  generation: number,
) {
  const { tokens, selectedId, layers, simGrid } = state;
  useEffect(() => ref.current?.setTokens(tokens, selectedId), [ref, tokens, selectedId, generation]);
  useEffect(() => ref.current?.setLayers(layers), [ref, layers, generation]);
  useEffect(() => ref.current?.setFire(simGrid), [ref, simGrid, generation]);
}
