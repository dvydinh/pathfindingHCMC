"""Create schema and load the edge graph into PostGIS. Idempotent (G1.5)."""
import json, os
import psycopg
from common import DERIVED, load_scenes, scene_name

DDL = """
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE TABLE IF NOT EXISTS edges (
  edge_id text PRIMARY KEY,
  edge_version int NOT NULL DEFAULT 1,
  scene text NOT NULL,
  u bigint NOT NULL, v bigint NOT NULL,
  road_class text NOT NULL, length_m real NOT NULL, width_m real, surface text,
  oneway boolean, speed_kmh real,
  access_car boolean, access_motorbike boolean, access_response boolean,
  z_start real, z_end real, z_min real, slope real,
  sink_score real, kappa_prior real, alpha_prior real, data_quality real,
  evidence_class_static text NOT NULL,
  is_synthetic boolean NOT NULL DEFAULT false,   -- invariant I6: NOT NULL
  geom geometry(LineString, 4326) NOT NULL
);
CREATE INDEX IF NOT EXISTS edges_geom_idx ON edges USING gist (geom);
CREATE INDEX IF NOT EXISTS edges_scene_idx ON edges (scene);
CREATE TABLE IF NOT EXISTS observations (
  observation_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  edge_id text NOT NULL REFERENCES edges(edge_id),
  tick int NOT NULL,
  source_class text NOT NULL,
  category text,
  depth_interval_cm_lo real, depth_interval_cm_hi real,
  vehicle_context text,
  quality_score real,
  thumb_b64 text,             -- 64x64 blurred thumbnail ONLY; raw never stored (I7)
  is_synthetic boolean NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS closures (
  edge_id text PRIMARY KEY REFERENCES edges(edge_id),
  active boolean NOT NULL,
  set_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS override_log (
  id serial PRIMARY KEY,
  kind text NOT NULL, target text NOT NULL, active boolean NOT NULL,
  at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS reference_sites (
  edge_id text PRIMARY KEY REFERENCES edges(edge_id),
  reason text NOT NULL
);
"""

def main() -> None:
    scene = scene_name()
    edges = json.loads((DERIVED / f"{scene}_edges.json").read_text(encoding="utf-8"))
    dsn = os.environ["DATABASE_URL"]
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(DDL)
        cur.execute("DELETE FROM reference_sites WHERE edge_id IN (SELECT edge_id FROM edges WHERE scene=%s)", (scene,))
        cur.execute("DELETE FROM observations WHERE edge_id IN (SELECT edge_id FROM edges WHERE scene=%s)", (scene,))
        cur.execute("DELETE FROM closures WHERE edge_id IN (SELECT edge_id FROM edges WHERE scene=%s)", (scene,))
        cur.execute("DELETE FROM edges WHERE scene=%s", (scene,))
        rows = []
        for e in edges:
            wkt = "LINESTRING(" + ",".join(f"{c[0]} {c[1]}" for c in e["coords"]) + ")"
            rows.append((
                e["edge_id"], scene, e["u"], e["v"], e["road_class"], e["length_m"],
                e["width_m"], e["surface"], e["oneway"], e["speed_kmh"],
                e["access_car"], e["access_motorbike"], e["access_response"],
                e["z_start"], e["z_end"], e["z_min"], e["slope"],
                e["sink_score"], e["kappa_prior"], e["alpha_prior"], e["data_quality"],
                e["evidence_class_static"], wkt,
            ))
        cur.executemany("""
            INSERT INTO edges (edge_id, scene, u, v, road_class, length_m, width_m, surface,
              oneway, speed_kmh, access_car, access_motorbike, access_response,
              z_start, z_end, z_min, slope, sink_score, kappa_prior, alpha_prior,
              data_quality, evidence_class_static, geom)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                    ST_GeomFromText(%s, 4326))
        """, rows)
        # reference sites: 20 deepest sinks (proposal: surveyed depth markers stand-in)
        cur.execute("""
            INSERT INTO reference_sites (edge_id, reason)
            SELECT edge_id, 'high sink_score (recurrent flood proxy)' FROM edges
            WHERE scene=%s ORDER BY sink_score DESC LIMIT 20
        """, (scene,))
        conn.commit()
        cur.execute("SELECT count(*) FROM edges WHERE scene=%s", (scene,))
        print(f"[ok] seeded {cur.fetchone()[0]} edges for scene {scene}")

if __name__ == "__main__":
    main()
