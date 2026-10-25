import { useEffect, useMemo, type RefObject } from "react";
import type { BinaryFrame } from "../shared/binary";
import { Cell, useEngine, type ForecastGrids } from "../shared/engine";
import { threatenedTowns } from "../shared/events";
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
  // Read straight from the store rather than threaded through every view's
  // props: every projection shows the same recommendations.
  const { recommendations, events, hello, units } = useEngine();
  const stations = hello?.stations;
  useEffect(() => ref.current?.setDispatch(stations ?? [], units), [ref, stations, units, generation]);
  const crewReach = hello?.crew_radius ?? 14;
  useEffect(() => ref.current?.setCrewReach(crewReach), [ref, crewReach, generation]);
  useEffect(() => ref.current?.setRecommendations(recommendations), [ref, recommendations, generation]);
  // The store's events outlive a reset, so a map with nothing burning has no
  // threatened towns whatever the log says. Joined to a string so the canvas
  // only redraws when the set actually changes, not on every sim frame.
  const burning = !!simGrid && simGrid.payload.includes(Cell.Burning);
  const threatened = useMemo(() => (burning ? threatenedTowns(events).join("|") : ""), [burning, events]);
  useEffect(
    () => ref.current?.setThreatened(threatened ? threatened.split("|") : []),
    [ref, threatened, generation],
  );
}
