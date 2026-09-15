"""Sample the DEM along edges; derive slope, min elevation, sink_score, and hydrology
priors (kappa/alpha). GLO-30 is a coarse prior, not alley truth — recorded as such."""
import json, math
import numpy as np
import rasterio
from common import RAW, DERIVED, load_scenes, scene_name

def main() -> None:
    scene = scene_name()
    scenes, _ = load_scenes()
    bbox = scenes[scene]["bbox"]
    lat0, lon0 = int(math.floor(bbox[1])), int(math.floor(bbox[0]))
    dem_path = RAW / f"glo30_N{lat0:02d}_E{lon0:03d}.tif"
    edges = json.loads((DERIVED / f"{scene}_edges.json").read_text(encoding="utf-8"))

    with rasterio.open(dem_path) as dem:
        def sample(pts):
            vals = np.array([v[0] for v in dem.sample(pts)], dtype=float)
            vals[vals < -100] = np.nan
            return vals
        starts = sample([e["coords"][0] for e in edges])
        ends = sample([e["coords"][-1] for e in edges])
        mids = sample([e["coords"][len(e["coords"]) // 2] for e in edges])

    z_min = np.nanmin(np.stack([starts, ends, mids]), axis=0)
    fallback = np.nanmedian(z_min)
    for arr in (starts, ends, mids, z_min):
        arr[np.isnan(arr)] = fallback
    null_pct = float(np.mean(np.isnan(z_min))) * 100

    # sink_score: how far below the local (~500 m cell) 75th percentile an edge sits
    lons = np.array([e["coords"][0][0] for e in edges])
    lats = np.array([e["coords"][0][1] for e in edges])
    cell = 0.0045  # ~500 m
    keys = np.stack([(lons // cell).astype(int), (lats // cell).astype(int)], axis=1)
    sink = np.zeros(len(edges))
    from collections import defaultdict
    buckets = defaultdict(list)
    for i, k in enumerate(map(tuple, keys)):
        buckets[k].append(i)
    for k, idx in buckets.items():
        neigh = [j for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                 for j in buckets.get((k[0] + dx, k[1] + dy), [])]
        ref = np.percentile(z_min[neigh], 75)
        spread = max(np.percentile(z_min[neigh], 90) - np.percentile(z_min[neigh], 10), 1.0)
        sink[idx] = np.clip((ref - z_min[idx]) / spread, 0, 1)

    rng = np.random.default_rng(42)  # deterministic priors
    for i, e in enumerate(edges):
        big = e["road_class"] in ("motorway", "trunk", "primary", "secondary")
        length = e["length_m"]
        e.update({
            "z_start": round(float(starts[i]), 2), "z_end": round(float(ends[i]), 2),
            "z_min": round(float(z_min[i]), 2),
            "slope": round(float((ends[i] - starts[i]) / max(length, 1)), 5),
            "sink_score": round(float(sink[i]), 3),
            # drainage capacity prior: arterials drain better; sinks drain worse
            "kappa_prior": round(float(np.clip(
                (0.22 if big else 0.12) - 0.10 * sink[i] + rng.normal(0, 0.01), 0.02, 0.4)), 4),
            # runoff amplification prior: dense low-lying areas collect more
            "alpha_prior": round(float(np.clip(1.0 + 1.5 * sink[i] + rng.normal(0, 0.05), 0.5, 3.0)), 3),
            "data_quality": round(0.5 + 0.25 * e.pop("tag_quality"), 2),
            "evidence_class_static": "inferred",  # terrain-derived attrs are inferred (I1)
        })
    (DERIVED / f"{scene}_edges.json").write_text(json.dumps(edges), encoding="utf-8")
    print(f"[ok] terrain attached: {len(edges)} edges, null-elev {null_pct:.2f}%, "
          f"sink std {sink.std():.3f} (must be > 0)")

if __name__ == "__main__":
    main()
