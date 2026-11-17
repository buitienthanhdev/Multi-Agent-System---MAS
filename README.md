# Multi-Agent-System (MAS) — Nền tảng Điều hành Công việc bằng AI Đa Tác Nhân

Thư mục dự án: `C:\Users\TIEN THANH\Desktop\ATLAS AI`  
GitHub Repository: [Multi-Agent-System (MAS)](https://github.com/buitienthanhdev/Multi-Agent-System-MAS)

## 1. Cấu trúc Monorepo

- `backend/` — FastAPI + SQLAlchemy 2 + Alembic + Pydantic + Temporal workflows + Deep Agents/LangGraph adapter + Pytest suite.
- `frontend/` — Next.js 16 + TypeScript Dashboard kết nối trực tiếp tới Backend thật.
- `docs/` — Kiến trúc, ADRs, API Contracts, tài liệu Policy/Budget/Approval/Connectors, Runbook và Báo cáo Kiểm thử.
- `docker-compose.yml` — Cấu hình PostgreSQL (`pgvector`), MinIO (S3-compatible) và Temporal cho môi trường container.
- `.env.example` — Mẫu cấu hình biến môi trường (không chứa secret).

## 2. Các lệnh Setup, Start, Test và Reset Demo (PowerShell trên Windows)

### 2.1. Chạy toàn bộ bộ kiểm thử tự động (16 bài kiểm thử nghiệm thu)
```powershell
cd "C:\Users\TIEN THANH\Desktop\ATLAS AI\backend"
uv run pytest -v
```

### 2.2. Chạy Database Migrations (Alembic)
```powershell
cd "C:\Users\TIEN THANH\Desktop\ATLAS AI\backend"
uv run alembic upgrade head
```

### 2.3. Khởi động Backend API (cổng 8000)
```powershell
cd "C:\Users\TIEN THANH\Desktop\ATLAS AI\backend"
uv run uvicorn atlas.api:app --host 127.0.0.1 --port 8000
```

### 2.4. Khởi động Worker nền (tùy chọn — hoặc bấm nút "▶ Chạy Worker" ngay trên Dashboard)
```powershell
cd "C:\Users\TIEN THANH\Desktop\ATLAS AI\backend"
uv run python -m atlas.worker
```

### 2.5. Khởi động Frontend Dashboard (cổng 3000)
```powershell
cd "C:\Users\TIEN THANH\Desktop\ATLAS AI\frontend"
npm run dev
```
Sau đó mở trình duyệt tại: `http://localhost:3000`

### 2.6. Reset dữ liệu Demo về trạng thái sạch ban đầu
```powershell
cd "C:\Users\TIEN THANH\Desktop\ATLAS AI\backend"
uv run python -c "from atlas.ops import reset_demo; print(reset_demo())"
```
(Hoặc nhấn nút **Reset Demo DB** ở góc phải trên cùng của Dashboard).
