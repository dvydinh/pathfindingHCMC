/** Applies scene state to the map via feature-state, using per-tick deltas so a
 * scrub repaints in well under 300 ms even with 25k edges (gate G2.5). */
import type maplibregl from "maplibre-gl";
import { BAND_NAME, type SceneState } from "../state/store";

export class StateJoin {
  private prev: number[] | null = null;
  private edgeIds: string[] = [];

  setEdgeIds(ids: string[]) { this.edgeIds = ids; this.prev = null; }

  forceNext() { this.prev = null; }

  apply(map: maplibregl.Map, st: SceneState) {
    if (!this.edgeIds.length) return;
    const n = st.bands.length;
    for (let i = 0; i < n; i++) {
      if (this.prev && this.prev[i] === st.bands[i]) continue;
      map.setFeatureState(
        { source: "edges", id: this.edgeIds[i] },
        { band: BAND_NAME[st.bands[i]] },
      );
    }
    this.prev = st.bands.slice();
  }

  reset(map: maplibregl.Map) {
    map.removeFeatureState({ source: "edges" });
    this.prev = null;
  }
}
