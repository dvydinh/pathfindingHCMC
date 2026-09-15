# Đường An VN — Hướng Dẫn Cài Đặt & Chạy Local

Hệ thống bản đồ dự báo ngập lụt theo thời gian thực và định tuyến an toàn theo phương tiện di chuyển (thử nghiệm tại khu vực TP. Thủ Đức, TP. Hồ Chí Minh).

---

## 1. Cấu Trúc Thư Mục Dự Án

Hiện tại toàn bộ mã nguồn có thể chạy được nằm trong thư mục:
```text
D:\Hackathon\Tasco\
├── artifact/
│   └── artifact/
│       └── code/                 <-- Thư mục mã nguồn chính của dự án
│           ├── apps/web/         <-- Frontend React + Vite + MapLibre GL
│           ├── services/api/     <-- Backend FastAPI + Router + Engine
│           ├── data/             <-- Dữ liệu bản đồ OSM, DEM và kịch bản ngập lụt
│           ├── config/           <-- Cấu hình BBox, xe, kịch bản
│           ├── .venv/            <-- Môi trường ảo Python (nếu đã có sẵn)
│           ├── env.ps1           <-- Script nạp biến môi trường cho PowerShell
│           └── Makefile
├── .gitignore
└── README.md
```

---

## 2. Yêu Cầu Môi Trường

- **Python**: `3.10` đến `3.12` (Khuyến nghị 3.10 hoặc 3.12 để tương thích `pyarrow`, `rasterio`, `numpy`).
- **Node.js**: Phiên bản `18+` (hoặc `20+`, `22+`) & `npm`.
- **Hệ điều hành**: Windows (PowerShell) hoặc Linux/macOS.

---

## 3. Hướng Dẫn Chạy Local Nhanh (Quick Start)

Dự án gồm 2 phần độc lập: **Backend API (FastAPI)** chạy trên cổng `8000` và **Frontend (React/Vite)** chạy trên cổng `5173`. Bạn cần mở **2 cửa sổ Terminal**.

### **Tab 1: Chạy Backend API (Cổng 8000)**

#### Trên Windows (PowerShell):
```powershell
# 1. Di chuyển vào thư mục mã nguồn
cd D:\Hackathon\Tasco\artifact\artifact\code

# 2. Kích hoạt môi trường ảo Python
# (Nếu máy đã có sẵn thư mục .venv bên trong code/):
.\.venv\Scripts\Activate.ps1

# (Nếu chưa có .venv, xem mục 4 bên dưới để tạo mới và cài thư viện)

# 3. Nạp biến môi trường cần thiết
.\env.ps1

# 4. Khởi chạy Backend FastAPI
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --app-dir services\api
```

#### Trên Linux / macOS (Bash):
```bash
cd artifact/artifact/code

# Kích hoạt venv
source .venv/bin/activate

# Nạp biến môi trường
export PYTHONUTF8=1
export DATA_DIR="$(pwd)/data"
export CONFIG_DIR="$(pwd)/config"
export PYTHONPATH="$(pwd)/services/api"

# Chạy Backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --app-dir services/api
```

---

### **Tab 2: Chạy Frontend Map Client (Cổng 5173)**

Mở thêm một cửa sổ Terminal thứ 2:

```bash
# 1. Di chuyển vào thư mục web
cd D:\Hackathon\Tasco\artifact\artifact\code\apps\web

# 2. Cài đặt packages (nếu chưa cài node_modules)
npm install

# 3. Khởi động Vite dev server
npm run dev
```

---

## 4. Hướng Dẫn Cài Đặt Từ Đầu (Dành Cho Người Mới Clone)

Nếu clone repo về máy mới và chưa có sẵn `.venv` hay `node_modules`:

### Bước 4.1: Cài đặt Backend (Python)
Mở PowerShell tại thư mục `artifact/artifact/code`:
```powershell
cd D:\Hackathon\Tasco\artifact\artifact\code

# Tạo môi trường ảo
python -m venv .venv

# Kích hoạt môi trường ảo
.\.venv\Scripts\Activate.ps1

# Cài đặt thư viện phụ thuộc
pip install -r ..\requirements.txt
```

### Bước 4.2: Tạo dữ liệu kịch bản mô phỏng bão / ngập (Nếu thiếu file trong `data/scenarios/`)
```powershell
# Đảm bảo đã nạp env.ps1
.\env.ps1

# Chạy mô phỏng tạo kịch bản Thủ Đức
python -m app.sim.storm
```

### Bước 4.3: Cài đặt Frontend (Node.js)
```powershell
cd D:\Hackathon\Tasco\artifact\artifact\code\apps\web
npm install
```

---

## 5. Kiểm Tra Kết Quả

Sau khi cả 2 server đã chạy:
- **Giao diện Bản đồ (Web App)**: [http://localhost:5173](http://localhost:5173)
- **Tài liệu API (Swagger UI)**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **Kiểm tra trạng thái API**: [http://localhost:8000/healthz](http://localhost:8000/healthz)

---

## 6. Chạy Bộ Kiểm Thử (Tests & Claims)

Để xác minh toàn bộ 113+ bài test định tuyến, logic ngập lụt và mô hình:
```powershell
cd D:\Hackathon\Tasco\artifact\artifact\code
.\.venv\Scripts\Activate.ps1
.\env.ps1

python -m pytest services\api\tests -q
```

---

## 7. Lưu Ý Khi Push Lên GitHub

> [!WARNING]
> Trong thư mục `data/scenarios/` có các file mô phỏng tensor `.npy`, `.npz` dung lượng > **140 MB**, vượt giới hạn **100 MB** của GitHub. 
> File `.gitignore` ở thư mục gốc đã được cấu hình tự động bỏ qua các file nặng này và các thư mục `.venv/`, `node_modules/`.

Các bước push code lên GitHub:
```powershell
cd D:\Hackathon\Tasco

# 1. Khởi tạo Git (nếu chưa có)
git init

# 2. Thêm file và commit
git add .
git commit -m "feat: setup project runnable structure and documentation"

# 3. Đổi nhánh chính sang main
git branch -M main

# 4. Thêm remote repository GitHub của bạn
git remote add origin https://github.com/<tai-khoan-cua-ban>/<ten-repo>.git

# 5. Push lên GitHub
git push -u origin main
```
