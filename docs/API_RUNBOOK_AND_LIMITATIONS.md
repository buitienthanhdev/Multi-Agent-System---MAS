# API Contracts, Runbook Vận hành / Khôi phục & Giới hạn Hiện tại

## 1. API Contracts (`atlas/api.py`)

Mọi endpoint (trừ `/api/health` và `/api/files/{version_id}` dùng chữ ký HMAC) đều yêu cầu header:
`Authorization: Bearer <token>`

Trong môi trường local/demo, hệ thống tạo sẵn 3 token kiểm thử:
- `demo-owner-token` (`owner` tại workspace `OneCoat Demo`)
- `demo-viewer-token` (`viewer` chỉ đọc tại workspace `OneCoat Demo`)
- `demo-other-token` (`owner` tại workspace `Other Workspace` — dùng để kiểm chứng cô lập đa tenant)

### Danh mục Endpoint chính

| Method & Path | Mô tả | Request Body / Query | Response chính |
|---|---|---|---|
| `GET /api/health` | Trạng thái hệ thống, chế độ LLM, Temporal, Langfuse | — | `{status, llm_mode, temporal, langfuse}` |
| `GET /api/me` | Thông tin user hiện tại & danh sách workspaces/roles | — | `{id, email, workspaces:[{id,name,role}]}` |
| `POST /api/missions/compile` | Biên dịch thử yêu cầu tự nhiên thành `MissionContract` | `{request: str}` | `MissionContract` JSON |
| `POST /api/missions` | Tạo Mission mới (trạng thái `draft`, version 1) | `{workspace_id, request, is_demo}` | Mission detail + Contract + Versions |
| `GET /api/missions` | Danh sách Missions trong workspace | `?workspace_id=...` | `list[Mission]` |
| `GET /api/missions/{id}` | Chi tiết Mission, Contract hiện hành & lịch sử phiên bản | — | Mission detail |
| `PATCH /api/missions/{id}/contract` | Cập nhật Contract (có kiểm tra `lock_version` chống ghi đè) | `{changes, reason, lock_version}` | Mission detail (tăng `current_version`) |
| `POST /api/missions/{id}/{op}` | Chuyển trạng thái: `activate`, `pause`, `resume`, `cancel` | — | Mission detail (+ `cancel_result` khi cancel) |
| `GET /api/missions/{id}/plan` | Xem Plan, phương án đã cân nhắc, Tasks, Dependencies, Decisions | — | `{plan, tasks, dependencies, decisions}` |
| `GET /api/missions/{id}/runs` | Lịch sử các lần chạy Agent (`AgentRun`) | — | `list[AgentRun]` |
| `GET /api/missions/{id}/artifacts` | Danh sách Artifacts kèm `download_url` đã ký HMAC có thời hạn | — | `list[Artifact + versions]` |
| `GET /api/files/{version_id}` | Tải nội dung file qua Signed URL | `?exp=...&sig=...` | `text/plain` (403 nếu hết hạn/sai chữ ký) |
| `GET /api/missions/{id}/evidence` | Danh sách bằng chứng (`verified_fact`, `estimate`, `assumption`...) | — | `list[Evidence]` |
| `GET /api/missions/{id}/evaluations` | Kết quả kiểm duyệt độc lập (`Evaluation`) | — | `list[Evaluation]` |
| `GET /api/missions/{id}/actions` | Danh sách Actions, Approvals và ExternalReceipts | — | `list[Action]` |
| `POST /api/actions/{id}/decide` | Duyệt hoặc từ chối Action (ràng buộc đúng `payload_hash`) | `{decision, payload_hash, comment}` | `Action` |
| `GET /api/missions/{id}/budget` | Sổ ngân sách theo nhóm tài khoản và lịch sử bút toán | — | `{accounts, entries, note}` |
| `GET /api/missions/{id}/reports` | Danh sách báo cáo tổng hợp | — | `list[Report]` |
| `POST /api/missions/{id}/reports` | Tạo báo cáo tổng hợp ngay | — | `Report` |
| `GET /api/missions/{id}/audit` | Nhật ký kiểm toán (Audit Log) của Mission | — | `list[AuditEvent]` |
| `GET /api/connectors` | Danh sách Connectors và trạng thái cấu hình (ẩn giá trị secret) | `?workspace_id=...` | `list[Connector]` |
| `GET /api/capabilities` | Capability Registry, giới hạn đội agent và thống kê đánh giá | — | `{capabilities, limits, evaluation_stats}` |
| `POST /api/worker/step` | Chạy 1 vòng thực thi Worker cho các task đã sẵn sàng | `?mission_id=...` | `{outbox_dispatched, tasks_executed}` |
| `GET /api/benchmark` | Chạy thực nghiệm so sánh Multi-Agent vs Single-Agent | — | Kết quả đo chất lượng, số lần can thiệp, latency |
| `POST /api/demo/reset` | Reset toàn bộ dữ liệu demo về trạng thái sạch ban đầu | — | `{status: "reset"}` |

---

## 2. Runbook Vận hành, Dừng Khẩn cấp & Khôi phục

### 2.1. Dừng khẩn cấp một Mission hoặc toàn hệ thống
1. **Tạm dừng (Pause)**:
   - Trên Dashboard nhấn **Pause** hoặc gọi `POST /api/missions/{id}/pause`.
   - Hiệu lực tức thì: Worker không nhận thêm task mới của Mission đó; `Action Gateway` từ chối mọi lệnh `execute()` mới với lỗi `PolicyDenied`.
2. **Hủy bỏ (Cancel)**:
   - Nhấn **Cancel Mission** hoặc gọi `POST /api/missions/{id}/cancel`.
   - Mọi task đang `planned`, `blocked`, `waiting_approval` chuyển sang `cancelled`.
   - Mọi Action chưa thực thi chuyển sang `cancelled`.
   - Với các Action đã `succeeded` ở bên ngoài (ví dụ bài đã đăng trên sandbox), hệ thống tự động gọi **Compensating Action** (`connector.request_stop(external_ref)`) và trả về trạng thái xác minh (`verified` hoặc `unconfirmed`). Hệ thống **không** gọi đây là rollback vì nội dung đã từng xuất hiện bên ngoài.
   - Với các Action đang `executing` hoặc `unknown`, kết quả dừng trả về `unconfirmed_outcome_unknown` để người vận hành kiểm tra thủ công.

### 2.2. Xử lý khi Worker bị dừng đột ngột (Crash Recovery)
- Mỗi task khi được worker nhận sẽ có `lease_owner` và `lease_until` (mặc định 30 giây).
- Nếu worker chết giữa chừng:
  - Khi hết hạn `lease_until`, worker mới sẽ tự động nhận lại task đó và chạy tiếp mà không làm mất các task đã `completed` trước đó.
  - Nếu worker chết ngay sau khi gửi lệnh ra connector bên ngoài nhưng trước khi kịp ghi `succeeded` vào DB (action đang ở trạng thái `executing` hoặc `unknown`), lần chạy kế tiếp của `gateway.execute()` sẽ gọi `reconcile()` để tra cứu trạng thái từ phía connector bằng `idempotency_key` trước, nhờ đó **không gửi trùng lệnh lần 2**.
- Các task vượt quá `max_attempts` (3 lần) hoặc vi phạm giới hạn tài nguyên sẽ chuyển sang `status="failed"` và ghi sự kiện `task.dead_letter` vào Audit Log để xử lý thủ công.

### 2.3. Sao lưu và Khôi phục (Backup & Restore)
- **Môi trường Local (SQLite + Local Object Store)**:
  ```powershell
  cd "C:\Users\TIEN THANH\Desktop\ATLAS AI\backend"
  # Sao lưu an toàn (dùng SQLite Online Backup API + đóng gói objects & sandbox state)
  uv run python -c "from pathlib import Path; from atlas.ops import backup_state; print(backup_state(Path('var/backup.tar.gz')))"

  # Khôi phục từ bản sao lưu
  uv run python -c "from pathlib import Path; from atlas.ops import restore_state; restore_state(Path('var/backup.tar.gz'))"
  ```
- **Môi trường Docker / PostgreSQL**:
  ```powershell
  docker compose exec -T postgres pg_dump -U atlas -Fc atlas > atlas_pg.dump
  docker compose exec -T postgres pg_restore -U atlas -d atlas --clean atlas_pg.dump
  ```

---

## 3. Giới hạn Hiện tại (Known Limitations)
1. **Không có Docker daemon trên máy hiện tại**: File `docker-compose.yml` đã được cung cấp đầy đủ cho PostgreSQL 16 (`pgvector`), MinIO và Temporal, nhưng trên máy Windows hiện tại chưa cài Docker nên hệ thống mặc định chạy với SQLite (WAL mode) + Local Object Store + DB-leased Worker.
2. **Chưa có API key của LLM và các kênh quảng cáo/mạng xã hội thật**:
   - Mặc định `ATLAS_LLM_MODEL=template` sử dụng bộ sinh văn bản tất định (không gọi mạng) và gắn nhãn rõ trong `AgentRun.limitations`. Khi cấp `ATLAS_LLM_MODEL=openai:gpt-4.1-mini` và `OPENAI_API_KEY`, adapter `DeepAgentsProvider` sẽ chạy qua `deepagents`.
   - Các connector `facebook_page`, `google_ads`, `media_generator`, `browser_worker` đang ở trạng thái `not_configured`.
   - Kênh gửi báo cáo tự động qua email/chat ngoài dashboard chưa cấu hình nên mọi báo cáo được lưu trên Dashboard với trạng thái `not_sent_channel_not_configured`.
3. **Kiểm tra Prompt Injection**: Bộ lọc `detect_injection()` và thẻ `<untrusted_content>` cùng việc tách quyền cứng ở `ToolBox`/`Action Gateway` đã chặn các mẫu tấn công đã kiểm thử (`test_08`), nhưng không tuyên bố loại bỏ 100% rủi ro ngữ nghĩa nếu dùng LLM thật trên dữ liệu mở.
