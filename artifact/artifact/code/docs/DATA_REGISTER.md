# Data & source register — local demo

| # | Source | What we use | Licence / terms | Provenance tag | Retention | Fallback for (pilot source) |
|---|---|---|---|---|---|---|
| 1 | OpenStreetMap (Overpass API) | Road/alley geometry + tags, Thủ Đức & Đà Nẵng bboxes | ODbL — attribution shown in map corner; derived edge graph is share-alike on redistribution | real geometry | vendored in `data/raw`, checksummed | Tasco base graph + survey |
| 2 | Copernicus GLO-30 DEM (AWS open data) | Edge elevation, slope, sink score | Free use with attribution (ESA/Airbus terms) | real, coarse prior | vendored, checksummed | City 1:2,000 survey / LiDAR |
| 3 | Storm scenario generator (`app/sim`) | Rain & tide forcing, truth run, ensemble | ours | **simulated** | content-addressed parquet/npz | VNMHA feeds + local gauges |
| 4 | Simulated gauge/camera feeds | Assimilation observations | ours (OSSE from truth run) | **simulated** | in scenario meta | FEDS/1022, authorized CCTV |
| 5 | User categorical reports (demo) | Local posterior updates | consent checkbox in flow | **simulated** (`is_synthetic=true` in DB) | demo DB only; thumbnail ≤9 KB blurred client-side | Vmap opt-in community flow |
| 6 | Drainage capacity κ | Latent prior per edge | derived (ours) | **inferred** | derived parquet | HCMC drainage partnership |
| 7 | OpenStreetMap named POIs & places (Overpass) | Landmark gazetteer for the assistant — markets, hospitals, schools, stations, wards; 517 named entries (Thủ Đức) / 344 (Đà Nẵng) | ODbL — same attribution as row 1 | real, `source: osm` on every entry | vendored `data/raw/{scene}.poi.json`, checksummed | Official ward boundaries + city POI register |
| 8 | OSM way names → street gazetteer | Place→coordinate lookup and street names on edges; 1,368 streets (Thủ Đức), 2,679 named ways | ODbL (derived from row 1) | real, `source: osm` | derived `{scene}_places.json`, `{scene}_edge_names.json` | Tasco / VMap street name layer |

| 9 | Open-Meteo Forecast API (ECMWF/GFS blend) | Temperature, feels-like, humidity, precipitation, wind for the scene bbox | CC-BY 4.0, free non-commercial tier | **real, observed** — the only non-simulated dynamic layer in the demo | vendored `data/raw/{scene}.env.json`, checksummed, refresh with `make env-refresh` | Local station network / VNMHA |
| 10 | Open-Meteo Air Quality API (CAMS) | PM2.5, PM10, mineral dust, US AQI, UV index | CC-BY 4.0, free non-commercial tier | **real, observed** | same file as row 9 | City air-quality monitors |

| 11 | OpenStreetMap EV charging (Overpass) | `amenity=charging_station` in the scene bbox **plus a 12 km buffer** | ODbL | **real geometry** for locations; reachability is **simulated** | vendored `data/raw/{scene}.charging.json`, checksummed | VinFast / EVN operator feed |

**Charging coverage finding (row 11).** Measured, not assumed: OSM maps **zero** charging
stations inside either demo bbox. The nearest to the Thủ Đức centre is **7.5 km east**.
Vietnam is not unmapped in general — Hà Nội has ~310 stations, mostly VinFast; TP.HCM has
19 — so this is a coverage gap in these two areas, not evidence that no station exists.
The API therefore separates "no station in scene" from "no station anywhere", always ships
the nearest known real stations with distance and bearing, and marks them unroutable
because the graph stops at the bbox. **No pin was invented to fill the gap.**

**OSM attribute completeness layer.** `data_quality = 0.5 + 0.25 x (width tagged) +
(surface tagged)`, so it takes exactly **three** values: 0.50 for 18,542 edges (71.8%),
0.75 for 7,263 (28.1%), 1.00 for 4. Those two tags feed the passability envelope, so an
edge missing them is modelled on defaults — inferred, not measured. The layer is drawn in
three discrete steps rather than a continuous ramp, because a smooth ramp would imply
resolution the field does not have.

**Sensor coverage.** `/v1/ops/sensor-coverage` reports what the observation network
genuinely informs: the engine's own `Scenario.neighbourhood()` footprint — up to 3 graph
hops within one basin, weights 1 / 0.6 / 0.35 / 0.2 — not an optical viewshed. In the Thủ
Đức scenario **38 sensors reach 161 of 25,809 edges (0.8% by length)**; the rest of the
map is inference. A test asserts the served footprint equals the engine function exactly.

**Ambient layer rule (rows 9–10).** This is the one layer that is measured rather than
simulated, so it is badged "QUAN TRẮC THẬT" and runs on the **real clock**, never on the
scenario tick — conflating the two would imply that measured air quality belongs to the
synthetic storm hour. Measured resolution is the other constraint: nine sample points
across the Thủ Đức bbox collapse into **four distinct source cells ~7.8 km apart**, so the
layer renders hard-edged blocks by nearest source cell and states its own resolution in the
panel. No smoothing, because a soft gradient would paint spatial detail the data does not
contain (same rule as the coverage layer, G1.4). It feeds nothing in passability or
routing, and `test_engine_never_imports_the_ambient_layer` enforces that structurally.

**Gazetteer rule (F1-grounding, docs/AI_FEATURES.md §2b):** every place the assistant can
name or route to comes from rows 7–8. No coordinate is hand-entered from model memory, and
`test_landmarks_and_streets_are_built_from_osm` asserts `source == "osm"` on every entry.
The two derived artifacts are rebuilt by `make gazetteer` and feed no physics, so rebuilding
them never invalidates a computed scenario.

Rules enforced in schema: `is_synthetic BOOLEAN NOT NULL` on every stateful table;
edge versions pinned (`edge_version`); observation rows carry interval + quality, never raw media.
