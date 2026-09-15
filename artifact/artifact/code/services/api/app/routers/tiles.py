"""Static edge-geometry MVT from PostGIS (production-shaped path; the demo UI
uses /v1/edges.geojson for simplicity — both serve the same versioned geometry)."""
from fastapi import APIRouter, Response
from ..deps import db

router = APIRouter(prefix="/v1")

SQL = """
WITH b AS (SELECT ST_TileEnvelope(%s,%s,%s) AS env)
SELECT ST_AsMVT(t, 'edges', 4096, 'geom') FROM (
  SELECT edge_id, road_class, data_quality,
         ST_AsMVTGeom(ST_Transform(geom, 3857), b.env, 4096, 64, true) AS geom
  FROM edges, b
  WHERE ST_Transform(geom, 3857) && b.env
) t;
"""

@router.get("/tiles/{z}/{x}/{y}.mvt")
def tile(z: int, x: int, y: int) -> Response:
    with db() as conn, conn.cursor() as cur:
        cur.execute(SQL, (z, x, y))
        row = cur.fetchone()
    data = bytes(row[0]) if row and row[0] else b""
    return Response(content=data, media_type="application/vnd.mapbox-vector-tile")
