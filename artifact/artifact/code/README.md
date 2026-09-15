# Hướng Dẫn Chạy Local — artifact/artifact/code

Thư mục này chứa toàn bộ mã nguồn có thể chạy được của dự án **Đường An VN**.

## 1. Chạy Backend API (Cổng 8000)

```powershell
# Từ thư mục này (artifact/artifact/code):
.\.venv\Scripts\Activate.ps1
.\env.ps1
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --app-dir services\api
```

Kiểm tra: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) và [http://127.0.0.1:8000/healthz](http://127.0.0.1:8000/healthz).

## 2. Chạy Frontend Web (Cổng 5173)

Mở terminal mới:
```powershell
cd apps\web
npm run dev
```

Truy cập: [http://localhost:5173](http://localhost:5173).

Xem hướng dẫn chi tiết đầy đủ tại [README gốc ở thư mục ngoài](../../../README.md).
