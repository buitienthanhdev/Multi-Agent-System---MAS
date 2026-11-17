# Tài liệu Policy, Sổ Ngân sách (Budget Ledger), Phê duyệt (Approval) & Cấu hình Connector

## 1. Policy Engine (`atlas/policies/engine.py`)
- Các quy tắc mặc định (`DEFAULT_RULES`):
  - Mọi hành động thuộc nhóm `publish.sandbox`, `publish.live`, `ads.launch`, `message.send_customer`, `budget.spend` **luôn yêu cầu phê duyệt của con người** (`always_require_approval`).
  - Giới hạn chi phí tối đa cho một hành động đơn lẻ: `10.000.000 ₫` (`max_single_action_minor`).
  - Chặn các mẫu nội dung vi phạm chính sách thương hiệu/pháp lý: `"bảo hành trọn đời"`, `"cam kết 100%"`, `"rẻ nhất thị trường"`, `"chữa"`, `"tốt nhất thế giới"`.
  - Chỉ cho phép thực hiện hành động khi Mission đang ở trạng thái `active`. Khi Mission chuyển sang `paused` hoặc `cancelled`, mọi lệnh thực thi mới đều bị chặn ngay tại Gateway.
- **Bảo vệ chống ghi đè**: Output từ công cụ hoặc nội dung web bên ngoài được bọc trong thẻ `<untrusted_content>` và quét bằng `detect_injection()`. Agent không có bất kỳ tool hay quyền hạn nào để sửa bảng `policies`, `budget_accounts`, hoặc `roles`.

## 2. Cơ chế Phê duyệt — Approval (`atlas/actions/gateway.py`)
- Mỗi `Action` khi chuẩn bị sẽ tính `payload_hash = sha256(canonical_json({connector, action_type, payload}))`.
- Chỉ người dùng có vai trò `owner` hoặc `approver` trong đúng Workspace mới có quyền gọi `POST /api/actions/{id}/decide`.
- Bản ghi `Approval` lưu `payload_hash` tại thời điểm duyệt và thời gian hết hạn `expires_at` (mặc định 60 phút).
- **Tính bất biến**:
  - Nếu payload của Action bị chỉnh sửa sau khi đã duyệt (`update_payload`), `payload_hash` mới sẽ khác với `payload_hash` trong `Approval` -> Gateway từ chối thực thi và đưa Action về lại `awaiting_approval`.
  - Nếu quá thời hạn `expires_at` mới thực thi -> Gateway từ chối thực thi.

## 3. Sổ Ngân sách — Budget Ledger (`atlas/budgets/ledger.py`)
- **Đơn vị tiền tệ**: Chỉ dùng số nguyên `BigInteger` (`amount_minor`). Không dùng `float`.
- **Phân nhóm tài khoản (`BudgetAccount`)**:
  - `total`: Tổng ngân sách của Mission (ví dụ: `30.000.000 ₫`).
  - `ads`: Ngân sách quảng cáo.
  - `external_services`: Dịch vụ bên ngoài.
  - `model_tools`: Ngân sách cho LLM/công cụ (chi phí ước tính được ghi riêng vào `estimated_untracked_minor` với cờ `is_estimate=True`, không trộn lẫn với chi phí đã đối soát).
- **Vòng đời bút toán**:
  1. `reserve`: Giữ chỗ trước khi gọi dịch vụ bên ngoài bằng câu lệnh SQL `UPDATE ... WHERE limit - reserved - committed - settled >= amount` nguyên tử, kết hợp ràng buộc `CHECK` trong DB. Hai worker chạy song song không thể làm vượt hạn mức.
  2. `commit`: Chuyển từ `reserved` sang `committed` khi lệnh bên ngoài thành công.
  3. `release`: Giải phóng `reserved` nếu lệnh thất bại xác định.
  4. `settle`: Đối soát số tiền thực tế từ nhà cung cấp (`settled_minor`).
- **Giới hạn kiểm soát đối với dịch vụ có số liệu chi phí trễ (ví dụ Google Ads / Meta Ads)**:
  - Hệ thống nội bộ chỉ có thể chặn việc tạo chiến dịch mới hoặc nâng ngân sách vượt hạn mức. Nếu nhà cung cấp quảng cáo phát sinh chi phí vượt mức cam kết trước khi kịp đồng bộ báo cáo (delayed billing), khoản chênh lệch được ghi nhận vào cột `overrun_minor` khi đối soát và cảnh báo trong báo cáo. Do đó, khi kết nối quảng cáo thật, **bắt buộc** cài đặt thêm hạn mức chi tiêu trực tiếp trên tài khoản của nhà cung cấp (provider-side spend cap).

## 4. Hướng dẫn Cấu hình Connector (`atlas/integrations/connectors.py`)

| Connector | Trạng thái mặc định | Biến môi trường cần cấp | Quyền Mission cần cấp thêm |
|---|---|---|---|
| `sandbox_publisher` | `sandbox` (`mocked`) | Không cần (lưu trạng thái vào `var/sandbox_publisher.json`) | `publish.sandbox` (có sẵn mặc định) |
| `sales_csv` | `sandbox` (`mocked`) | Không cần (đọc dữ liệu mẫu có gắn nhãn `DEMO DATA`) | `analytics.read_fixture` (có sẵn) |
| `facebook_page` | `not_configured` | `FACEBOOK_PAGE_TOKEN` | `publish.live` (chỉ Owner mới cấp được) |
| `google_ads` | `not_configured` | `GOOGLE_ADS_CREDENTIALS` | `ads.launch`, `budget.spend` |
| `media_generator` | `not_configured` | `MEDIA_PROVIDER_API_KEY` | `media.generate` |
| `browser_worker` | `not_configured` | Cần chạy container Browser Use tách biệt | Tùy tác vụ |

> **Nguyên tắc**: Khi chưa cấu hình biến môi trường, hệ thống hiển thị rõ `not_configured` trên Dashboard và trả lỗi `NotConfigured` minh bạch; tuyệt đối không trả kết quả giả tạo để tuyên bố đã đăng bài hay tạo ảnh thành công.
