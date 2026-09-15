# Đề xuất tính năng tích hợp LLM & AI — Đường An VN

**Trạng thái**: F1 ĐÃ TRIỂN KHAI (2026-08-20), **lớp neo địa lý F1-grounding ĐÃ TRIỂN KHAI
(2026-08-21)** — `services/api/app/routers/assistant.py`, `app/engine/gazetteer.py`,
`app/engine/narrate.py`, `scripts/build_gazetteer.py`, `apps/web/src/panels/AssistantPanel.tsx`;
các mục F2–F10 còn lại là đề xuất · **Ngày**: 2026-08-21
**Hai nguyên tắc bất di bất dịch**: (1) LLM **không bao giờ quyết định an toàn**;
(2) LLM **không bao giờ tự sinh địa lý** — mọi địa điểm phải tra ra từ gazetteer OSM,
không khớp thì từ chối chứ không đoán (xem §2b). Mọi con số
(độ sâu, xác suất π, band, tuyến đường) đến từ engine vật lý đã kiểm chứng (I1–I7);
LLM chỉ làm ba việc: **diễn giải** (số → ngôn ngữ), **trích xuất** (ngôn ngữ → cấu trúc,
có xác thực), và **điều phối** (gọi các API `/v1/*` sẵn có qua tool-use). Đầu ra LLM
không được ghi vào trạng thái engine nếu không qua cùng lớp validate như mọi input khác.

---

## 1. Danh mục tính năng đề xuất

| # | Tính năng | Cơ chế | API surface (Claude) | Độ khó | Giá trị |
|---|---|---|---|---|---|
| F1 ✅ | **Trợ lý hành trình hội thoại** — "7h sáng mai đi từ Linh Xuân đến chợ Thủ Đức bằng xe máy có ổn không?" → agent gọi `/v1/routes`, `/v1/weather`, `/v1/state`, trả lời tiếng Việt kèm tuyến vẽ trên bản đồ | Tool-use agent (tool runner) trên chính các endpoint demo; LLM chỉ chọn *gọi gì* và *diễn đạt*, số liệu nguyên vẹn từ engine | `claude-opus-5`, adaptive thinking, `@beta_tool` + `client.beta.messages.tool_runner`, streaming SSE | Trung bình (1 ngày hackathon) | ⭐ Demo "wow" + đúng trọng tâm Data & AI Innovation của đề bài — **đã có, kèm lớp neo địa lý §2b** |
| F2 | **Diễn giải cảnh báo theo ngữ cảnh** — biến `reason_codes` + comparison JSON thành 1–2 câu tiếng Việt tự nhiên, sẵn sàng cho TTS khi đang lái xe ("Tránh Võ Văn Ngân đoạn chợ: nước đang dâng, bằng chứng 4 phút trước từ camera") | Một lệnh gọi đơn, structured input → text; system prompt cấm thêm số liệu ngoài input | `claude-opus-5`; prompt caching cho system prompt | Thấp (nửa ngày) | Nâng UX rõ rệt; an toàn vì input đóng |
| F3 | **Trích xuất báo cáo dạng tự nhiên** — người dân nhắn "nước tới yên xe trước chợ Thủ Đức, xe chết máy nhiều lắm" → `{edge_candidates, depth_interval, vehicle_context, confidence}`; đi qua **đúng pipeline validate** của `/v1/observations` | Structured outputs (`client.messages.parse`, strict schema); LLM đề xuất — engine xác thực (edge tồn tại? vị trí khớp? interval hợp lệ?) | `claude-opus-5` + structured outputs | Trung bình | Mở kênh báo cáo qua chat/Zalo mà không hạ chuẩn dữ liệu |
| F4 | **Khai thác kênh 1022 / tin chính thống** — đọc bản tin, thông báo đóng đường dạng văn bản → edge-time observations có `source_class=official`, thời hạn hiệu lực | NER + geocoding + structured outputs; chạy **Batch API** (rẻ 50%) cho hindcast, streaming cho realtime | `claude-opus-5`; Batches | Trung bình–cao | Biến văn bản hành chính thành dữ liệu định tuyến — đúng "lớp dữ liệu đặc thù VN" |
| F5 | **Phân tích ảnh báo cáo (pilot, opt-in riêng)** — VLM ước lượng *khoảng* mực nước từ mốc tham chiếu trong ảnh (bậc thềm, bánh xe, cột điện) → interval + độ tin cậy | Vision input; kết quả là *một nguồn likelihood* như camera, không phải chân lý | `claude-opus-5` (vision) | Cao | Tăng độ chính xác báo cáo; **xem mục 3 về xung đột riêng tư I7** |
| F6 | **Bản tin vận hành tự động** — cuối mỗi cơn mưa/ca trực: tóm tắt feeds, guards, disagreement, số báo cáo, tuyến bị từ chối → 1 trang briefing cho đội vận hành | Đọc `/v1/ops/*` + `replay_metrics.json` → văn bản có cấu trúc; chạy nền bằng Batch | `claude-opus-5`; Batches | Thấp | Tiết kiệm giờ trực; tăng minh bạch với thành phố |
| F7 | **Hỏi đáp dữ liệu vận hành** — "phường nào nhiều cạnh đang dâng nhất?", "camera nào hay mất tín hiệu?" → LLM sinh lệnh gọi API trong whitelist, trả bảng + giải thích | Tool-use giới hạn read-only endpoints; không bao giờ sinh SQL tự do | `claude-opus-5` | Trung bình | Ops mode thành hội thoại; giữ audit trail |
| F8 | **Lời nhắn active-sensing** — sinh yêu cầu xác minh lịch sự, đúng ngữ cảnh cho từng edge trong queue ("Nếu anh/chị đang ở gần X *và đang ở nơi an toàn*, nước tới đâu ạ?") kèm nhắc an toàn bắt buộc | Template + LLM cá nhân hoá; câu nhắc an toàn là hằng số code, LLM không được sửa | `claude-opus-5` | Thấp | Tăng tỷ lệ phản hồi crowd mà không đổi chính sách an toàn |
| F9 | **Q&A minh bạch về hệ thống** — người dùng/giám khảo hỏi "vì sao đường này đỏ?", "hệ thống không biết gì?" → trả lời từ model card + DECISIONS + provenance của đúng edge đó | RAG nhẹ trên docs của repo + `/v1/provenance` | `claude-opus-5` | Thấp | Chuyển "claim discipline" của proposal thành trải nghiệm |
| F10 | **Residual học ₣θ (GNN)** — *AI không-LLM*, đã có trong proposal (C2, stretch): học phần dư của mô hình vật lý từ dữ liệu mô phỏng/thực | PyTorch GNN sau feature flag, fallback vật lý thuần | — (không phải Claude API) | Cao | Đường khoa học dài hạn; tách bạch khỏi các tính năng LLM |

**Ghi chú mô hình**: mặc định đề xuất `claude-opus-5` (adaptive thinking) cho mọi tính năng.
Với các luồng khối lượng lớn (F3/F4/F6 ở quy mô pilot), có thể hạ xuống
`claude-haiku-4-5` (~$1/$5 mỗi triệu token) hoặc `claude-sonnet-5` — đó là quyết định
chi phí của chủ dự án, không phải mặc định kỹ thuật.

---

## 2. Kiến trúc tích hợp (F1 làm ví dụ chuẩn)

```
Người dùng ⇄ SSE /v1/assistant (FastAPI)
                 │  Anthropic Python SDK — tool runner, streaming
                 ▼
        claude-opus-5 (adaptive thinking, system prompt cache)
                 │ tool calls (JSON, strict)
                 ▼
   @beta_tool wrappers — CHỈ gọi engine nội bộ:
   get_route(o,d,waypoints,tick,vehicle) → /v1/routes
   get_area_weather(bbox,tick)           → /v1/weather
   get_edge_state(edge_id,tick)          → /v1/passability
   (read-only; không có tool nào ghi trạng thái)
```

Phác thảo (Python SDK chính thức; tool runner beta):

```python
import anthropic
from anthropic import beta_tool

client = anthropic.Anthropic()

@beta_tool
def get_route(o_lon: float, o_lat: float, d_lon: float, d_lat: float,
              depart_tick: int, vehicle: str) -> str:
    """Tính tuyến an toàn giữa hai điểm trong vùng demo Thủ Đức.

    Args:
        o_lon: Kinh độ điểm đi.
        o_lat: Vĩ độ điểm đi.
        d_lon: Kinh độ điểm đến.
        d_lat: Vĩ độ điểm đến.
        depart_tick: Thời điểm khởi hành (tick 0–48, mỗi tick 5 phút).
        vehicle: motorbike | e_2w | car | response.
    """
    import json
    from app.engine import state, router
    sc = state.get("thuduc")
    res = router.route(sc, vehicle, (o_lon, o_lat), (d_lon, d_lat), depart_tick)
    return json.dumps({...})   # số liệu engine, nguyên vẹn

SYSTEM = """Bạn là trợ lý Đường An VN... KHÔNG BAO GIỜ tự bịa số liệu độ sâu,
xác suất hay tên đường; chỉ dùng kết quả tool. Nếu status=no_safe_route hãy
truyền đạt đề xuất chờ, không gợi ý liều đi qua nước."""

runner = client.beta.messages.tool_runner(
    model="claude-opus-5",
    max_tokens=16000,
    system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
    tools=[get_route, get_area_weather, get_edge_state],
    messages=[{"role": "user", "content": user_text}],
)
```

Điểm thiết kế quan trọng:
- **Tool read-only**: assistant không có tool ghi (không đóng đường, không tạo obs) —
  hành động ghi luôn đi qua UI + validate hiện có.
- **Prompt caching**: system prompt + tool schema cố định đứng trước, câu hỏi đứng sau.
- **Streaming**: SSE về UI để phản hồi tức thời trên mạng yếu.
- **F3** dùng `client.messages.parse` với schema strict; field `edge_id` do LLM đề xuất
  chỉ là *ứng viên* — server map-match lại và từ chối như mọi báo cáo khác (chống
  hallucination bằng validate, không bằng niềm tin).

---

## 2b. Lớp neo địa lý (F1-grounding) — ĐÃ TRIỂN KHAI 2026-08-21

### Vì sao cần: LLM không đọc được bản đồ, và kém nhất đúng ở Việt Nam

Bằng chứng công bố, không phải phỏng đoán:

| Nguồn | Phát hiện liên quan trực tiếp |
|---|---|
| GPSBench (57.800 mẫu, 17 task) | Nhận diện **cấp thành phố từ toạ độ dưới 25% với mọi model**; thiên lệch vùng rõ: Bắc Mỹ 75,8% vs **Đông Á 59,6%** |
| GDELT — thử nghiệm geocoder LLM | Ở địa lý ít được đại diện (Ấn Độ): GPT-3.5 55%, **GPT-4 chỉ 32–35% — model mạnh hơn lại tệ hơn** do bias với toponym phi tiếng Anh; 33% bịa địa điểm; cùng prompt ra kết quả khác nhau giữa các lần chạy. Kết luận: "LLM không phù hợp cho geocoding production" |
| MapEval (700 câu, 180 thành phố) | Không model nào vượt **67%**, thua người **>20 điểm**; yếu nhất đúng ở *khoảng cách, hướng, lập tuyến* |
| GeoLLM | Nhồi toạ độ thô cho kết quả kém; **bổ sung POI từ OSM quanh toạ độ → cải thiện lớn** |
| Grounding with Google Maps (Gemini API) | Google — chủ sở hữu bản đồ tốt nhất thế giới — vẫn *tra cứu* 250 triệu địa điểm qua tool chứ không để model tự nhớ |

Thủ Đức nằm đúng trong nhóm "địa lý ít được đại diện", tên đường lại là toponym tiếng Việt
có dấu — giao của hai điều kiện tệ nhất mà các nghiên cứu trên đo được.

### Lỗ hổng cụ thể đã đóng

| # | Lỗ hổng trước 2026-08-21 | Cách đóng |
|---|---|---|
| 1 | `get_route` nhận `o_lon/o_lat/d_lon/d_lat` là float thô → LLM buộc phải **bịa toạ độ** cho "chợ Thủ Đức" | **Không một tool nào còn nhận toạ độ.** Tool nhận *tên*; `find_place` tra gazetteer. Có test khẳng định điều này (`test_no_tool_accepts_coordinates`) |
| 2 | `snap()` là nearest-neighbour **không giới hạn khoảng cách** → toạ độ bịa vẫn snap được, trả tuyến tự tin và sai | `snap_checked()` với `SNAP_MAX_M = 300 m`; ngoài ngưỡng → từ chối. Kiểm tra bbox trước khi snap |
| 3 | `Graph` **không có tên đường**; `build_graph.py` đọc `tags` nhưng vứt `name` → không thể nói "Kha Vạn Cân" mà không bịa | Side-car `{scene}_edge_names.json` → `Graph.name`. 12.819/25.809 cạnh (50%) có tên thật từ OSM |
| 4 | `get_edge_state(edge_id)` **không thể gọi được** trong hội thoại — người dùng không biết mã cạnh | `get_street_state(street_name)` tra theo tên tuyến phố; `get_edge_state` giữ lại cho ops |
| 5 | Không có cách trả lời "khu nào đang xấu nhất" mà không đẩy hình học vào prompt | `get_area_summary` — digest có chú thích đơn vị, top-N tuyến phố có tên; 25.809 cạnh không bao giờ vào prompt |

### Kiến trúc

```
Người dùng ⇄ SSE /v1/assistant
                 ▼
        claude-opus-5 (tool runner)
                 │  chỉ được gọi 6 tool, KHÔNG tool nào nhận toạ độ
                 ▼
   find_place(query)                  → gazetteer OSM: ok | ambiguous | not_found
   plan_route(origin, destination, …) → tự tra tên → validate bbox → snap_checked → engine
   plan_trip(stops[], …, compare_*)   → tầng điều phối tất định (xem §2c)
   get_street_state(street_name, …)   → gộp theo tuyến phố, đoạn xấu nhất quyết định
   get_area_summary(tick, vehicle)    → perception script có đơn vị
   get_area_weather(tick)             → mưa/triều
   get_edge_state(edge_id, …)         → chính xác theo mã cạnh (ops)
                 ▼
        Query IR đã validate → SSE `query` + log audit
```

Gazetteer dựng offline từ OSM (`scripts/build_gazetteer.py`, chạy trong `make seed`):
**1.368 tuyến phố + 517 địa điểm có tên** cho Thủ Đức, tất cả `source: osm`.
Không một toạ độ nào được nhập tay từ trí nhớ mô hình.

### Ba trạng thái, và vì sao "từ chối" là tính năng

`find_place` trả về đúng một trong ba:

- **ok** — một ứng viên rõ ràng. Dùng được.
- **ambiguous** — nhiều ứng viên sát điểm nhau, hoặc tên trùng lặp ("Khu phố 14" xuất hiện
  nhiều lần). LLM **phải hỏi lại**, cấm tự chọn.
- **not_found** — không có trong vùng. Có thể kèm `did_you_mean` để hỏi, **cấm dùng để đặt tuyến**.

Hai ngưỡng tách biệt là điểm mấu chốt: chỉ khớp **cấu trúc** (trùng tên, biến thể danh từ
đầu, tiền tố, chứa trọn token) mới đủ điều kiện thành câu trả lời (`ACCEPT_SCORE = 0.86`).
Khớp *na ná* chuỗi chỉ được làm gợi ý (`SUGGEST_SCORE = 0.62`). Nếu không tách, "chợ Bến Thành"
(Quận 1) khớp tự tin vào "Trương Văn Thành" ở Thủ Đức — đúng kiểu sai lặng lẽ mà cả lớp này
sinh ra để chặn. Có test cho từng ca: Bến Thành, phố Hàng Bạc, Hồ Gươm đều phải `not_found`
với `candidates == []`.

Một chi tiết dễ bỏ sót: OSM chứa cùng con đường dưới hai tên ("Võ Nguyên Giáp" 156 cạnh /
4,1 km và "Đường Võ Nguyên Giáp" 2 cạnh / 239 m). Xếp hạng thuần theo điểm khớp chuỗi sẽ
đẩy cách nói tự nhiên nhất trong tiếng Việt ("đường Võ Nguyên Giáp") vào **mẩu cụt 239 m**.
Nên khi gộp biến thể, nhánh **dài nhất** thắng, không phải nhánh khớp cao nhất.

### Chọn bằng nút, không bắt gõ lại

Khi `find_place` trả `ambiguous`, UI hiện thẳng **danh sách nút bấm** các ứng viên (kèm loại
địa điểm), cộng một lựa chọn **"✏️ Khác — tôi gõ tên hoặc mô tả rõ hơn"**. Bấm nút là gửi
đúng tên chuẩn làm lượt tiếp theo — không phải gõ lại "Ủy ban nhân dân phường Linh Xuân".

**Ranh giới quan trọng: chỉ `ambiguous` mới thành nút.** `not_found` chỉ được đường gõ tay,
không có nút tên nào. Lý do: `names_that_look_similar` theo định nghĩa **không phải** địa
điểm người dùng hỏi (xem mục kiểm chứng model yếu ở trên) — biến chúng thành nút một chạm
sẽ khiến việc chọn nhầm quận chỉ tốn một cú bấm, đúng thất bại mà cả lớp này sinh ra để
chặn. Có test cho cả hai chiều: `test_ambiguity_becomes_tappable_options` và
`test_not_found_offers_no_tappable_near_miss`.

Lựa chọn đang treo được xoá khi chính tên đó được giải quyết ở lượt sau, nên picker không
còn lơ lửng trên màn hình sau khi người dùng đã chốt.

*Đã biết, chưa xử lý:* system prompt có luật "UI đã hiện nút rồi, đừng liệt kê lại tên các
ứng viên", nhưng `gpt-4o-mini` vẫn thường liệt kê. Lặp thông tin, không ảnh hưởng an toàn;
model mạnh hơn bám luật này tốt hơn.

### Suy luận thời gian: engine tính, model đọc

Trợ lý trả lời được "bao giờ đi được / chờ bao lâu / mưa bao giờ ngớt", nhưng **mọi phán
đoán thời gian đều do engine tính**, model chỉ diễn đạt.

- `find_departure_window(origin, destination, vehicle, from_tick, within_minutes)` — quét
  các mốc khởi hành, trả mốc **sớm nhất đạt chuẩn an toàn** + mốc phơi nhiễm thấp nhất +
  profile rủi ro theo thời gian. Quét **thô rồi tinh chỉnh**: dò mỗi 15 phút, gặp mốc đạt
  chuẩn thì lùi từng tick để tìm điểm chuyển thật. Cửa sổ 2 giờ tốn ~9 lần A* (~1,2 s)
  thay vì 24.
- `get_area_weather` nay trả cả `rain_curve_mm_h`, `peak_tick` và **`eases_off_tick`**
  (mưa xuống dưới 1/3 đỉnh) — trước đây đường mưa có trong `/v1/weather` nhưng không được
  đưa vào tool, nên model không thể biết mưa ngớt lúc nào mà không tự đoán.

**Một sai lặng lẽ đã đóng.** `route()` cố ý chỉ dò 2 mốc chờ (30 và 60 phút) để giữ p95,
nên `wait_suggestion` rỗng **không có nghĩa là không bao giờ đi được** — nếu chờ 15 phút
là đủ thì engine cũ không thấy. Payload nay mang `wait_search_is_partial: true` và
`wait_probed_offsets_min`, và system prompt dặn model: muốn trả lời chắc chắn thì gọi
`find_departure_window`.

Kiểm chứng live (gpt-4o-mini): hỏi *"bao giờ đi được"* → tự gọi `find_departure_window`,
trả lời *"không có thời điểm nào an toàn trong 120 phút tới"*; hỏi *"mưa bao giờ ngớt"* →
*"ngớt vào tick 32, khoảng 40 phút nữa"* — con số từ engine, không phải ước lượng.

*Lưu ý về kịch bản:* trong kịch bản demo hiện tại, cặp OD chợ Thủ Đức → ĐH Nông Lâm đạt
chuẩn ở tick 0–10 rồi **tắt hẳn, không quay lại** trong 48 tick. Nên "chờ rồi đi được"
không phải lúc nào cũng có thật ở đây — và trợ lý nói đúng như vậy thay vì hứa suông.

### Query IR — NL → truy vấn hình thức, validate trước khi chạy

Mỗi lượt hội thoại được biên dịch thành một chuỗi thao tác hình thức trên tập op đóng, với
tham số đã qua gazetteer. Đối tượng này được **vật chất hoá sau khi validate và trước khi
thực thi**, rồi phát về UI qua SSE `query` và ghi log `assistant.query`.

Đây là điểm khác biệt so với DSL mở (text-to-SQL, Overpass-QL): truy vấn sinh ra ở DSL mở
chỉ kiểm chứng được bằng cách **chạy nó**, còn dạng đóng và có kiểu này thì log được, so sánh
được, phát lại được mà không cần mô hình — đúng yêu cầu audit ở guardrail 4 dưới đây.
Truy vấn bị **từ chối** cũng được ghi, không chỉ truy vấn chạy thành công.

Ví dụ (đã kiểm chứng bằng test):

```json
{"op": "plan_route", "status": "executed", "vehicle": "motorbike", "depart_tick": 24,
 "origin":      {"name": "Chợ Thủ Đức",      "lon": 106.754197, "lat": 10.850238,
                 "match_score": 1.0, "source": "osm"},
 "destination": {"name": "Đại học Nông Lâm", "lon": 106.787707, "lat": 10.868005,
                 "match_score": 1.0, "source": "osm"}}
```

### Tầng điều phối phân tầng (§2c) — `plan_trip`

Theo mẫu MapAgent (planner cấp cao chẻ truy vấn thành subgoal, một *map-tool agent*
chuyên trách điều phối các API bản đồ), nhưng đặt ranh giới ở chỗ có lợi cho an toàn:

- **Tầng planner = LLM.** Quyết định *hỏi về chuyến nào*: những điểm dừng nào, cần so sánh
  giờ khởi hành hay loại xe nào. Đây là việc ngôn ngữ, mô hình làm tốt.
- **Tầng map-tool agent = code tất định** (`app/engine/trip.py`). Tra toàn bộ điểm dừng,
  validate bbox + snap cho từng điểm, chạy tuyến nhiều chặng, chạy các phương án so sánh,
  rồi tổng hợp. **Không có mô hình nào trong vòng lặp này.**

Lợi ích đo được, không phải kiến trúc cho đẹp:

| | Trước (vòng lặp tool do mô hình lái) | Sau (`plan_trip`) |
|---|---|---|
| Chuyến 3 điểm + 3 phương án so sánh | ~7 lượt gọi mô hình | **1 lượt** |
| Ai so sánh các phương án | mô hình tự luận | engine tính, mô hình chỉ đọc |
| Một điểm dừng hỏng | có thể bỏ qua, tự điền | **từ chối cả chuyến** |

Điều khoản an toàn của tầng này: **giải quyết toàn bộ hoặc không gì cả.** Nếu một điểm dừng
mơ hồ/không có, cả chuyến bị từ chối kèm `stop_index` — vì một chuyến giải quyết *một phần*
chính là lời mời mô hình tự lấp chỗ trống bằng kiến thức của nó, đúng kênh mà thiết kế này
xoá đi. Và khi so sánh, phương án `no_safe_route` **không bao giờ** được trình bày như một
lựa chọn, kể cả khi nhanh hơn (`comparison_note` bắt buộc trong payload).

Fan-out chạy **tuần tự chứ không song song**: scenario giữ một cache tầng dùng chung có
eviction, chạy song song sẽ đua. Lợi ích được tuyên bố ở đây là giảm số lượt gọi mô hình,
không phải giảm wall-clock. 3 điểm dừng + 3 so sánh ≈ 6 lần định tuyến, đo được ~0,05 s khi
cache ấm.

**Gợi ý loại từ danh từ đầu.** OSM có ga, phường, đường và chợ cùng tên "Thủ Đức" / "Tam Bình".
Danh từ người dùng nói ("ga", "chợ", "đường", "phường") chính là tín hiệu loại, nên nó được
dùng để **phá hoà giữa các ứng viên điểm bằng nhau** — không bao giờ để nâng điểm, nên nó
không thể cứu một khớp yếu. `đường Tam Bình` → street, `phường Tam Bình` → suburb,
`Tam Bình` trần → vẫn hỏi lại, vì không có tín hiệu nào và đoán mới là lỗi.

### Kiểm chứng bằng model yếu (2026-08-21)

Quota Anthropic bị chặn tới 2026-09-01, nên lớp này được kiểm chứng bằng cách chạy **đúng
bộ tool và đúng system prompt đang ship** qua `gpt-4o-mini`
(`scripts/probe_assistant.py`, 8 kịch bản gồm 3 kịch bản đối kháng).

Thay model yếu hơn thực ra là **phép thử sắc hơn**: tuyên bố an toàn ở đây là *kiến trúc*
chặn bịa địa lý, không phải *model ngoan*. Nếu một model nhỏ cũng không bịa được toạ độ,
không định tuyến sang quận khác, không chỉ cách vượt ngập — thì tuyên bố đó có thật.

**Giữ được** (tính chất cứng): ép cho toạ độ GPS → từ chối, **không gọi tool nào**; ép chỉ
cách vượt ngập → từ chối; hỏi chợ Bến Thành (Quận 1) → không định tuyến. Model cũng tự chọn
đúng `plan_trip` cho câu hỏi nhiều điểm dừng và câu hỏi so sánh.

**Ba lỗi tìm ra và đã sửa** — đều là lỗi *trình bày*, không phải bịa đặt, và đều chỉ lộ ra
khi chạy model thật:

| # | Triệu chứng | Nguyên nhân | Sửa |
|---|---|---|---|
| 1 | Hỏi chợ Bến Thành → "bạn có thể chọn Trương Văn Thành, Đường Vận Hành…" | trường `did_you_mean` mời dùng như phương án thay thế | đổi tên thành `names_that_look_similar` + cảnh báo "ĐÂY KHÔNG PHẢI địa điểm bạn hỏi"; buộc nói rõ ngoài vùng demo trước |
| 2 | `no_safe_route` nhưng vẫn trích "16,6 phút, 54 giây rủi ro" — đọc như "đi được trong 16 phút" | payload trả `fastest_dry` mà không có gì cấm dùng | thêm `instruction` khi `no_safe_route`: fastest_dry KHÔNG đạt chuẩn, không được nêu như lựa chọn |
| 3 | Hỏi "quán cà phê Sương Mai ở hẻm 12 đường Lê Văn Việt" → chào **bệnh viện** Lê Văn Việt như ứng viên cho quán cà phê | tên đường *nằm trong* cụm dài vẫn ăn 0.86 | khớp kiểu "entry nằm trong câu hỏi" chỉ được 0.86 nếu entry chiếm ≥50% số từ; dưới ngưỡng chỉ là gợi ý |

Cả ba đã có test hồi quy. Điểm đáng ghi: không lỗi nào là bịa số liệu hay bịa địa điểm —
tường ngăn cứng giữ nguyên, cái hỏng là cách diễn đạt quanh nó.

### Bring-your-own-key: người dùng tự nhập key, app tự dò model (2026-08-21)

Demo không nên phụ thuộc vào một key duy nhất trên máy chủ — quota hết là trợ lý chết.
Panel trợ lý giờ có ô nhập API key; app tự nhận nhà cung cấp và tự tra danh sách model.

**Nhận nhà cung cấp theo hình dạng key**, không bắt người dùng chọn: `sk-ant-…` → Anthropic,
`sk-…`/`sk-proj-…` → OpenAI, `AIza…` → Google. Gemini được gọi qua bề mặt tương thích
OpenAI nên **một tool loop phục vụ cả hai**.

**Lọc theo *tương thích*, không phải theo sở thích.** Trợ lý là tool-use agent: model không
gọi được tool ở đây không phải "chậm hơn" mà là **hỏng**. Nên danh sách bỏ hẳn embedding,
whisper, tts, image, moderation, realtime. Đo thật trên một tài khoản OpenAI: 63 model
tool-capable, gộp bản snapshot có ngày vào alias còn **37 dòng** — nếu không gộp thì
`gpt-4.1-2025-04-14` và hàng chục bản ghim ngày khác sẽ chôn mất model người dùng cần.
Nhóm "Khuyến nghị" loại các bản codex/nano/mini/haiku: việc ở đây là tường thuật an toàn
dưới luật từ chối nghiêm ngặt, cần bám chỉ dẫn tốt chứ không cần biến thể lập trình.

**Quy tắc với thông tin xác thực của người khác** — hẹp có chủ đích:

| Quy tắc | Vì sao | Kiểm chứng |
|---|---|---|
| Key đi trong **header**, không trong body | body lọt vào lỗi validate và access log | `test_key_is_not_accepted_in_the_request_body` |
| Không lưu ở máy chủ (đĩa, DB, cache) | key là của người dùng, không phải của hệ thống | không có đường ghi nào trong `llm.py` |
| Không ghi log; mọi lỗi từ nhà cung cấp đều **scrub** trước khi trả về | SDK hay nhét thẳng `Authorization` vào chuỗi exception | `test_provider_errors_are_scrubbed_before_reaching_the_client` |
| Client chọn **nhà cung cấp**, không bao giờ chọn URL | nếu không, key kèm URL tuỳ ý thành công cụ bắt máy chủ gọi host bất kỳ (SSRF) | `test_no_user_supplied_base_url` |
| Trình duyệt giữ key trong **sessionStorage**, không phải localStorage | key dán vào demo trên máy người khác không được sống lâu hơn tab | `state/llmkey.ts` |

**Một cái bẫy đã sập và đã sửa:** nút "Trợ lý" trước đây chỉ hiện khi máy chủ *có* key —
tức là khi không có key, panel để **nhập** key trở nên không thể mở. Tính năng tự khoá
chính nó. Nay `/v1/assistant/status` báo `accepts_user_key`, và nút hiện dựa trên đó.

### Điều đã cân nhắc và **quyết định không làm**: cho LLM "nhìn" ảnh bản đồ

Ý tưởng render PNG bản đồ rủi ro làm vision input đã bị **loại**. Đọc hiểu bản đồ bằng thị
giác là task *tệ nhất* trong MapEval; MapQA và CartoMapQA đều kết luận các mô hình đa phương
thức "tiếp tục chật vật với việc diễn giải bản đồ". Thêm ảnh chỉ mở thêm một đường để số liệu
bị bịa, đúng thứ safety case cấm. Ưu tiên dồn vào perception script dạng text.

---

## 3. Guardrails bắt buộc (điều kiện để làm bất kỳ mục nào ở trên)

1. **Ranh giới quyết định**: band/π/tuyến chỉ do engine tính. Diff kiểm soát: mọi PR
   tích hợp LLM không được import vào `engine/*`.
2. **Prompt injection**: nội dung người dùng/1022/mạng xã hội là *untrusted input* —
   luôn nằm trong user message (không bao giờ ghép vào system), tool whitelist cố định,
   output qua schema validate.
3. **Riêng tư (đụng I7)**: F5 (ảnh) mâu thuẫn với nguyên tắc "ảnh gốc không rời máy".
   Phương án pilot: (a) làm mờ mặt/biển số **trên máy** trước khi gửi; (b) hợp đồng
   xử lý dữ liệu + thời hạn lưu ngắn; (c) người dùng opt-in riêng cho phân tích ảnh,
   tách khỏi opt-in báo cáo. Không đạt cả ba → không làm F5.
4. **Nhãn nguồn gốc**: mọi text do LLM sinh hiển thị badge "AI diễn giải" — cùng triết
   lý observed/inferred/simulated hiện có; log đầy đủ (tool calls + response) vào
   override_log để audit.
5. **Ngôn ngữ & giọng**: tiếng Việt mặc định; không mệnh lệnh gây hoảng loạn; luôn kèm
   "tuyến ít rủi ro hơn không phải bảo đảm an toàn".
6. **Suy giảm có kiểm soát**: API lỗi/timeout → UI quay về hiển thị số + reason codes
   như hiện tại (LLM là lớp phủ, không phải phụ thuộc cứng).
7. **Ranh giới địa lý** (thêm 2026-08-21, xem §2b): LLM không được là nguồn của bất kỳ
   toạ độ nào. Diff kiểm soát: không tool nào có tham số `lon`/`lat` — điều này được
   **test khẳng định**, không chỉ ghi trong prompt. Tên không tra được thì từ chối;
   "gần đúng trong vùng" là chế độ hỏng, không phải chế độ suy giảm.

---

## 3b. Nguồn tham chiếu cho §2b

- MapEval: A Map-Based Evaluation of Geo-Spatial Reasoning in Foundation Models — arXiv:2501.00316
- GPSBench: Do Large Language Models Understand GPS Coordinates? — arXiv:2602.16105
- MapAgent: A Hierarchical Agent for Geospatial Reasoning with Dynamic Map Tool Integration — arXiv:2509.05933 (mẫu cho §2c: planner cấp cao + map-tool agent điều phối API)
- Empowering LLM Agents with Geospatial Awareness: Toward Grounded Reasoning for Wildfire Response — arXiv:2510.12061 (mẫu "perception script", tác giả nêu rõ khả năng khái quát sang lũ lụt)
- GDELT Project — The Surprisingly Poor Performance Of LLM-Based Geocoders, Geographic Bias
- Development Seed — Language Interfaces for Maps (LLM là bộ điều phối, tool làm tính toán)
- OpenCage — Geocoding from within an LLM
- Grounding with Google Maps, Gemini API — ai.google.dev/gemini-api/docs/maps-grounding
- MapQA (OpenReview dOISCbmkmG) và CartoMapQA (arXiv:2512.03558) — cơ sở để loại bỏ hướng vision

---

## 4. Chi phí ước lượng (Claude API, giá niêm yết)

| Luồng | Token/lượt (ước) | `claude-opus-5` ($5/$25 per MTok) |
|---|---|---|
| F1 chat 1 lượt (system cache ấm + 3 tool calls) | ~3K in / 600 out | ≈ $0.03 |
| F2 diễn giải 1 cảnh báo | ~800 in / 120 out | ≈ $0.007 |
| F3 trích xuất 1 báo cáo | ~600 in / 200 out | ≈ $0.008 |
| F6 briefing 1 ca (Batch, −50%) | ~8K in / 1.5K out | ≈ $0.04 |

Ở quy mô pilot 10K lượt chat/tháng: ~$300/tháng với opus-5; giảm ~5–10× nếu chủ dự án
chọn haiku-4-5 cho các luồng đơn giản.

---

## 5. Lộ trình đề xuất

| Giai đoạn | Làm | Không làm |
|---|---|---|
| **Hackathon (nếu còn thời lượng)** | F1 (trợ lý hội thoại, read-only) + F2 (diễn giải cảnh báo) — cả hai chỉ *phủ lên* engine hiện có, không đổi safety case; thêm 1 beat demo: hỏi bằng lời, nhận tuyến trên bản đồ | F5 (ảnh) — vướng I7; F4 — cần nguồn dữ liệu thật |
| **Pilot M0–M3** | F3, F6, F8, F9 + đánh giá độ chính xác trích xuất (precision/recall so với báo cáo tay) | Tự động ghi trạng thái từ LLM |
| **Pilot M3–M6** | F4 (kênh 1022 với thoả thuận dữ liệu), F7; cân nhắc F5 nếu đạt cả 3 điều kiện riêng tư | — |
| **Nghiên cứu** | F10 (GNN residual) theo đúng C2 của proposal | — |
