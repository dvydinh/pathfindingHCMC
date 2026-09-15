# API quick reference

Contract of record: `packages/contracts/openapi.yaml`. TS types are generated from it;
Python responses are contract-tested against it.

| Endpoint | Purpose |
|---|---|
| `GET /v1/scene` | Scene metadata (bbox, scenario, edge count) |
| `GET /v1/edges.geojson` | Static edge geometry (order = state array order) |
| `GET /v1/tiles/{z}/{x}/{y}.mvt` | Same geometry as MVT (PostGIS `ST_AsMVT`) |
| `GET /v1/state?at&vehicle` | Compact aligned-array state for all edges |
| `GET /v1/passability?at&vehicle&edge_id` | Full EdgeState detail (+depth fan) |
| `POST /v1/routes` | fastest_dry / recommended / most_conservative + why |
| `POST /v1/observations` | Consented categorical report (blurred thumb only) |
| `GET /v1/provenance/{edge_id}` | Source classes + freshness for an edge |
| `GET /v1/model-card` | Scope, envelopes, guards, limitations |
| `GET /v1/ops/feeds` · `/v1/ops/queue` | Feed health · active-sensing queue |
| `POST /v1/ops/closure` · `/v1/ops/outage` | Official closure · sensor outage drill |
| `GET /v1/ops/replay-metrics` | Benchmark results (n, CIs, per-OD rows) |

Tasco swap-in seam: `apps/web/src/map/MapView.tsx` (basemap style + sources) and
`services/api/scripts/build_graph.py` (graph source). Both isolate the provider.
