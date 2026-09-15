"""In-memory edge graph, loaded once per scene from the derived pipeline output."""
from __future__ import annotations
import json, functools
from dataclasses import dataclass, field
import numpy as np
from ..deps import DATA

@dataclass
class Graph:
    scene: str
    edge_ids: list[str]
    idx: dict[str, int]                    # edge_id -> array index
    u: np.ndarray; v: np.ndarray           # node ids per edge
    length_m: np.ndarray; speed_kmh: np.ndarray
    z_min: np.ndarray; slope: np.ndarray
    sink: np.ndarray; kappa: np.ndarray; alpha: np.ndarray
    quality: np.ndarray
    road_class: list[str]
    name: list[str]                        # OSM street name, '' when the way is unnamed
    access: dict[str, np.ndarray]          # vehicle -> bool mask
    coords: list[list[list[float]]]
    out_edges: dict[int, list[int]] = field(default_factory=dict)   # node -> edge indices
    v_int: list[int] = field(default_factory=list)                  # v as plain ints (hot loop)
    downhill: list[list[int]] = field(default_factory=list)         # edge -> downhill successor edges

    @property
    def n(self) -> int:
        return len(self.edge_ids)

    def travel_time_s(self) -> np.ndarray:
        return self.length_m / (self.speed_kmh / 3.6)

def _edge_names(scene: str, edges: list) -> list[str]:
    """Street names from the gazetteer side-car (scripts/build_gazetteer.py).

    Kept out of the edge artifact on purpose: names are a presentation concern for the
    conversational layer, and rebuilding them must never invalidate a computed scenario.
    Missing file degrades to unnamed rather than failing the scene.
    """
    path = DATA / "derived" / f"{scene}_edge_names.json"
    if not path.exists():
        return [""] * len(edges)
    names = json.loads(path.read_text(encoding="utf-8"))
    return [names.get(str(e["way_id"]), "") for e in edges]

@functools.lru_cache(maxsize=4)
def load(scene: str) -> Graph:
    edges = json.loads((DATA / "derived" / f"{scene}_edges.json").read_text(encoding="utf-8"))
    n = len(edges)
    g = Graph(
        scene=scene,
        edge_ids=[e["edge_id"] for e in edges],
        idx={e["edge_id"]: i for i, e in enumerate(edges)},
        u=np.array([e["u"] for e in edges], dtype=np.int64),
        v=np.array([e["v"] for e in edges], dtype=np.int64),
        length_m=np.array([e["length_m"] for e in edges], dtype=float),
        speed_kmh=np.array([e["speed_kmh"] for e in edges], dtype=float),
        z_min=np.array([e.get("z_min", 0.0) for e in edges], dtype=float),
        slope=np.array([e.get("slope", 0.0) for e in edges], dtype=float),
        sink=np.array([e.get("sink_score", 0.0) for e in edges], dtype=float),
        kappa=np.array([e.get("kappa_prior", 0.15) for e in edges], dtype=float),
        alpha=np.array([e.get("alpha_prior", 1.0) for e in edges], dtype=float),
        quality=np.array([e.get("data_quality", 0.5) for e in edges], dtype=float),
        road_class=[e["road_class"] for e in edges],
        name=_edge_names(scene, edges),
        access={
            "motorbike": np.array([e["access_motorbike"] for e in edges]),
            "e_2w": np.array([e["access_motorbike"] for e in edges]),
            "car": np.array([e["access_car"] for e in edges]),
            "response": np.array([e["access_response"] for e in edges]),
        },
        coords=[e["coords"] for e in edges],
    )
    g.v_int = [int(x) for x in g.v]
    for i in range(n):
        g.out_edges.setdefault(int(g.u[i]), []).append(i)
    # downhill successors: edges leaving my end node whose z is not higher than mine
    g.downhill = [
        [j for j in g.out_edges.get(int(g.v[i]), [])
         if g.z_min[j] <= g.z_min[i] + 0.05 and j != _reverse_of(g, i, j)]
        for i in range(n)
    ]
    return g

def _reverse_of(g: Graph, i: int, j: int):
    return j if (g.u[j] == g.v[i] and g.v[j] == g.u[i]) else None

def geojson(scene: str) -> dict:
    g = load(scene)
    feats = []
    for i in range(g.n):
        feats.append({
            "type": "Feature",
            "id": g.edge_ids[i],
            "properties": {
                "edge_id": g.edge_ids[i],
                "name": g.name[i],
                "road_class": g.road_class[i],
                "length_m": float(g.length_m[i]),
                "z_min": float(g.z_min[i]),
                "sink_score": float(g.sink[i]),
                "data_quality": float(g.quality[i]),
                "evidence_class_static": "inferred",
            },
            "geometry": {"type": "LineString", "coordinates": g.coords[i]},
        })
    return {"type": "FeatureCollection", "features": feats}
