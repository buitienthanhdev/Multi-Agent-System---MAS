# Kiến trúc hệ thống ATLAS & Architecture Decision Records (ADRs)

## 1. Tổng quan Kiến trúc (Modular Monolith + Isolated Workers)

ATLAS được thiết kế theo mô hình **Modular Monolith** cho lõi nghiệp vụ, kết hợp với các worker tách biệt cho thực thi tác vụ dài ngày:

```
+-------------------------------------------------------------------+
|                   Next.js 16 + TypeScript Dashboard               |
|  (Mission, Plan/DAG, Runs, Artifacts/Evidence, Approvals, Budget) |
+---------------------------------+---------------------------------+
                                  | REST JSON (Bearer Auth, RBAC)
+---------------------------------v---------------------------------+
|                    FastAPI Business Core (Python 3.12)            |
|  - missions/compiler.py   : NL -> MissionContract (Pydantic)      |
|  - missions/service.py    : State Machine, Versioning, Outbox     |
|  - planning/planner.py    : <=3 Options Tradeoff + DAG Tasks      |
|  - capabilities/registry  : Capability specs, limits, eval stats  |
|  - actions/gateway.py     : Authz -> Policy -> Approval -> Budget |
|                             -> Idempotent Execute -> Reconcile    |
|  - budgets/ledger.py      : Atomic minor-unit reservation/settle  |
|  - evaluations/evaluator  : Deterministic Independent Reviewer    |
|  - reporting/reports.py   : Verified vs Estimate separation       |
|  - improvement.py         : Candidate -> Sandbox -> Held-out      |
+--------+------------------------+------------------------+--------+
         |                        |                        |
         v                        v                        v
+----------------+      +-------------------+     +-----------------+
| PostgreSQL 16  |      | Temporal / Local  |     | Object Storage  |
| (hoặc SQLite   |      | Durable Worker    |     | (Local / MinIO) |
|  khi không có  |      | + Deep Agents /   |     | + Signed URLs   |
|  Docker)       |      |   LangGraph Adapt |     +-----------------+
+----------------+      +-------------------+
```

### Quyền sở hữu trạng thái (State Ownership)
- **PostgreSQL (hoặc SQLite local)**: Nguồn chuẩn duy nhất (Single Source of Truth) cho Mission, MissionVersion, Plan, Task, BudgetAccount, BudgetEntry, Action, Approval, ExternalReceipt, Evidence, Artifact metadata, Evaluation, Report và AuditEvent.
- **Temporal**: Giữ lịch sử thực thi workflow dài ngày, timers, signals (`nudge`, `stop`) và retry của Activity.
- **Deep Agents / LangGraph**: Chỉ giữ trạng thái suy luận cục bộ trong phạm vi một lần chạy task thông qua adapter `atlas/llm.py`. Không sở hữu ngân sách, quyền hạn hay trạng thái Mission.
- **Langfuse**: Chỉ giữ telemetry/traces đã redact dữ liệu nhạy cảm (`atlas/telemetry.py`). Lỗi telemetry được bắt hoàn toàn để không bao giờ làm hỏng giao dịch nghiệp vụ.

---

## 2. Ma trận Dependency & Đánh giá Thư viện Nền tảng

| Thành phần | Thư viện / Phiên bản đã cài | License | Vai trò trong ATLAS | Giới hạn & Cách nâng cấp |
|---|---|---|---|---|
| Agent Harness | `deepagents==0.7.38` | MIT | Harness cho agent phức tạp, bọc qua `DeepAgentsProvider` trong `atlas/llm.py`. | Phụ thuộc model có hỗ trợ tool-calling; được cách ly qua interface `LLMProvider`. |
| Agent State Graph | `langgraph==1.2.22` | MIT | Runtime bên dưới Deep Agents. | Không dựng tầng orchestration trùng lặp bên trên LangGraph ngoài `engine.py`. |
| Durable Workflows | `temporalio==1.36.1` | MIT | Workflow dài ngày (`MissionWorkflow` trong `temporal_workflows.py`). | Khi máy local không có Docker/Temporal server, `worker.py` dùng DB-leased engine tương đương. |
| Observability | `langfuse==5.2.0` | MIT (SDK) | Tracing qua `atlas/telemetry.py` kèm `redact_obj`. | Self-hosted hoặc Cloud có phí nếu vượt free tier; tắt mặc định khi chưa cấu hình key. |
| Web / API | `fastapi==0.163.1`, `pydantic==2.14.3` | MIT | REST API và kiểm tra hợp đồng dữ liệu. | Nâng cấp minor qua `uv lock --upgrade-package`. |
| Persistence & Migrations | `sqlalchemy==2.1.8`, `alembic==1.20.1`, `psycopg[binary]==3.3.9` | MIT / LGPL-3.0 | ORM, atomic conditional UPDATE cho ngân sách và schema migrations. | Hỗ trợ song song PostgreSQL và SQLite (WAL mode). |
| Browser Automation | `browser-use` (Adapter `not_configured`) | MIT | Dự kiến cho browser worker cô lập. | Chưa bật local vì cần container sandbox riêng, tránh lộ session/secrets. |
| Coding Agent | `openhands` SDK (Adapter `not_configured`) | MIT | Dự kiến cho capability `software_engineering`. | Chỉ tạo patch đề xuất trong sandbox; không tự merge. |
| CrewAI / MS Agent Framework | Đã khảo sát, không ghép | MIT | Tham khảo mô hình role/team. | Xem ADR-003. |

---

## 3. Architecture Decision Records (ADRs)

### ADR-001: Đồng bộ Database và Workflow qua Transactional Outbox + DB Lease
- **Bối cảnh**: Ghi database và gọi Temporal `start_workflow` không phải là một giao tác nguyên tử. Ngoài ra, máy dev/test có thể không cài Docker.
- **Quyết định**: Mọi thay đổi trạng thái kích hoạt hoặc đánh thức workflow đều ghi bản ghi `OutboxEvent` trong cùng transaction DB. Worker (`atlas/worker.py`) đọc outbox với cơ chế retry + backoff + dead-letter (`status="dead"` sau 10 lần lỗi). Ở chế độ local không có Temporal server, worker thực thi trực tiếp các task khả dụng thông qua cơ chế **DB Lease có thời hạn (`lease_owner`, `lease_until`)**.
- **Hệ quả**: Đảm bảo tính bền vững (durability) và khả năng phục hồi khi worker chết giữa chừng ở cả chế độ Temporal lẫn chế độ local.

### ADR-002: Một nơi duy nhất chịu trách nhiệm Retry và Idempotency cho Hành động Bên ngoài
- **Bối cảnh**: Nếu cả Temporal, LangGraph và Connector cùng retry khi gặp lỗi mạng, hành động bên ngoài (đăng bài, chi tiền) có nguy cơ bị nhân đôi.
- **Quyết định**: `atlas/actions/gateway.py` là chủ sở hữu duy nhất của việc thực thi bên ngoài:
  1. Lưu trạng thái `executing` xuống DB **trước** khi gọi connector.
  2. Gửi `idempotency_key` cố định theo `(mission_id, task_id, action_type, payload_hash)`.
  3. Khi gặp timeout (`ConnectorTimeout`) hoặc khi khôi phục một action đang ở trạng thái `executing`/`unknown` sau crash, Gateway **bắt buộc gọi `reconcile()`** (`connector.lookup(idempotency_key)`) trước khi quyết định có gửi lại hay không.
- **Hệ quả**: Không bao giờ gửi trùng khi connector hỗ trợ idempotency/lookup (đã kiểm chứng bằng `test_02`, `test_03`, `test_04`).

### ADR-003: Không ghép CrewAI hoặc Microsoft Agent Framework vào runtime chính
- **Bối cảnh**: Đề bài yêu cầu đánh giá CrewAI và Microsoft Agent Framework nhưng cảnh báo không ghép nhiều framework điều phối chỉ vì chúng có sẵn.
- **Quyết định**: Backend viết bằng Python nên không dùng Microsoft Agent Framework (.NET-first). Không ghép CrewAI vì `DeepAgents`/`LangGraph` + `Capability Registry` của ATLAS đã đảm nhiệm việc chọn đội và kiểm soát giới hạn (`TEAM_LIMITS`).
- **Hệ quả**: Giảm độ phức tạp dependency và bề mặt lỗi.
