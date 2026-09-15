# Three-minute judging script (keystroke level)

Precondition: `make demo` done; browser at http://localhost:4173/?t=0 ; warm-up done
(~2 min after boot). Vehicle = Xe máy. Backup: screen recording in docs/media/.

| Clock | Action | Say |
|---|---|---|
| 0:00–0:25 | Press ▶ on the time slider; let it run to ~T+1h50 (or open `?t=22`) | "Đây không phải bản đồ ngập — đây là lớp quyết định. Mỗi cạnh đường có phân phối độ sâu và xác suất đi qua được, cập nhật 5 phút một." |
| 0:25–1:05 | Click a red edge in a sink cluster → inspector | "Dải tin cậy, tuổi bằng chứng, nguồn dữ liệu, lý do — và mọi thứ gắn nhãn MÔ PHỎNG. Không bao giờ hiển thị 'không chắc chắn' như 'an toàn'." |
| 1:05–1:40 | Nút "Tìm đường an toàn": chọn điểm hai bên cụm ngập → hai tuyến hiện ra | "Tuyến khô nhanh nhất (xám, đứt) so với tuyến khuyến nghị. Thêm X phút, tránh Y giây phơi nhiễm. Đổi sang Ô tô — tuyến thay đổi vì ngưỡng xe khác nhau." |
| 1:40–2:10 | Inspector → "Báo cáo tại đây" → chọn "Đến gác chân xe" → gửi (kèm ảnh nếu muốn) | "Báo cáo an toàn, không ai phải đo nước. Ảnh gốc không rời máy — chỉ thumbnail mờ 64×64. Posterior khu vực hẹp lại ngay." |
| 2:10–2:35 | "Vận hành": tắt gauge-0 (mất cảm biến) → map thận trọng hơn; đóng 1 đường → π=0 tức thì | "Mất cảm biến chỉ làm tăng thận trọng. Lệnh đóng đường chính thức thắng mô hình ngay lập tức." |
| 2:35–3:00 | Ops → tab metrics; tab model card | "Đánh giá replay với CI và cỡ mẫu — kể cả các cặp OD mà tuyến an toàn thua về thời gian. Model card nói rõ giới hạn. Đây là giao kèo dữ liệu cho pilot 6 tháng." |

**Beat tuỳ chọn — hỏi bằng tiếng Việt** (nếu API quota còn). Hai câu, theo đúng thứ tự này:

1. *"Bây giờ đi xe máy từ chợ Thủ Đức đến đại học Nông Lâm có ổn không?"* — trợ lý tra
   gazetteer, tính tuyến, vẽ lên bản đồ, trả lời tiếng Việt với badge "AI diễn giải".
   Chỉ vào dòng **"Truy vấn bản đồ đã hiểu"**: `tuyến: Chợ Thủ Đức → Đại học Nông Lâm ·
   tick 24 · motorbike`. Nói: *"Đây là truy vấn hình thức mà câu nói được biên dịch ra.
   Toạ độ tra từ OpenStreetMap, không phải AI đoán."*
2. *"Thế còn chợ Bến Thành?"* — **trợ lý phải từ chối.** Bến Thành ở Quận 1, ngoài vùng
   demo. Nói: *"Đây mới là phần quan trọng. Không có lớp neo này, tên đó khớp gần đúng
   vào 'Trương Văn Thành' ngay tại Thủ Đức và hệ thống sẽ trả về một tuyến hoàn toàn tự
   tin tới nhầm chỗ. Nghiên cứu đo được cấp thành phố từ toạ độ dưới 25% với mọi mô hình,
   và tệ hơn nữa ở Đông Á. Nên chúng tôi bỏ hẳn khả năng sinh toạ độ khỏi mô hình chứ
   không chỉ dặn nó đừng làm."*

**Nếu không có key trên máy chủ** (hoặc hết quota): mở panel trợ lý, dán API key của chính
bạn vào ô 🔑 — app tự nhận nhà cung cấp (Anthropic / OpenAI / Google) và tự tra danh sách
model gọi được tool, rồi chọn model trong dropdown. Key chỉ nằm trong tab đó, máy chủ không
lưu và không ghi log. Đây cũng là một beat demo tốt: *"không khoá cứng vào một nhà cung cấp,
và giám khảo có thể chạy bằng key của chính mình."*

Hết quota → UI báo lịch sự, bản đồ và số liệu chạy đầy đủ. Lưu ý: gazetteer, snap có ngưỡng và tên đường vẫn hoạt động khi trợ
lý tắt — chúng là cải tiến engine, không phụ thuộc LLM.

Failure drills rehearsed: kill Redis (`docker compose stop redis`) → app still serves;
model error → deterministic fallback; venue Wi-Fi down → everything is local.
