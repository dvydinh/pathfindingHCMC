# Decision log

Entries are appended, never rewritten. Fallbacks taken during the sprint are recorded here
per WORKFLOW.md rules.

## 001 — Demo bounding box (M0)
Thủ Đức core: `[106.735, 10.815, 106.795, 10.870]`, frozen in `config/bbox.yaml`.
Rationale: contains recurring flood hot spots, arterial + alley mix, matches proposal pilot.
Subject to the M1 fallback (shrink to densest sub-area) if OSM alley coverage is thin.

## 002 — Contract generation strategy (M0)
`openapi.yaml` is the single authored contract. TS types are code-generated
(`openapi-typescript`). Python models are hand-written pydantic mirrors, held to the contract
by response-validation tests in `services/api/tests/test_contract.py`. Full two-sided codegen
(datamodel-code-generator) was skipped to keep the container build lean; the contract tests
provide the drift guard the workflow requires.

## 003 — Client-driven clock instead of WS broadcast (M0)
The time slider drives state fetches per tick (cacheable, instant scrubbing). The WS clock in
PLAN.md §5 is deferred: single-viewer local demo has no fan-out need. The API shape keeps a
tick-indexed design so a WS broadcaster can be added without contract change.

## 004 — Basemap strategy for offline guarantee (M0)
No third-party tile server. The vendored MapLibre style renders a neutral background; the road
graph itself (our edges layer, real OSM geometry) is the visual base, which is also the honest
choice: the demo's subject *is* the road graph. ODbL attribution rendered in the map corner.

## 005 — Edge-count band widened (M1)
The pre-data band (3,000–8,000) was set before knowing OSM density. The Thủ Đức bbox yields
25,809 directed edges (21,063 alley-class) — richer coverage than planned, which is the good
direction. Perf is guarded by the real gates (G2.5 scrub latency, G3.5 route p95), so the
G1.1 band is widened to 1,500–30,000 directed edges instead of shrinking the bbox.

## 006 — Router: weighted Dijkstra + constraint retry instead of multi-label Pareto (M3)
Full (time, risk) Pareto label search was replaced by single-label Dijkstra with a
CVaR-weighted cost, a post-hoc union-bound chance check, and an escalating risk-multiplier
retry (×1, ×4, ×16), then a wait-and-depart-later scan. Same safety contract (I5 is
verified post-hoc on the returned path), a fraction of the complexity and latency.

## 007 — Scene switching via URL param (M7)
`?scene=danang` reloads the app against the frozen transfer scene; a permanent amber
banner marks it precomputed/simulated. Chosen over in-app hot-switching to keep the
state join trivially correct.

## 008 — Chance-constraint noise floor (M7 hardening)
Per-edge unsafety below 0.01 is excluded from the union-bound accumulation
(`P_NOISE_FLOOR` in router.py). Without it, envelope-sigmoid tail noise (~5e-4/edge)
summed over a 100+-edge path breached α≈0.05 on effectively dry routes, forcing
`no_safe_route` everywhere at peak. Exposure metrics still use the raw probabilities.

## 009 — A* admissible heuristic (M8, G3.5)
Route search upgraded from Dijkstra to A* with straight-line-distance / 80 km/h as an
admissible, consistent lower bound on remaining cost. Needed to hold p95 < 2 s with up
to 8 searches per request (dry, 3 escalating aware retries, conservative, wait scan).

## 010 — Snap targets restricted to the strongly-connected core (M8)
Weak connectivity was insufficient: ~1,900 nodes are one-way-in pockets. Origin/
destination now snap into the largest strongly-connected motorbike-accessible core
(forward∩backward BFS from a hub), guaranteeing mutual dry-graph routability.
