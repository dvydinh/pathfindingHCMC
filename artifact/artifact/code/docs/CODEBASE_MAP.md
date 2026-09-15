# CODEBASE_MAP — Đường An VN

Phase 0 comprehension pass. Read-only: không có file nào bị sửa.
Mọi số dòng trích từ source tại commit `3946191` (xem `PROVENANCE`).

Kim chỉ nam phân loại: **SPINE = DỰ ĐOÁN NGẬP → CẬP NHẬT TÌNH TRẠNG ĐƯỜNG → ĐỀ XUẤT TUYẾN.**

---

## 1. Data flow: storm simulation → edge state → routing → UI

### Giai đoạn A — offline: build graph & precompute storm

- `scripts/build_graph.py` → `data/derived/{scene}_edges.json` (25.809 cạnh có hướng cho scene `thuduc`, theo `docs/DECISIONS.md:30`).
- `scripts/attach_terrain.py` gắn `z_min`, `slope`, `sink_score`, `kappa_prior`, `alpha_prior` từ DEM.
- `scripts/build_gazetteer.py` → `data/derived/{scene}_edge_names.json` (side-car tên đường, cố ý tách khỏi edge artifact — `engine/graph.py:33-44`).
- `app/engine/graph.py:46` `load(scene)` đọc JSON thành dataclass `Graph`: mảng numpy song song theo cạnh + `out_edges` (node → edge idx, dòng 75-76) + `downhill` (cạnh → cạnh xuôi dốc, dòng 78-82). Cache `lru_cache(maxsize=4)`.
- `app/sim/storm.py:38` `main()` — entry `python -m app.sim.storm`:
  - `hydro.run_ensemble(g, spec, seed_offset=777, n_members=1)` → **truth run** (dòng 44).
  - `hydro.run_ensemble(g, spec)` → **ensemble prior** `(T, E, N)` (dòng 46).
  - `make_feeds(...)` (dòng 15-36) rút quan trắc gauge/camera **từ truth run + nhiễu**, gán `is_synthetic=true` — đây là thiết kế OSSE.
  - Ghi `data/scenarios/{scene}_{spec_hash}_ens.npy`, `_truth.npy`, `_quantiles.parquet`, và `{scene}_meta.json` (chứa `feeds`, `guards`, `spec_hash`).
- `app/engine/hydro.py:38` `step()` là toàn bộ vật lý: `h+ = [h + α·rain + q_in − f_out − κ·h]_+`, có thêm triều (`imp`, dòng 51-52) chỉ tác động lên cạnh trũng (percentile 25 của `z_min`). Guard counters (clamp âm, nhảy bậc) ở dòng 63-68.

### Giai đoạn B — runtime: assimilation → edge state

- `app/engine/state.py:19` `Scenario.__init__` mmap `_ens.npy` / `_truth.npy` (dòng 25-27), load graph, khởi tạo state tương tác: `closures`, `outages`, `user_obs`, `version`.
- Quan trắc → hậu nghiệm:
  - `observations_upto(tick)` (dòng 82) = feeds mô phỏng (trừ feed đang outage) + báo cáo người dùng.
  - `_log_lik` (dòng 88) tính log-likelihood mỗi ensemble member; hỗ trợ 2 dạng: `depth_cm` (Gaussian) và `interval_cm` (soft-window, dùng cho báo cáo cộng đồng dạng hạng mục).
  - `neighbourhood(e)` (dòng 59) giới hạn ảnh hưởng: ≤3 hop, cùng lưu vực (`|Δz| < 2 m`), hop decay `[1.0, 0.6, 0.35, 0.2]`.
  - `weights(tick)` (dòng 129) → ma trận trọng số hậu nghiệm `(E, N)`, softmax theo tổng log-lik có nhân influence.
  - `quantiles(tick)` (dòng 172) → p10/p50/p90 theo trọng số hậu nghiệm.
- `app/engine/passability.py`:
  - `ENVELOPE` (dòng 12-17): ngưỡng (caution, refuse) cm theo loại xe.
  - `member_passability` (dòng 21) → sigmoid quanh ngưỡng refuse; `pi_matrix` (dòng 26) marginalise theo trọng số → **π mỗi cạnh**, ép 0 nếu xe không được phép đi (dòng 33).
  - `band_arrays` (dòng 65) → risk band vector hoá; **closure ép π=0 SAU inference** (dòng 83, invariant I4).
  - `edge_states` (dòng 86) → payload mảng song song mà client join theo index.
- `app/engine/active.py` xếp hạng cạnh chưa quan trắc cho hàng đợi active sensing (dùng `sc.recent_routes`).

### Giai đoạn C — routing

- `app/engine/router.py`:
  - `_tick_layer` (dòng 26) tính mỗi tick: `p_unsafe`, `p_constraint` (có noise floor 0.01, dòng 20/36), `cvar` (CVaR₉₀, dòng 38-40), `width_norm`, `blocked`.
  - `_fast_layer` (dòng 126) đổi sang list/set thuần Python cho vòng lặp A*; cost = `tt · (1 + L1·risk_mult·CVaR + L2·width)` (dòng 137).
  - `_search` (dòng 149) A* trên **node**, heuristic haversine/`VMAX_MS` (dòng 157-162), chi phí phụ thuộc **arrival tick** (dòng 176-177).
  - `route` (dòng 239): chạy `dry` (không né ngập) → retry escalation `RETRY_MULT = [1, 4, 16]` cho tới khi `sum_p_unsafe ≤ alpha` → nếu thất bại thì quét `WAIT_OFFSETS` để gợi ý đi trễ.
  - `departure_window` (dòng 296) quét coarse-to-fine cửa sổ khởi hành.

### Giai đoạn D — API → UI

- `GET /v1/edges.geojson` (`routers/scene.py:22`) → hình học tĩnh, cache 1h.
- `GET /v1/state?at&vehicle` (`routers/passability.py:29`) → mảng `bands/pi/p50_cm/width_cm/age_s`, orjson + byte cache. `warm()` (dòng 9) chạy nền lúc startup, precompute mọi tick × mọi vehicle.
- `POST /v1/routes` (`routers/routes.py:18`) → 3 tuyến (`fastest_dry`, `recommended`, `most_conservative`) + `comparison` + `explanation` (reason code của cạnh mà tuyến khuyến nghị từ chối, dòng 56-69).
- Frontend `apps/web/src/App.tsx`:
  - `applyState(tick, vehicle)` → `fetchState` → `StateJoin.apply(map, st)` (`map/stateJoin.ts`) tô màu cạnh theo band.
  - `reroute(tick, vehicle)` → `requestRoutes` → `drawRoutes` (`state/routing.ts`).
  - Mỗi thay đổi tương tác (đóng đường qua `EdgeInspector`, báo cáo qua `ReportFlow`, outage qua `OpsPanel`) đều gọi `joinRef.current.forceNext()` rồi `applyState` + `reroute` → vòng lặp đóng kín.

**Vòng khép kín cốt lõi:** `storm.py` (prior) → `state.py` (assimilation) → `passability.py` (π + band) → `router.py` (A* có ràng buộc rủi ro) → `/v1/state` + `/v1/routes` → `App.tsx`.

---

## 2. Bảng phân loại module

### Routers (`app/routers/`)

| Module | Endpoint | Chức năng | Phân loại |
|---|---|---|---|
| `scene.py` | `GET /v1/scene`, `GET /v1/edges.geojson` | Metadata scene + hình học cạnh | **SPINE** (nền tảng UI) |
| `passability.py` | `GET /v1/state`, `GET /v1/passability` | Edge state theo tick/vehicle; chi tiết 1 cạnh cho Inspector; `warm()` | **SPINE** |
| `routes.py` | `POST /v1/routes` | Đề xuất tuyến + so sánh + giải thích | **SPINE** |
| `observations.py` | `POST /v1/observations` | Báo cáo cộng đồng → `interval_cm` → assimilation | **SPINE** (cập nhật tình trạng đường) |
| `weather.py` | `GET /v1/weather` | Mưa/triều của kịch bản + thống kê ngập theo bbox | **SPINE** (đầu vào dự đoán) |
| `assistant.py` | `POST /v1/assistant`, `/assistant/status`, `/assistant/models` | LLM tool-calling qua gazetteer/router/narrate | **SPINE** (theo chỉ đạo) |
| `tiles.py` | `GET /v1/tiles/{z}/{x}/{y}.mvt` | MVT từ PostGIS (đường production-shaped; UI demo không dùng) | **SPINE** (theo chỉ đạo) — xem Câu hỏi #3 |
| `ops.py` | `POST /v1/ops/closure` | Đóng đường chính thức → `sc.closures` | **SPINE** (tín hiệu ngập chính thức) |
| `ops.py` | `POST /v1/ops/outage`, `GET /ops/feeds`, `/ops/queue`, `/ops/sensor-coverage`, `/ops/replay-metrics`, `/ops/override-log` | Sensor outage, hàng đợi active sensing, coverage, benchmark | **PHỤ** (phần outage) — xem Câu hỏi #1 |
| `environment.py` | `GET /v1/environment`, `/environment/series` | Nhiệt/ẩm/PM2.5/AQI (Open-Meteo thật, đồng hồ thật) | **PHỤ** — docstring tự khẳng định "feeds nothing in the passability or routing path" |
| `charging.py` | `GET /v1/charging` | Trạm sạc EV + khả năng tiếp cận | **PHỤ** |
| `modelcard.py` | `GET /v1/model-card` | Model card, envelope, guards, giới hạn | **PHỤ** nhưng là tài sản trung thực — xem Câu hỏi #2 |
| `provenance.py` | `GET /v1/provenance/{edge_id}` | Nguồn bằng chứng cho 1 cạnh | **PHỤ** — xem Câu hỏi #2 |

### Engine (`app/engine/`)

| Module | LOC | Chức năng | Phân loại |
|---|---|---|---|
| `graph.py` | 107 | Graph in-memory, `out_edges`, `downhill`, GeoJSON | **SPINE** |
| `hydro.py` | 91 | Vật lý ngập 1 bước + `run_ensemble` | **SPINE** |
| `state.py` | 209 | Scenario runtime, assimilation, weights, quantiles, closures/outages | **SPINE** |
| `passability.py` | 128 | π theo vehicle, risk band, reason codes, `edge_states` | **SPINE** |
| `router.py` | 366 | A* phụ thuộc thời gian, chance constraint, CVaR, retry, departure window | **SPINE** |
| `gazetteer.py` | 233 | Tên địa điểm → toạ độ, từ chối khi không khớp | **SPINE-support** (assistant) |
| `narrate.py` | 178 | Kết quả engine → facts có tên + đơn vị cho LLM | **SPINE-support** (assistant) |
| `trip.py` | 173 | Điều phối tool nhiều chặng, deterministic | **SPINE-support** (assistant) |
| `active.py` | 37 | Xếp hạng cạnh đáng quan trắc | **PHỤ** (gắn với ops queue) |
| `charging.py` | 110 | Snapshot trạm sạc + reachability | **PHỤ** |
| `environment.py` | 178 | Chuỗi ambient theo giờ thật | **PHỤ** |

### Sim (`app/sim/`)

| Module | Chức năng | Phân loại |
|---|---|---|
| `storm.py` | Precompute truth + ensemble + feeds mô phỏng, content-addressed | **SPINE** |
| `scenarios/thuduc_compound.yaml`, `danang_transfer.yaml` | Spec kịch bản (rain/tide curve, physics, uncertainty, feeds) | **SPINE** |

### Frontend (`apps/web/src/`)

| File | Phân loại |
|---|---|
| `App.tsx`, `map/MapView.tsx`, `map/stateJoin.ts`, `state/store.ts`, `state/api.ts`, `state/routing.ts`, `state/i18n.ts` | **SPINE** |
| `panels/EdgeInspector.tsx`, `EdgePopup.tsx`, `TimeSlider.tsx`, `RouteCompare.tsx`, `WeatherPanel.tsx`, `VehiclePicker.tsx`, `Legend.tsx`, `ReportFlow.tsx`, `AssistantPanel.tsx`, `LlmKeySetup.tsx` | **SPINE** |
| `panels/ChargingPanel.tsx`, `EnvironmentPanel.tsx`, `state/environment.ts` | **PHỤ** (Phase 1 sẽ ẩn) |
| `panels/OpsPanel.tsx`, `state/sensors.ts` | **HỖN HỢP** — tab `feeds` chứa cả closure (spine) lẫn nút outage (phụ); tab `queue`/`metrics`/`card` là phụ |

---

## 3. Dependency giữa các module

```
deps.py  (DATA/CONFIG path, db(), scenes())
   ↑ mọi thứ

graph.py ──────────────┐
   ↑                   │
hydro.py ──► sim/storm.py
   ↑
state.py ──► passability.py ──► router.py
   │              ↑   ↑             ↑
   │              │   │             │
   │         active.py│        trip.py ──► gazetteer.py
   │              narrate.py ◄─────┘
   │
   └──► routers/{passability, routes, observations, ops, weather, modelcard, provenance, assistant}

charging.py ──► narrate.py, passability.py, router.py, state.py   (nhánh PHỤ)
environment.py ──► deps.py only                                   (nhánh PHỤ, độc lập hoàn toàn)
```

Điểm đáng chú ý:

- **`environment.py` là lá cô lập**: chỉ import `..deps`. Tắt nó không ảnh hưởng gì.
- **`charging.py` là lá tiêu thụ**: import `narrate`, `passability`, `router`, `state` nhưng **không module spine nào import ngược lại**. Tắt an toàn.
- **`main.py` import tất cả 12 router ở top-level** (dòng 4) — gating phải làm ở tầng `include_router`, còn import vẫn giữ (không xoá code).
- **Import vòng được né bằng import cục bộ**: `routers/passability.py:16` (`eng_router` bên trong `warm`), `routers/routes.py:57`, `routers/assistant.py:361`.
- `sim/storm.py` được `routers/weather.py:8` import (`spec_for`) — nghĩa là weather router phụ thuộc file YAML kịch bản, không chỉ vào ensemble đã tính.

---

## 4. Entry points & cách chạy

### Makefile targets

| Target | Lệnh | Ghi chú |
|---|---|---|
| `make up` | `docker compose up -d --build` | Dựng db (postgis:16-3.4), redis:7, api |
| `make fetch` | `fetch_raw.py`, `fetch_env.py`, `fetch_charging.py` | Cần mạng, chạy 1 lần. 2/3 script này phục vụ nhánh PHỤ |
| `make seed` | `build_graph.py` → `attach_terrain.py` → `build_gazetteer.py` → `seed.py` | Dựng graph + nạp PostGIS |
| `make storm` | `python -m app.sim.storm` | **Bắt buộc trước khi test/demo** — sinh `data/scenarios/` |
| `make dev` | `cd apps/web && npm run dev` | Vite dev server |
| `make test` | `pytest tests -q` trong container + `npm run typecheck` | |
| `make eval` | `replay_eval.py` | Sinh `data/eval/replay_metrics.json` |
| `make demo` | `up` + khôi phục snapshot DB nếu bảng `edges` rỗng + `npm run build && preview` | |
| `make freeze` | `pg_dump | gzip > data/snapshot.sql.gz` + `git tag demo-freeze` | |

### Runtime entry points

- **API**: `uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload` (docker-compose command), cổng 8000.
- **Startup hook** `main.py:@app.on_event("startup")` — spawn thread chạy `passability.warm(default_scene())`.
- **Healthz** `GET /healthz` — trả cả `persistence: bool` và danh sách `degraded` khi không có PostGIS (main.py, có docstring giải thích rõ 4 đường xuống cấp im lặng).
- **Frontend**: Vite, `apps/web/src/main.tsx` → `App.tsx`. Scene chọn qua query param `?scene=`, tick qua `?t=`, rehearsal route qua `?route=lon1,lat1,lon2,lat2`.
- **Redis** khai báo trong docker-compose và `REDIS_URL` được truyền vào api, nhưng **không module Python nào trong `app/` import redis** — cache hiện đều là in-process dict (`sc._pi_cache`, `_bytes_cache`, `functools.lru_cache`).

### Test suite

- 14 file test, ~102 hàm `test_*` khai báo trực tiếp (chưa tính parametrize/hypothesis expansions).
- `tests/conftest.py` định nghĩa `needs_scenario = skipif(not (DATA/"scenarios"/"thuduc_meta.json").exists())` — **toàn bộ test phụ thuộc kịch bản sẽ SKIP nếu chưa chạy `make storm`**.
- Thư mục `data/` hiện **không tồn tại** trong bản artifact này → không thể chạy pytest cục bộ nếu chưa `make seed && make storm` (cần Docker + mạng).

---

## 5. Quan sát cần lưu ý trước Phase 1

1. `main.py` include đúng 12 router, không có cơ chế flag nào — Phase 1 sẽ thêm `DEMO_FEATURES` và gate ở đây.
2. `ops.py` là **một router duy nhất** trộn closure (SPINE) và outage (PHỤ). Không thể tắt cả router; phải gate ở mức endpoint hoặc ẩn nút phía UI.
3. `passability.warm()` lặp qua 4 vehicle × T tick — chi phí startup này không đổi khi de-scope, vì nó thuộc spine.
4. Frontend hardcode `MAX_TICK = 48`; API trả `sc.T` từ meta. Nếu spec đổi số tick, hai bên lệch nhau (ghi nhận, không thuộc scope Phase 1).

---

## 6. Câu hỏi cần anh xác nhận trước khi sang Phase 1

**#1 — `/v1/ops/queue`, `/ops/sensor-coverage`, `/ops/replay-metrics`, `/ops/override-log`.**
Chỉ đạo nói "tắt phần ops sensor-outage, giữ ops closure". Bốn endpoint trên không phải outage nhưng cũng không nằm trên chuỗi giá trị. Riêng `sensor-coverage` đang được `App.tsx` dùng cho lớp phủ "vùng cảm biến thấy được" — nó là lập luận trung thực về giới hạn dữ liệu, khá có giá trị demo. Tắt hết hay chỉ tắt nút outage + tab `queue`/`metrics`?

**#2 — `modelcard.py` và `provenance.py`.**
Không nằm trên chuỗi giá trị, nhưng là phần "chúng tôi không khẳng định điều gì" — thường được giám khảo hackathon đánh giá cao. Đề xuất của tôi: **giữ bật**, vì chi phí bằng 0 và chúng chống lại cáo buộc thổi phồng. Anh quyết.

**#3 — `tiles.py`.**
Chỉ đạo liệt kê `tiles` vào nhóm bật. Nhưng `/v1/tiles` cần PostGIS và **UI demo không hề gọi nó** (docstring dòng 1-2 tự nhận điều này; `healthz` cũng liệt nó vào danh sách degraded). Bật nó không hại gì nhưng cũng không thêm gì. Xác nhận vẫn bật?

**#4 — `active.py` / hàng đợi active sensing.**
Đây là "hệ thống tự biết mình chưa biết gì" — về mặt kỹ thuật là nhánh phụ, nhưng nếu anh muốn kể câu chuyện thu thập dữ liệu tương lai (liên quan trực tiếp Phase 3 camera) thì nó là cầu nối. Giữ hay tắt?

**#5 — Test.**
`data/` không có trong artifact. Phase 1 yêu cầu "chạy lại pytest, 122 test xanh" — điều đó cần Docker + `make seed` + `make storm` (và `make fetch` cần mạng). Trước khi vào Phase 1, xin xác nhận: môi trường Docker có sẵn để tôi chạy thật, hay tôi chỉ được sửa code và anh tự chạy test?
