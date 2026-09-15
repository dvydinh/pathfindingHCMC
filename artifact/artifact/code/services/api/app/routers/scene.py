import functools, json
from fastapi import APIRouter, Response
from ..deps import scenes, default_scene
from ..engine import graph

router = APIRouter(prefix="/v1")

@router.get("/scene")
def get_scene(scene: str | None = None) -> dict:
    s = scene or default_scene()
    meta = scenes()[s]
    g = graph.load(s)
    return {"scene": s, "name": meta["name"], "bbox": meta["bbox"],
            "scenario": meta["scenario"], "n_edges": g.n}

@functools.lru_cache(maxsize=4)
def _geojson_bytes(s: str) -> bytes:
    return json.dumps(graph.geojson(s)).encode()

@router.get("/edges.geojson")
def get_edges(scene: str | None = None) -> Response:
    s = scene or default_scene()
    return Response(content=_geojson_bytes(s), media_type="application/geo+json",
                    headers={"Cache-Control": "max-age=3600"})
