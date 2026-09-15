# SCALE_ANALYSIS

Phase 6. Read-only. Đánh giá khả năng scale-up trên ba trục: **geography**, **data**,
**users**. Không sửa code, không đề xuất code trong phase này.

Phần lớn nguyên liệu là **gom lại** từ ba tài liệu đã có — `ROUTING_ANALYSIS.md` (đo
trên scene `thuduc`, 25,811 directed edges), `DATA_REGISTER.md`, `CAMERA_FEASIBILITY.md`.
Phần **mới đo trong phase này** là trục 3 (throughput + RAM/instance) và phần multi-scene
ở trục 1; các số đó được đánh dấu **[đo Phase 6]** kèm cách đo.

Quy tắc của tài liệu: mỗi khẳng định phải có số hoặc giới hạn cụ thể. Chỗ nào không đo
được thì viết thẳng **"chưa đo"**.

Baseline mọi con số: scene `thuduc`, 25,811 directed edges, 11,944 nodes,
ensemble `(49, 25811, 32)` float32, spec hash `5ad137a14513`.

---

## Trục 1 — GEOGRAPHY (phạm vi địa lý)

### 1.1 Sáu điểm gãy đã đo khi đi từ district → city

Tất cả từ `ROUTING_ANALYSIS.md §C.3`, giữ nguyên số đo. Mục tiêu giả định của cột
"city-scale" là **1,000,000 directed edges** (≈ 39× hiện tại, cỡ TP.HCM toàn thành).

| # | Điểm gãy | District (25,811 edges) | City (1M edges) | Loại |
|---|---|---|---|---|
| 1 | **Ensemble tensor** `O(T·E·N)` float32 | 161.9 MB (file trên đĩa 154.4 MB, mmap) | **6.3 GB**/scene/scenario; slice 1 tick = 125 MB | tường cứng RAM/IO |
| 2 | **`warm()` precompute** `O(T·V·E·N)` = 49 tick × 4 vehicle = 196 layer | ~20 s | **~13 phút** | startup |
| 3 | **`_tick_layer` một tick** | 102 ms cold / 0.006 ms cached | ~4.0 s cold | latency cold-path |
| 4 | **A\* → Dijkstra degradation** — heuristic bound *travel time*, objective là travel time + risk. Ratio `cost/tt` tại tick 22: m=0 mean 1.21 → **m=16 mean 13.34, p95 95.03** | p95 127.6 ms (3 lượt search chuỗi) | dự kiến **giây/query** | thuật toán |
| 5 | **BUG — arrival tick tính từ cost đã phạt, không phải travel time thật** (`router.py:176`). Đo: m=16, trip 549 s → search tưởng đã trôi 1296 s (**×2.4**) | vô hại (trip 7 phút, horizon 245 phút) | trip 45 phút @ m=16 → perceived elapsed **vượt 48-tick horizon**, saturate ở tick cuối → mọi edge bị định giá theo trạng thái cuối bão | **lỗi đúng-sai**, hiện bị hình học district che |
| 6 | **BUG — cache cap đếm entry, không đếm byte** (`router.py:144-145`, `passability.py:92-93`: evict khi `len > 900`) | fast-layer 2.5 MB/entry → 900 entry = **~2.2 GB** nếu cache đầy | 97 MB/entry → **vài entry là hết RAM** | bound sai đơn vị |
| + | **Snap là linear scan** `argmin` toàn bộ core node (`router.py:90-92`), `O(nodes)` mỗi origin/destination/waypoint | 11,944 node | 1M+ node × 2-8 lần/query | cần spatial index trước khi cần đổi router |

Hai cái cần sửa **trước** mọi việc scale, vì chúng là bug chứ không phải tuning
(`ROUTING_ANALYSIS §D.1`): **#5 arrival tick** và **#6 cache bound theo byte**.

### 1.2 Hướng scale router: OSRM/Valhalla vs CH tự làm

Tóm tắt `ROUTING_ANALYSIS §D.2`, không mở lại tranh luận.

| | (a) OSRM / Valhalla + risk làm edge weight | (b) Contraction Hierarchies tự viết |
|---|---|---|
| Gains | turn restriction, turn cost, road hierarchy, map-matching, alternatives, isochrone — đều là thứ codebase này **không có**; query city-scale về **single-digit ms** | giữ nguyên cost model, chance constraint và time-dependence là first-class |
| Costs | cả hai engine muốn **một scalar weight/edge**; model hiện tại mang `p_unsafe`, `CVaR90`, `width_norm` riêng biệt | CH giả định metric **tĩnh**; metric đổi mỗi 5 phút theo posterior làm hỏng shortcut set |
| Time-dependence | OSRM traffic update = reload cả graph → tick 5 phút nghĩa là hot-swap weight set mỗi tick | Time-dependent CH khó hơn nhiều; CRP hợp hơn nhưng là công việc nhiều tháng của người đã làm CRP trước đó |

**Insight quyết định — constraint là path-level, không biểu diễn được bằng edge-weight.**
Ràng buộc thật là `sum_{e in path} p_unsafe(e, t_arr(e)) <= ALPHA[vehicle]`
(`router.py:254`, ALPHA = 0.05 cho motorbike/e_2w/car, 0.20 cho response). Không có phép
gán trọng số nào cho từng cạnh biểu diễn được một tổng ràng buộc trên toàn đường đi. Ép
vào edge-weight thì hoặc mất chance constraint, hoặc xấp xỉ bằng phạt Lagrange và mất
guarantee.

**Khuyến nghị (giữ nguyên từ §D.2):** option (a) **lai** — engine ngoài trả *k*
alternatives theo risk weight đã làm phẳng, rồi **re-score từng alternative bằng ensemble
thật trong codebase này** và loại cái vượt `alpha`. Luận điểm an toàn ở lại trong code
mình kiểm soát; phần search giao cho engine giỏi search. Phải nói thẳng cái mất:
guarantee tụt từ *"optimal subject to constraint"* xuống *"best of k checked"*.

Phần sống sót nguyên vẹn qua port: **chính sách chặn**. Edge có `pi < AVOID_PI = 0.55`
bị **loại khỏi search**, không phải bị làm đắt — cả OSRM lẫn Valhalla đều diễn đạt được
bằng infinite weight / access restriction. Phần quan trọng nhất cho an toàn là phần port
được sạch nhất.

### 1.3 Multi-scene / multi-city — gap thật, chưa làm

**Hiện trạng đã đọc code (không suy đoán):**

- `config/bbox.yaml` **đã có 2 scene**: `thuduc` (pilot) và `danang` (frozen transfer
  scene), cùng `default_scene: thuduc`. Registry cấp cấu hình **đã tồn tại**.
- `state.get(scene)` là `@functools.lru_cache(maxsize=2)` (`state.py:207-209`) →
  runtime giữ được **tối đa 2 Scenario cùng lúc**, scene thứ 3 sẽ **evict** một scene
  đang nóng và buộc load lại + warm lại từ đầu.
- `Scenario.__init__` (`state.py:20-46`) load per-scene: `{scene}_meta.json`,
  `{scene}_{spec_hash}_ens.npy` (mmap), `_truth.npy`, `graph.load(scene)`, rồi
  `_build_node_adj()` duyệt toàn bộ `g.n` edge. Mọi thứ đều đã tham số hoá theo `scene` —
  không có hằng số `thuduc` hardcode trong đường load.
- `POST /v1/routes` **đã nhận `scene` optional** (`routes.py:16,21`), fallback
  `default_scene()`. API đã multi-scene-aware.
- **Nhưng `warm()` chỉ chạy cho đúng một scene**: `main.py:122-123` khởi động
  `threading.Thread(target=passability.warm, args=(default_scene(),))`. Scene thứ hai
  **không được precompute** → query đầu tiên vào `danang` đi thẳng vào cold path
  (~102 ms/tick-layer, `_search` cold 327 ms), không phải 30 ms.

**Cần gì để chạy N thành phố — nêu rõ, cả cái đã có lẫn cái thiếu:**

| Hạng mục | Trạng thái | Ghi chú |
|---|---|---|
| Scene registry (config) | **có** | `bbox.yaml`, 2 scene |
| Per-city graph build | **có** | `build_graph.py` chạy theo bbox; `danang` đã build thật |
| Per-scene scenario load | **có** | đã tham số hoá hoàn toàn theo `scene` |
| API nhận `scene` | **có** | `RouteRequest.scene` |
| Scenario cache | **giới hạn cứng = 2** | `lru_cache(maxsize=2)`; N > 2 thành phố → thrash |
| Warm cho scene ≠ default | **thiếu** | chỉ default scene được warm |
| Ngân sách RAM cho N scene đồng thời | **thiếu** | xem trục 3: 1 scene warm = **1.75 GB working set** [đo Phase 6] → 2 scene ≈ 3.5 GB, chưa đo trực tiếp |
| Routing xuyên thành phố | **không có** | graph dừng ở bbox — đã thấy hệ quả ở `DATA_REGISTER` row 11 (trạm sạc gần nhất cách 7.5 km bị đánh dấu unroutable vì nằm ngoài bbox) |

Nói thẳng: multi-city **không phải rewrite**, nó là 3 việc — nâng `maxsize`, warm theo
danh sách scene, và một ngân sách RAM. Nhưng nó cũng **chưa được chạy thử với N > 1
scene warm cùng lúc**, nên số RAM cho N scene là **chưa đo**.

### 1.4 Kết trục 1

- **Sẵn sàng tới đâu:** district 25,811 edges chạy đúng và nhanh (p50 30 ms warm theo
  Phase 2), scene registry + per-scene load + `scene` param trên API đã có, 2 scene đã
  build thật.
- **Gãy ở đâu:** ensemble 161.9 MB → 6.3 GB @1M edges, warm 20 s → ~13 phút, A* thoái hoá
  về Dijkstra ở m=16, snap `O(n)`, cộng 2 bug (arrival-tick ×2.4, cache cap theo entry);
  `lru_cache(maxsize=2)` chặn cứng ở 2 scene và scene không-default không được warm.
- **Cần gì để đi tiếp:** sửa 2 bug trước (bug-shaped, không phải tuning), thêm spatial
  index cho snap, rồi hybrid OSRM/Valhalla + re-score k-alternatives; multi-city cần
  nâng `maxsize`, warm-list, và một ngân sách RAM đo thật.

---

## Trục 2 — DATA (dữ liệu)

### 2.1 Nguồn dữ liệu hiện có — đã verify

Tóm tắt `DATA_REGISTER.md`. Phân loại theo cái quan trọng nhất: **thật vs mô phỏng**.

| Nhóm | Nguồn | Thật / mô phỏng | Số đo |
|---|---|---|---|
| Hình học | OSM Overpass (road/alley + tags) | **real geometry**, ODbL | 25,811 directed edges; **21,067 (81.6%) là alley-class** |
| Địa hình | Copernicus GLO-30 DEM | **real nhưng thô** | 30 m — không phân giải nổi microtopography của hẻm |
| Gazetteer | OSM POI + way names | **real**, `source: osm` trên mọi entry | 517 POI + 1,368 street (Thủ Đức); 344 POI (Đà Nẵng) |
| Ambient | **Open-Meteo** Forecast + Air Quality (CAMS) | **QUAN TRẮC THẬT** — lớp động duy nhất không mô phỏng | 9 điểm mẫu collapse thành **4 source cell cách nhau ~7.8 km**; chạy theo **đồng hồ thực**, không theo tick |
| Trạm sạc | OSM `amenity=charging_station` + buffer 12 km | vị trí **real**, reachability **mô phỏng** | **0 trạm trong cả 2 bbox**; gần nhất cách tâm Thủ Đức **7.5 km** — không bịa pin nào |
| Bão / ensemble | `app/sim` storm generator | **SIMULATED** | `(49, 25811, 32)` |
| Gauge / camera feed | OSSE từ truth run | **SIMULATED** | 38 sensor |
| User report | demo flow | **SIMULATED** (`is_synthetic=true` trong DB) | thumbnail ≤ 9 KB, blur client-side |
| Drainage κ | latent prior từ DEM sink score + `rng.normal(0, 0.01)` | **INFERRED** | không phải dữ liệu ống thật |

Hai con số về **độ phủ** cần nhắc lại vì chúng định nghĩa trần của mọi tuyên bố:

- **Sensor coverage: 38 sensor chạm 161 / 25,809 edges = 0.8% theo chiều dài.** Phần còn
  lại của bản đồ là **suy luận**, không phải quan trắc. Footprint được báo cáo đúng bằng
  `Scenario.neighbourhood()` (≤3 hop, cùng basin, weight 1 / 0.6 / 0.35 / 0.2), không
  phải viewshed quang học — có test khẳng định bằng nhau.
- **OSM attribute completeness:** `data_quality` chỉ nhận **3 giá trị** — 0.50 cho
  18,542 edge (71.8%), 0.75 cho 7,263 (28.1%), 1.00 cho **4** edge. Tức là ~72% edge được
  mô hình hoá bằng default cho width/surface, hai tag trực tiếp nuôi passability envelope.

Nguồn dữ liệu **thật** đã tích hợp và đã verify: Goong (geocode/gazetteer path),
Open-Meteo (2 API, badged riêng), OSM (geometry + POI + charging), Copernicus DEM.
Nguồn **chưa có dữ liệu thật**: camera, gauge, flood point quan trắc, drainage.

### 2.2 Data INGESTION khi scale — phần chưa ai viết

Câu hỏi thật của trục này không phải "thêm nguồn nào" mà: **nếu observation thật +
camera + crowdsource cùng đổ vào `state.py` assimilation thì cần gì?**

Đường vào đã tồn tại và đã test (`CAMERA_FEASIBILITY §0`): mọi nguồn đều phải trở thành

```
{feed_id, source_class, edge (int index), tick, interval_cm | depth_cm+noise_cm}
```

append vào `sc.user_obs` rồi `sc.bump()`. `_log_lik` (`state.py:88-99`) chỉ có **đúng hai
dạng** likelihood — point và interval — và bản ghi do camera stub sinh ra đã chạy qua
`_log_lik` thật **không sửa một dòng nào trong `state.py`** (`§0.5`, đã kiểm chứng). Về
mặt giao diện, thêm nguồn là việc nhỏ.

Cái **không** nhỏ là ba gap đã phát hiện ở Phase 3 (`CAMERA_FEASIBILITY §C.4`):

**(a) Không có ánh xạ đồng-hồ-thực → tick.** `_log_lik` đọc `ens[o["tick"], ...]`: quan
trắc được so với ensemble **tại tick của chính nó**. Kịch bản hiện tại là một sự kiện
tổng hợp **cố định 49 tick** (245 phút, tick 5 phút). Một camera hay một gauge thời gian
thực **không có tick**. Đây là gap chặn mọi nguồn thật, không riêng camera.

**(b) Ánh xạ camera → edge là thủ công.** Mỗi camera phải được gán vào đúng **chỉ số
edge** nó nhìn. Với **~800 camera toàn TP.HCM** đây là **hạng mục tốn công nhất của cả
tính năng**, và không tự động hoá đáng tin bằng toạ độ đơn thuần vì **góc nhìn** mới
quyết định camera thấy đoạn đường nào — không phải vị trí lắp. Thêm một chế độ hỏng đã
liệt kê: camera lệch hướng sau bảo trì → ánh xạ edge sai **âm thầm**, không tự phát hiện
được.

**(c) `user_obs` không chịu outage filter.** `observations_upto` (`state.py:83-85`) chỉ
lọc `feed_id` theo `self.outages` trên `meta["feeds"]`; `user_obs` được cộng vào **không
qua lọc**. Mọi nguồn đi theo đường `user_obs` — camera, crowdsource, và bất kỳ ingestion
mới nào — **không tắt được** bằng công tắc outage hiện có. Ở quy mô 800 camera, "không
tắt được một feed đang báo sai" là vấn đề vận hành, không phải vấn đề lý thuyết.

Thêm một thứ đã đo cần mang sang thiết kế ingestion, vì nó phản trực giác
(`CAMERA_FEASIBILITY §D`): **quan trắc `DRY` mang nhiều thông tin hơn `FLOODED`** khi
prior đã dự đoán ngập. Đo trên edge 18074, tick 22: `DRY` conf=0.95 đẩy π từ 0.397 →
**0.833** (qua ngưỡng `AVOID_PI = 0.55`, tức là đổi được quyết định định tuyến), trong
khi `FLOODED` conf=0.95 chỉ đưa π 0.397 → 0.357 và entropy gần như không đổi
(3.4657 → 3.4575) — vì bracket `FLOODED` mở đến 120 cm nên likelihood gần phẳng. Ai thiết
kế ingestion mà không biết điều này sẽ kết luận nhầm rằng pipeline "không phản ứng với
ngập".

### 2.3 Điều phải nói thẳng: real-time→tick là công việc scale-data thật sự

Gap (a) **không phải là thêm một nguồn**. Nó là **thay đổi tầng scenario**: chuyển từ một
sự kiện tổng hợp 49-tick đóng băng sang một scenario chạy theo đồng hồ thực, tức là
ensemble phải được sinh/lăn liên tục theo forcing thật, và `tick` phải trở thành một hàm
của thời gian thực chứ không phải một chỉ số vào một mảng đã tính sẵn.

**Nó lớn hơn module camera.** Module camera là một classifier cộng một hàm mapping —
`camera_ingest.py` đã là hàm mapping đó, thuần, không import ML. Còn tầng scenario theo
đồng hồ thực chạm vào `state.py`, vào pipeline sinh ensemble, vào `warm()` (đang
precompute 196 layer cho một horizon **cố định** — một horizon trôi liên tục thì
precompute nghĩa là gì?), và vào cache invalidation.

Thứ tự ưu tiên (nhất quán `ROUTING_ANALYSIS §D.3` và `CAMERA_FEASIBILITY §E`): quan trắc
thật > địa hình/drainage thật > hiệu chuẩn trên một sự kiện có thật > tinh chỉnh cost
model. Camera thuộc **bước 1** vì nó là dữ liệu thật — nhưng nó vẫn xếp **sau** hai điều
kiện tiên quyết **không phải kỹ thuật**: văn bản cho phép từ Sở GTVT, và một scenario
theo đồng hồ thực.

### 2.4 Kết trục 2

- **Sẵn sàng tới đâu:** giao diện đồng hoá đã nhận interval observation từ nguồn nhiễu có
  định danh, có age decay, có giới hạn lan truyền theo basin (≤3 hop), đã test — bản ghi
  camera stub chạy qua `_log_lik` thật không sửa dòng nào; nguồn thật đã tích hợp gồm OSM,
  GLO-30, Open-Meteo (lớp động thật duy nhất).
- **Gãy ở đâu:** (a) không có ánh xạ real-clock→tick (scenario cố định 49 tick),
  (b) camera→edge thủ công, tốn nhất ở quy mô 800 cam, (c) `user_obs` không chịu outage
  filter → không tắt được feed lỗi; và trần dữ liệu hiện tại: **0.8% edge có quan trắc**,
  **71.8% edge thiếu tag width/surface**, drainage là prior suy ra chứ không phải đo.
- **Cần gì để đi tiếp:** làm tầng scenario theo đồng hồ thực **trước** (đây mới là công
  việc scale-data, không phải thêm nguồn), cho `user_obs` đi qua outage filter, và coi
  camera→edge siting là công việc khảo sát có ngân sách — cộng hai điều kiện phi kỹ thuật:
  giấy phép dữ liệu và dữ liệu gán nhãn.

---

## Trục 3 — USERS (số lượng người dùng)

### 3.1 Latency đã đo

Từ `ROUTING_ANALYSIS §C.1` (Phase 2, live HTTP, warm caches):

```
POST /v1/routes  (motorbike, 1 leg)          n=30   p50 = 30.1 ms   p95 = 94.7 ms   max = 127.6 ms
POST /v1/routes  (include_conservative=true) n=20   p50 = 67.0 ms                   max = 127.4 ms
_search single A*                            327.0 ms cold
route() full chain                           266.9 ms cold
_tick_layer(t=22)                            102.3 ms cold / 0.006 ms cached
```

**[đo Phase 6] — cách đo, để lặp lại được:** khởi một instance
`uvicorn app.main:app --host 127.0.0.1 --port 8011` (**không** `--workers`, đúng như
`docker-compose.yml:38` và `run_local.sh:59`), đợi ~60 s cho
`passability.warm(default_scene())` chạy xong, 5 request khởi động bỏ đi, rồi 40 request
tuần tự cùng một OD (Ga Bình Thái → Kha Vạn Cân, `depart_tick=16`, `motorbike` — chính là
case reroute mạnh nhất ở `ROUTING_ANALYSIS` Regime C, tức là **kịch bản nặng nhất**, không
phải trung bình):

```
SEQ  n=40   p50 = 91.9 ms   p95 = 139.8 ms   max = 140.3 ms   mean = 94.2 ms
include_conservative=true, 1 mẫu:  167 ms
```

p50 91.9 ms ở đây **cao hơn** 30.1 ms của Phase 2 vì OD này là case Regime C — escalation
chạy nhiều multiplier và A* đã thoái hoá (điểm gãy #4). Hai số không mâu thuẫn; chúng là
hai đầu của cùng một dải. Máy đo cũng khác (Windows, laptop) nên **không so tuyệt đối
giữa hai phase** — dùng số Phase 6 cho phần throughput dưới đây vì nó đo trên cùng máy,
cùng process.

### 3.2 Throughput thô một instance — suy từ số đo, không bịa

**Giả định phải nêu rõ:**
- **Một process uvicorn, không `--workers`** — đúng cấu hình đang chạy
  (`docker-compose.yml:38`, `run_local.sh:59`).
- `post_routes` là **`def` đồng bộ**, không phải `async def` (`routes.py:19`) → FastAPI
  chạy nó trong anyio threadpool. Nhiều request **có** chạy song song về mặt thread,
  nhưng phần nặng là NumPy + vòng lặp A\* thuần Python, nên **GIL serialize** phần Python.
- Một scene, warm, cache nóng.

**[đo Phase 6] — đo trực tiếp bằng ThreadPoolExecutor, 10 request/luồng:**

| concurrency | n | wall | **RPS** | p50 | p95 |
|---|---|---|---|---|---|
| 1 | 10 | 0.95 s | **10.5** | 91.3 ms | 96.3 ms |
| 2 | 20 | 1.81 s | **11.0** | 181.2 ms | 199.1 ms |
| 4 | 40 | 3.89 s | **10.3** | 374.7 ms | 495.4 ms |
| 8 | 80 | 7.95 s | **10.1** | 776.6 ms | 1138.1 ms |
| 16 | 160 | 11.60 s | **13.8** | 1144.2 ms | 1241.4 ms |

Kết quả này rất sạch và cần đọc đúng: **RPS phẳng ở ~10-11 bất kể concurrency**, trong
khi **p50 tăng gần tuyến tính theo concurrency** (91 → 181 → 375 → 777 ms). Đó là chữ ký
kinh điển của một tài nguyên bị serialize — ở đây là GIL. Thêm luồng **không** thêm
throughput, chỉ thêm hàng đợi.

**Throughput thô một instance, trên OD nặng nhất: ~10 req/s.** Suy từ p50 Phase 2
(30.1 ms) cho OD trung bình thì trần lý thuyết là ~33 req/s, nhưng **con số đó chưa đo
dưới tải song song** — chỉ nói được rằng nó nằm giữa ~10 và ~33 req/s tuỳ hỗn hợp OD.
Không có số RPS nào ngoài dải đó được khẳng định ở đây.

### 3.3 Kiến trúc concurrency — vì sao horizontal scale là đường đúng

Đọc từ code, không suy đoán:

- **App không giữ state cần chia sẻ giữa instance.** Ensemble được `mmap` từ file
  (`state.py:26-27`) — read-only, chia sẻ được ở tầng page cache của OS.
- **Redis khai báo nhưng không dùng.** `docker-compose.yml:16-24` dựng service Redis và
  set `REDIS_URL`, `services/api/requirements.txt:5` pin `redis==5.2.*` — nhưng **không
  một file Python nào trong `services/api/app` import redis**. Không có shared cache,
  không có shared session.
- **DB là best-effort.** `db()` (`deps.py:8`) chỉ được gọi ở 5 chỗ
  (`main.py:137`, `observations.py:60`, `ops.py:148,158`, `tiles.py:20`) và `/healthz`
  báo `persistence:false` với danh sách degraded rõ ràng khi không có DB — API vẫn phục
  vụ route bình thường.
- ⇒ Tải là **read-heavy**, mỗi instance tự đủ.

**Cách scale ngang:** N instance sau một load balancer, **mỗi instance load cùng scenario
ở chế độ read-only** và tự chạy `warm()` của mình. Không cần sticky session cho `/v1/routes`
(request thuần chức năng của body). Đổi lại — và phải nói thẳng — **state tương tác
(closures, outages, `user_obs`) là in-process per-instance** (`state.py:36-39`), nên một
observation gửi vào instance A **không** thấy được ở instance B. Multi-instance mà vẫn
muốn ops override / citizen report nhất quán thì cần một tầng chia sẻ mà hiện **chưa có**
(Redis đang nằm sẵn trong compose, không dùng — đây là chỗ nó sẽ dùng để làm gì).

### 3.4 Giới hạn thật: bị chặn bởi RAM/instance, KHÔNG phải CPU

Đây là phần quan trọng nhất của trục 3 và là phần dễ nói dối nhất.

**[đo Phase 6] — một instance, một scene `thuduc`, sau khi `warm()` xong:**

```
Working set     1,754 MB   (~1.75 GB)
Private commit  2,748 MB   (~2.75 GB)
```

Con số này **lớn hơn nhiều** so với 161.9 MB của ensemble, và lý do đã được §C.3 chỉ ra
trước khi đo: `warm()` precompute **49 tick × 4 vehicle = 196 layer**, cộng `_fast_layer`
convert NumPy → **Python list** (`router.py:142-143`) — 2.5 MB **boxed floats** mỗi entry
tại 25,811 edges. Cache thì cap **theo số entry (900), không theo byte** (bug #6). Nghĩa
là RAM/instance không được kiểm soát bởi một ngân sách, nó là hệ quả phụ của việc warm
bao nhiêu layer.

**Tính thô N instance (giả định tuyến tính, 1 scene/instance, chưa tính OS/overhead):**

| N instance | Working set ước tính | Ghi chú |
|---|---|---|
| 1 | ~1.75 GB | đã đo |
| 4 | ~7 GB | vừa một máy 16 GB |
| 8 | ~14 GB | cần máy 32 GB |
| 16 | ~28 GB | cần máy 64 GB |

Ở ~10 req/s/instance, **16 instance ≈ 160 req/s cần ~28 GB RAM**. Trần thực tế là RAM,
không phải CPU — và đó là lý do câu trả lời "chạy nhiều worker hơn" không miễn phí.

Ba điều làm nhẹ hoặc làm nặng con số này, nêu để không bị đọc quá đơn giản:
- **`mmap` chia sẻ được:** nhiều process trên **cùng một máy** đọc cùng file ensemble sẽ
  share page cache của OS, nên phần 154 MB đó **không** nhân N. Phần nhân N là phần
  precompute Python-object. **Chưa đo** tỉ lệ shared/private thực tế khi chạy nhiều
  instance cùng máy — bảng trên là ước tính bi quan.
- **Scale geography làm nổ số này:** ở 1M edges, mỗi fast-layer entry ~97 MB thay vì
  2.5 MB. Một instance city-scale **chưa đo** và không thể ngoại suy tuyến tính an toàn
  từ 1.75 GB.
- **Multi-scene nhân thêm:** `lru_cache(maxsize=2)` cho phép 2 Scenario cùng process;
  RAM cho 2 scene warm cùng lúc **chưa đo**.

**LLM assistant — giới hạn riêng, phải tách khỏi routing.** Trợ lý không chia trần với
`/v1/routes`: nó bị chặn bởi **quota/rate limit của provider** và độ trễ của lời gọi
ngoài, không bởi RAM hay GIL của instance này. Ở mô hình **BYOK** (người dùng mang key
của mình), trần đó **theo từng người dùng**, không phải theo hệ thống — nghĩa là số
người dùng đồng thời của trợ lý và số người dùng đồng thời của định tuyến là **hai bài
toán capacity khác nhau và phải được nói riêng**. Con số quota cụ thể **chưa đo** trong
phase này.

### 3.5 Kết trục 3

- **Sẵn sàng tới đâu:** app read-heavy và stateless cho `/v1/routes` (ensemble mmap
  read-only, Redis không dùng, DB best-effort với `/healthz` báo degraded rõ ràng) → chạy
  N instance sau load balancer là đường thẳng, không cần refactor.
- **Gãy ở đâu:** **~10 req/s một instance** ở OD nặng nhất và RPS **phẳng** từ
  concurrency 1→16 (GIL serialize) — thêm luồng chỉ thêm p50 (91 → 1144 ms), không thêm
  throughput; một instance warm chiếm **1.75 GB working set**, và cache cap **theo entry
  chứ không theo byte** nên RAM/instance không có ngân sách; state tương tác
  (closures/outages/`user_obs`) là per-instance nên multi-instance chưa nhất quán.
- **Cần gì để đi tiếp:** đổi cache bound sang byte để RAM/instance thành một tham số điều
  chỉnh được; scale ngang bằng process (không phải thread) với ngân sách ~1.75 GB/instance;
  đưa state tương tác ra một tầng chia sẻ (Redis đã có sẵn trong compose, chưa dùng); tính
  capacity của LLM assistant tách bạch theo quota provider / BYOK.

---

## Bảng tổng

| Trục | Hạng mục | District hiện tại (25,811 edges) | City-scale cần gì | Đã đo? |
|---|---|---|---|---|
| **Geo** | Ensemble tensor | 161.9 MB, mmap | 6.3 GB @1M edges; slice/tick 125 MB → cần tiling/streaming | **đã đo** (district), ngoại suy (city) |
| **Geo** | `warm()` precompute | ~20 s (196 layer) | ~13 phút → cần warm theo nhu cầu / precompute offline | **đã đo** + ngoại suy |
| **Geo** | Thuật toán search | A\*, p95 127.6 ms; degrade→Dijkstra ở m=16 (cost/tt mean 13.34) | OSRM/Valhalla + re-score k-alternatives; chấp nhận "best of k" | **đã đo** (ratio), city latency **chưa đo** |
| **Geo** | Snap origin/dest | `O(nodes)` linear scan, 11,944 node | spatial index (bắt buộc trước khi đổi router) | đo gián tiếp qua p95 |
| **Geo** | Bug arrival-tick | ×2.4 inflation @m=16, vô hại ở trip 7 phút | **phải sửa** — trip 45 phút sẽ saturate horizon 48 tick | **đã đo** |
| **Geo** | Bug cache cap | evict theo `len > 900`, không theo byte | cap theo byte | **đã đo** (2.5 MB/entry) |
| **Geo** | Multi-scene | 2 scene trong `bbox.yaml`; `lru_cache(maxsize=2)`; chỉ default scene được warm | nâng maxsize, warm-list, ngân sách RAM/scene | cấu hình **đã đọc code**; RAM N-scene **chưa đo** |
| **Data** | Nguồn thật đã có | OSM, GLO-30, Open-Meteo (lớp động thật duy nhất), OSM charging | + gauge thật, camera, drainage thật | **đã verify** |
| **Data** | Độ phủ quan trắc | 38 sensor → **161/25,809 edge = 0.8%** theo chiều dài | mật độ cao hơn nhiều bậc; camera là ứng viên | **đã đo** |
| **Data** | Chất lượng thuộc tính | `data_quality` 3 mức: 71.8% ở 0.50 | khảo sát width/surface | **đã đo** |
| **Data** | Real-clock → tick | **không có** — scenario cố định 49 tick | scenario theo đồng hồ thực (thay đổi **tầng scenario**) | **đã xác định gap**, chi phí **chưa ước lượng** |
| **Data** | Camera → edge mapping | thủ công | siting thủ công @~800 cam; góc nhìn quyết định, không phải toạ độ | **đã xác định**, giờ công **chưa đo** |
| **Data** | Outage filter cho `user_obs` | **không lọc** (`state.py:83-85`) | mọi nguồn phải tắt được | **đã đo** (đọc code) |
| **Users** | Latency/query | p50 30.1 ms (OD thường) / 91.9 ms (OD nặng), p95 ~140 ms | phụ thuộc router mới; **chưa đo** | **đã đo** |
| **Users** | Throughput/instance | **~10 req/s**, phẳng từ concurrency 1→16 (GIL) | scale bằng process, không bằng thread | **đã đo Phase 6** |
| **Users** | RAM/instance | **1.75 GB** working set (2.75 GB private), 1 scene warm | ngân sách theo byte; city-scale instance **chưa đo** | **đã đo Phase 6** |
| **Users** | Scale ngang | stateless cho `/v1/routes`; Redis khai báo mà **không import** | N instance sau LB; ~28 GB cho ~160 req/s | kiến trúc **đã đọc code**, cụm N-instance **chưa đo** |
| **Users** | State tương tác | per-instance in-process | tầng chia sẻ (Redis đang nằm không) | **đã xác định gap** |
| **Users** | LLM assistant | quota provider / BYOK | capacity **tách khỏi** routing | **chưa đo** |

---

## 3-5 câu cho pitch slide

Dùng được khi giám khảo hỏi C5. Mỗi câu **defensible** — có số đứng sau.

1. **Geography.** Ở quy mô quận, 25,811 edges chạy p50 30 ms warm với precompute 20 giây;
   lên quy mô thành phố (~1M edges) chúng tôi **đã đo được đúng chỗ gãy** — ensemble
   161 MB → 6.3 GB, warm 20 s → ~13 phút, A\* thoái hoá về Dijkstra — nên hướng đi là
   giao search cho OSRM/Valhalla rồi **re-score k-alternatives bằng ensemble của mình**,
   vì ràng buộc an toàn của chúng tôi là **path-level** (`sum p_unsafe <= alpha`) và
   không edge-weight nào biểu diễn được nó.

2. **Data.** Tầng đồng hoá đã nhận quan trắc dạng khoảng từ nguồn có định danh và đã
   test — bản ghi camera chạy qua `_log_lik` thật mà **không sửa một dòng nào** trong
   `state.py` — nên thêm nguồn là thêm vào một giao diện đã có; cái **chưa có** là ánh xạ
   đồng-hồ-thực → tick, và đó là thay đổi **tầng scenario, lớn hơn cả module camera**.

3. **Data, phần trung thực.** Hôm nay **38 sensor chỉ chạm 0.8% chiều dài mạng lưới** và
   71.8% edge thiếu tag width/surface — nên phần còn lại của bản đồ là suy luận, và chúng
   tôi hiển thị đúng như vậy chứ không tô cho đẹp.

4. **Users.** Một instance phục vụ **~10 req/s** và throughput **phẳng từ concurrency 1
   đến 16** — GIL, không phải CPU thiếu — nên scale là chạy nhiều process; trần thật là
   **RAM: 1.75 GB một instance đã warm**, tức ~160 req/s cần khoảng **28 GB**, một con số
   biết trước chứ không phải một lời hứa.

5. **Hai bug chúng tôi tự tìm ra trước khi scale.** Arrival tick đang được tính từ cost
   đã phạt (đo ×2.4 ở `risk_mult=16`) và cache cap đếm entry thay vì byte — cả hai vô hại
   ở quy mô quận và **đều hỏng ở quy mô thành phố**, nên chúng đứng trước mọi việc mở rộng
   trong thứ tự ưu tiên.
