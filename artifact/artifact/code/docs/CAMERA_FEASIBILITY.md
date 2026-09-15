# CAMERA_FEASIBILITY

Đánh giá khả thi việc dùng camera giao thông công cộng TP.HCM làm nguồn quan trắc ngập
cho engine. **Đây không phải tài liệu triển khai.** Tại thời điểm viết, dự án không có
dữ liệu camera và không có một frame nào được gán nhãn. Không có model nào được huấn
luyện, và không có logic ML nào được viết.

Kèm theo tài liệu này là `services/api/app/engine/camera_ingest.py` — một **stub
interface**: enum + hàm mapping thuần, không import ML, không mount vào `main.py`.

Phần kiến trúc và thuật toán viết bằng tiếng Anh; phần đánh giá và khuyến nghị dùng
tiếng Việt.

---

## 0. Đường vào của một observation — trích từ code thật

Camera **bắt buộc tái dùng đúng đường này**. Không tạo format mới.

### 0.1 Citizen report đi vào hệ thống như thế nào

`app/routers/observations.py`:

- Người dùng chọn một **hạng mục**, không đo nước. `CATEGORY_CM` (dòng 11-14) quy đổi
  hạng mục thành khoảng độ sâu:
  `dry (0-3)`, `ankle (3-15)`, `footrest (15-30)`, `wheel_hub (30-50)`, `impassable (50-120)` cm.
- `edge_id` (chuỗi) được đổi sang **chỉ số mảng** qua `sc.g.idx[o.edge_id]` (dòng 38).
- Bản ghi được append vào `sc.user_obs` (dòng 53-56), rồi `sc.bump()` (dòng 57) xoá cache
  hậu nghiệm:

```python
sc.user_obs.append({
    "feed_id": f"user-{len(sc.user_obs)}", "source_class": "community",
    "edge": e, "tick": o.tick, "interval_cm": [lo, hi],
})
```

### 0.2 `state.py` tiêu thụ bản ghi đó ra sao

`Scenario._log_lik` (`state.py:88-99`) — **chỉ có đúng hai dạng likelihood**:

```python
h = self.ens[o["tick"], o["edge"], :]                                   # state.py:90
decay = 0.5 ** ((tick - o["tick"]) / self.meta.get("obs_decay_ticks", 6))  # state.py:91
if "depth_cm" in o:                       # point form
    sig = max(o.get("noise_cm", 4.0), 1.0)
    ll = -0.5 * ((h - o["depth_cm"]) / sig) ** 2
else:                                     # interval form
    lo, hi = o["interval_cm"]; soft = 3.0
    ll = np.log(1e-9 + _sig((h - lo + soft) / soft) * _sig((hi + soft - h) / soft))
return ll * decay
```

Ảnh hưởng lan ra lân cận rồi hợp thành trọng số hậu nghiệm:

- `neighbourhood(o["edge"])` (`state.py:59-79`) — tối đa 3 hop, decay
  `HOP_DECAY = [1.0, 0.6, 0.35, 0.2]`, ràng buộc cùng lưu vực `BASIN_DZ = 2.0 m`.
- `_obs_arrays` (`state.py:102-126`) rải `(edge, obs, influence)`.
- `weights` (`state.py:129-143`) softmax `S[e] += influence * ll[o]` trên chiều member.
- `pi_matrix` (`passability.py:26-35`) marginalise theo trọng số đó.

### 0.3 Các trường thực sự được đọc

| Trường | Bắt buộc | Ai đọc |
|---|---|---|
| `edge` | có | `_log_lik:90`, `_obs_arrays:118` — **int index, không phải chuỗi `edge_id`** |
| `tick` | có | `_log_lik:90-91`, `observations_upto:84-85` |
| `interval_cm` **hoặc** `depth_cm`+`noise_cm` | có | `_log_lik:93-98` |
| `source_class` | có | `source_mix:153` |
| `feed_id` | có | `observations_upto:84` (lọc outage) |

### 0.4 Ba điểm phải đính chính so với phác thảo ban đầu

Phác thảo trong yêu cầu là `{edge_id, depth_hint, weight, source="camera"}`. Ba chỗ
không khớp code thật:

1. **Không có trường `weight` hay `confidence` nào trong schema.** Engine không đọc nó.
   Trọng số ảnh hưởng duy nhất là `HOP_DECAY` theo khoảng cách đồ thị, cộng suy giảm
   theo tuổi. Muốn diễn đạt độ tin cậy của classifier thì **chỉ có một cách hợp lệ: nới
   rộng `interval_cm`**. Khoảng rộng phủ nhiều member hơn → likelihood ít phân biệt hơn
   → hậu nghiệm gần prior hơn. Đây chính là cơ chế fallback ở §D, và nó đã có sẵn.
2. **`edge` là chỉ số mảng, không phải `edge_id`.** Việc quy đổi là của caller.
3. **Tên trường là `source_class`, không phải `source`.** Và `"camera"` **đã là một giá
   trị hợp lệ đang dùng** — `sim/storm.py:30-35` sinh feed mô phỏng với
   `source_class: "camera"`. Nghĩa là `source_mix` trong inspector đã biết hiển thị
   nhãn này. Khác biệt: feed mô phỏng dùng dạng **point** (`depth_cm` + `noise_cm`), còn
   camera thật phải dùng dạng **interval**.

### 0.5 Đã kiểm chứng, không phải suy đoán

Bản ghi do stub sinh ra được đưa thẳng vào `Scenario._log_lik` thật:

```
to_observation("CAM-042", 1234, 22, FloodClass.FLOODED, 0.9)
  -> {'feed_id': 'CAM-042', 'source_class': 'camera', 'edge': 1234,
      'tick': 22, 'interval_cm': [13.8, 120.0]}
sc._log_lik(rec, 22)  -> shape=(32,) finite=True range=[-3.37, -2.57]
```

Engine tiêu thụ được ngay, không sửa một dòng nào trong `state.py`.

---

## A. Data accessibility

Nguồn: cổng camera giao thông của Sở GTVT TP.HCM, `giaothong.hochiminhcity.gov.vn`.

| Thuộc tính | Thực tế | Hệ quả |
|---|---|---|
| Phạm vi | ~800 điểm toàn thành phố | Mật độ tốt ở trục chính, mỏng ở hẻm |
| Truy cập | Công khai, xem không cần đăng nhập | Không có rào kỹ thuật để *xem* |
| API chính thức | **Không có** | Phải lấy ảnh từ endpoint ảnh, tức là scraping |
| Tần suất | Ảnh tĩnh làm mới ~15-18 giây; một số điểm có luồng trực tiếp | Đủ nhanh so với tick 5 phút của engine |
| Độ phân giải | Thấp, nén mạnh, nhiều điểm góc rộng | Ràng buộc quyết định ở §B |

**Rủi ro pháp lý và ToS — phải nói thẳng.**

Dữ liệu công khai để *xem* không đồng nghĩa với được phép *thu thập tự động, lưu trữ và
tái phân phối*. Rủi ro cụ thể:

- Cổng không công bố API nên cũng không công bố điều khoản sử dụng lập trình. Việc
  không có điều khoản **không phải là sự cho phép**.
- Lấy ảnh theo lịch ở quy mô 800 điểm × 4 lần/phút là tải có hệ thống lên hạ tầng công.
  Về kỹ thuật là scraping, và có thể bị chặn IP bất cứ lúc nào — nghĩa là một sản phẩm
  dựng trên đó có thể chết mà không báo trước.
- Ảnh camera đường phố chứa biển số và người đi đường. Lưu frame thô tạo nghĩa vụ bảo
  vệ dữ liệu cá nhân theo Nghị định 13/2023/NĐ-CP. Dự án này đã có lập trường về vấn đề
  đó ở luồng citizen report (invariant I7: chỉ nhận thumbnail 64×64 đã làm mờ phía
  client, `observations.py:15,45-50`), và một module camera phải giữ đúng lập trường:
  **phân loại tại chỗ, chỉ truyền nhãn ordinal, không lưu frame**.

**Kết luận phần A:** dùng cho nghiên cứu/PoC nội bộ thì chấp nhận được với tần suất
thấp và không lưu frame. Dùng cho production thì **phải có văn bản cho phép chính thức
từ Sở GTVT**. Đây là công việc quan hệ đối tác, không phải công việc kỹ thuật, và nó
nằm trên đường tới hạn — không nên bắt đầu bằng việc viết classifier.

---

## B. What can actually be detected from these frames

### B.1 Centimetre-level depth regression is not achievable

Stating this plainly because it is the claim most likely to be over-promised:

- **No reference scale in frame.** Depth in pixels means nothing without a known
  vertical reference at a known distance. These cameras have no calibration target.
- **Unknown, uncalibrated geometry.** Mounting height, pitch and focal length are not
  published and vary per site. Without them, the image-to-ground homography that would
  convert a water line into a depth cannot be recovered.
- **Illumination.** Night sites without dedicated lighting produce frames where the
  road surface is a low-contrast smear. Wet asphalt and standing water are close to
  indistinguishable under sodium or LED street lighting, both being specular.
- **Resolution and compression.** A water line a few centimetres high projects onto
  single-digit pixel counts at typical camera distances, below the compression noise
  floor.

Any pipeline reporting "18 cm" from these frames would be reporting a number the imagery
does not contain.

### B.2 What is achievable

**Option 1 — ordinal classification (recommended).** Three classes plus an abstention,
as defined in `camera_ingest.py`:

| Class | Visual criterion | Bracket (cm) |
|---|---|---|
| `DRY` | No standing water on carriageway | 0 – 3 |
| `WET` | Surface water present; road markings and kerb line still readable | 3 – 15 |
| `FLOODED` | Water obscuring markings or reaching kerb height | 15 – 120 |
| `UNKNOWN` | Night, occluded lens, offline, or low confidence | *no observation* |

The `FLOODED` bracket is deliberately open-ended to 120 cm. A camera cannot separate
20 cm from 60 cm, and pretending otherwise is exactly the failure mode §B.1 warns about.

**Option 2 — water line against a fixed landmark.** Where a site has a persistent
vertical reference in frame — a kerb, a pole base, a median edge — the water line can be
tracked against that landmark across frames. This gives a *relative* signal ("water is
rising past the kerb") that is more precise than the three-class call, and it degrades to
Option 1 when the landmark is occluded. It requires per-camera manual annotation of the
reference object, so it does not scale to 800 sites without effort, but it is the natural
upgrade for a handful of high-value locations.

**Ordinal, not regression, is also the right shape for the engine.** `_log_lik` already
has an interval branch built for exactly this — it was written for categorical citizen
reports (`state.py:96-98`, comment "interval observation (categorical, M5)"). A camera
classifier producing ordinal calls fits an interface that already exists and is already
under test.

---

## C. Integration architecture

### C.1 The camera is a likelihood, never an engine

The design constraint, in one line: **physics ensemble = prior; camera = observation
update**. The camera never writes state, never overrides a band, and never touches
routing cost.

```
  frame  ──►  classifier  ──►  {FloodClass, confidence}
                                      │
                                      ▼   camera_ingest.to_observation()
                       {feed_id, source_class="camera", edge, tick, interval_cm}
                                      │
                                      ▼   sc.user_obs.append(...) ; sc.bump()
                       state.py  _log_lik ──► neighbourhood (≤3 hop, same basin)
                                      │
                                      ▼
                       weights (posterior over 32 ensemble members)
                                      │
                       ┌──────────────┴──────────────┐
                       ▼                             ▼
              quantiles p10/p50/p90            pi_matrix (passability)
                       │                             │
                       └──────────────┬──────────────┘
                                      ▼
                         router.py  _tick_layer  (p_unsafe, CVaR90, width)
```

**Nothing in the routing layer changes.** Confirmed in Phase 2: `router.py` reads `pi`,
`cvar` and `width_norm` directly (`router.py:33-44`) and never reads the risk band. A
camera improves the posterior; the cost function consumes the improved posterior without
knowing where it came from. That is the property that makes this a module rather than a
rewrite.

### C.2 Interface contract

Producer side, which does not exist yet:

```
classify(frame) -> (FloodClass, confidence: float in [0, 1])
```

Bridge, which exists as a stub:

```
camera_ingest.to_observation(camera_id, edge, tick, flood_class, confidence)
    -> dict | None
```

Consumer side, which exists and is tested:

```
sc.user_obs.append(record); sc.bump()      # observations.py:52-57 does exactly this
```

`None` is a normal return, not an error. Abstention and low confidence produce no record
at all.

### C.3 Where active-sensing fits

`app/engine/active.py` was deliberately retained through the Phase 1 de-scope, and this
is why. `active.queue()` ranks edges by

```
EIG × Impact × Reachability / (1 + SafetyRisk)          # active.py:12-31
```

where `EIG` is normalised posterior spread, `Impact` counts how often recent route
queries touched the edge (`sc.recent_routes`, `active.py:18-21`), and edges already
believed flooded are excluded.

Today it answers "which edge should a person be asked to report on". With a camera fleet
it answers a more useful question: **which of the 800 cameras is worth pulling and
classifying right now**. Fetching and running inference on 800 streams every 15 seconds
is neither necessary nor polite to the source. Ranking by decision-weighted information
gain turns that into a bounded budget — pull the top *k* cameras whose state most affects
routes people are actually asking for.

The only change needed is the candidate set: rank camera-covered edges instead of all
unobserved edges. The scoring function itself carries over unchanged.

### C.4 Interface gaps — chưa giải quyết, phải nói ra

Ba khoảng trống thật, phát hiện khi đọc code, không được che:

1. **Không có ánh xạ đồng hồ thực → tick.** `_log_lik` đọc `ens[o["tick"], ...]`, tức là
   quan trắc được so với ensemble **tại tick của chính nó**. Kịch bản hiện tại là một sự
   kiện tổng hợp cố định 49 tick. Camera thời gian thực không có tick. Muốn dùng thật thì
   phải có một scenario chạy theo đồng hồ thực — đây là thay đổi ở tầng scenario, không
   phải ở tầng camera, và nó lớn hơn bản thân module camera.
2. **Ánh xạ camera → edge là công việc thủ công.** Mỗi camera cần được gán vào đúng chỉ
   số edge mà nó nhìn. Với 800 camera đây là công việc siting tốn công nhất của cả tính
   năng, và không tự động hoá được đáng tin bằng toạ độ đơn thuần vì góc nhìn quyết định
   camera thấy đoạn đường nào.
3. **`user_obs` không chịu bộ lọc outage.** `observations_upto` (`state.py:83-85`) chỉ
   lọc `feed_id` theo `self.outages` trên `meta["feeds"]`, còn `user_obs` được cộng vào
   không qua lọc. Camera đi theo đường `user_obs` sẽ **không tắt được** bằng công tắc
   outage hiện có. Đây là một khoảng trống có thật; sửa nó là việc của tương lai, không
   phải của phase này.

---

## D. Failure modes

Đêm, mưa che ống kính, camera offline, góc nhìn bị xe tải che — tất cả đều dẫn về cùng
một hành vi: **confidence thấp → khoảng rộng → hậu nghiệm quay về prior**. Đây không phải
lời hứa, đã đo được.

Thí nghiệm: edge index 18074 tại tick 22, ensemble trải 12.0-53.6 cm trên 32 member.
Entropy trọng số đều = 3.4657 (tức là chưa quan trắc gì).

Quan trắc `DRY` (mâu thuẫn với prior, nên có sức kéo):

| confidence | `interval_cm` | p50 | π | weight entropy |
|---|---|---|---|---|
| *(prior)* | — | 21.09 cm | 0.397 | 3.4657 |
| 0.95 | [0.0, 3.6] | 14.97 cm | **0.833** | **2.5971** |
| 0.70 | [0.0, 6.6] | 14.97 cm | 0.825 | 2.6430 |
| 0.50 | [0.0, 9.0] | 14.97 cm | 0.813 | 2.7045 |
| 0.36 | [0.0, 10.7] | 15.14 cm | 0.800 | 2.7612 |
| *(UNKNOWN)* | — *(không sinh bản ghi)* | 21.09 cm | 0.397 | 3.4657 |

Entropy tăng đơn điệu 2.5971 → 2.7612 khi confidence giảm 0.95 → 0.36: hậu nghiệm trượt
dần về prior đúng như thiết kế. Dưới `MIN_CONFIDENCE = 0.35`, và với `UNKNOWN`, không có
bản ghi nào được sinh — prior đứng nguyên vẹn.

Ở ví dụ trên, một quan trắc `DRY` tự tin đẩy π từ 0.397 lên 0.833, tức là đưa edge từ
sát ngưỡng `AVOID_PI = 0.55` lên vùng đi được. Đó là ảnh hưởng thật lên định tuyến — và
đó cũng chính là lý do ngưỡng confidence phải được đặt cẩn thận.

**Một phát hiện ngược trực giác, đáng ghi:** quan trắc `FLOODED` có sức kéo **yếu hơn**
`DRY` trên cùng edge:

| | `interval_cm` | p50 | π | entropy |
|---|---|---|---|---|
| FLOODED conf=0.95 | [14.4, 120.0] | 22.99 cm | 0.357 | 3.4575 |
| FLOODED conf=0.50 | [9.0, 120.0] | 22.76 cm | 0.389 | 3.4654 |

Lý do: bracket `FLOODED` mở đến 120 cm nên phủ gần hết các member phía trên — likelihood
gần như phẳng, ít phân biệt. Nói cách khác, **camera báo "khô" mang nhiều thông tin hơn
camera báo "ngập"**, khi prior vốn đã dự đoán ngập. Điều này hợp lý về mặt lý thuyết
thông tin, nhưng nó ngược với kỳ vọng thường thấy và cần được nêu trước khi ai đó kết
luận module camera "không phản ứng với ngập".

Các chế độ hỏng còn lại:

| Chế độ | Biểu hiện | Xử lý |
|---|---|---|
| Camera offline | Không có frame | Không sinh bản ghi; suy giảm theo tuổi (`state.py:91`) làm nhạt dần quan trắc cũ |
| Mưa che ống kính | Frame mờ toàn phần | Classifier trả `UNKNOWN` |
| Đêm không đèn | Không phân biệt được ướt/ngập | `UNKNOWN`, hoặc `WET` với confidence thấp |
| Xe tải che khuất | Frame hợp lệ nhưng không thấy mặt đường | `UNKNOWN`; nếu classifier không phát hiện được che khuất thì đây là nguồn sai lệch nguy hiểm nhất và phải nằm trong tập nhãn |
| Camera lệch hướng sau bảo trì | Ánh xạ edge sai âm thầm | Không tự phát hiện được. Cần đối chiếu định kỳ; là lý do `feed_id` phải ổn định theo camera |

---

## E. Kết luận

**Khả thi như một module tương lai — và kiến trúc đã sẵn sàng.**

Đây là điểm đáng nói nhất trong pitch, và nó kiểm chứng được chứ không phải lời quảng
cáo: tầng đồng hoá đã nhận quan trắc dạng khoảng từ nguồn nhiễu có định danh, đã có suy
giảm theo tuổi, đã có giới hạn lan truyền theo lưu vực, và đã được test. Bản ghi do stub
sinh ra chạy qua `_log_lik` thật mà không sửa một dòng nào trong `state.py` (§0.5).
Thêm camera là **thêm một nguồn vào một giao diện đã có**, không phải xây lại engine.

**Không nằm trong phạm vi hackathon.** Lý do đơn giản và không nên vòng vo: không có dữ
liệu gán nhãn. Không có frame nào được gán nhãn thì không có classifier; không có
classifier thì phần "camera" chỉ là một hàm mapping — đúng bằng cái đang có trong
`camera_ingest.py`, và đó là mức trung thực nhất có thể trình bày.

Ngoài ra còn hai điều kiện tiên quyết **không phải kỹ thuật**, đã nêu ở §A và §C.4:
văn bản cho phép từ Sở GTVT, và một scenario chạy theo đồng hồ thực.

### Đề xuất phạm vi PoC tối thiểu (đề xuất, không cam kết)

Nếu sau này xin được dữ liệu, phạm vi nhỏ nhất đủ để trả lời "có làm được không":

| Hạng mục | Đề xuất | Lý do |
|---|---|---|
| Phạm vi | **1 tuyến camera pilot**, khoảng 5-10 điểm trên một hành lang hay ngập | Đủ để phủ một chuỗi edge liên tục, đủ nhỏ để gán nhãn thủ công |
| Dữ liệu | **200-500 frame gán nhãn**, cân bằng giữa 3 lớp, **bắt buộc có frame đêm và frame mưa** | Tập nhỏ hơn sẽ không đo được lớp `UNKNOWN`, vốn là lớp quyết định độ an toàn |
| Model | Ordinal classifier, backbone nhỏ đã pretrain, fine-tune | Không cần kiến trúc mới; bài toán là 3 lớp trên ảnh chất lượng thấp |
| Chỉ số | Độ chính xác theo lớp + **tỉ lệ bỏ sót `FLOODED`** + độ hiệu chuẩn confidence | Bỏ sót ngập là lỗi nguy hiểm; confidence sai hiệu chuẩn phá cơ chế fallback ở §D |
| Ngưỡng chấp nhận | Bỏ sót `FLOODED` dưới một mức thoả thuận trước, trên tập test đêm/mưa riêng | Đặt trước khi nhìn kết quả |
| Không làm | Hồi quy độ sâu; tự động hoá ánh xạ camera→edge; mở rộng 800 điểm | Đã giải thích ở §B.1 và §C.4 |

Các con số 200-500 frame và 5-10 camera là **đề xuất điểm khởi đầu**, không phải cam
kết. Con số thật phụ thuộc vào việc hành lang được chọn có bao nhiêu sự kiện ngập được
ghi lại — và điều đó chỉ biết được sau khi có quyền truy cập dữ liệu.

### Thứ tự ưu tiên

Nhất quán với `ROUTING_ANALYSIS.md §D.3`: camera là **nguồn dữ liệu thật**, nên nó thuộc
bước 1 của thứ tự ưu tiên đó, không phải bước 4. Một classifier ordinal thô trên dữ liệu
thật cải thiện điều có thể khẳng định được nhiều hơn bất kỳ tinh chỉnh nào của hàm chi
phí. Nhưng nó vẫn xếp sau việc **xin được dữ liệu** và **có scenario theo đồng hồ thực**
— hai việc mà không dòng code nào giải quyết được.
