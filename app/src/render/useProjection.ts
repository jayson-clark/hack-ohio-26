import { useEffect, type RefObject } from "react";
import type { BinaryFrame } from "../shared/binary";
import type { ForecastGrids } from "../shared/engine";
import type { RouteInfo, Token } from "../shared/protocol";
import type { Layers, Projection } from "./projection";

/** Pushes engine and UI state into a view's projection uniforms. */
export function useProjectionSync(
  ref: RefObject<Projection | null>,
  state: {
    tokens: Token[];
    selectedId: string | null;
    layers: Layers;
    simGrid: BinaryFrame | null;
    forecast: ForecastGrids | null;
    routes: RouteInfo[];
  },
  // Bumped by the view when it (re)creates the projection.
  generation: number,
) {
  const { tokens, selectedId, layers, simGrid, forecast, routes } = state;
  useEffect(() => ref.current?.setTokens(tokens, selectedId), [ref, tokens, selectedId, generation]);
  useEffect(() => ref.current?.setLayers(layers), [ref, layers, generation]);
  useEffect(() => ref.current?.setFire(simGrid), [ref, simGrid, generation]);
  useEffect(() => ref.current?.setForecast(forecast), [ref, forecast, generation]);
  useEffect(() => ref.current?.setRoutes(routes), [ref, routes, generation]);
}
