# Báo cáo Thực thi Kiểm thử & Nghiệm thu Thực tế (Test & Live Qualification Report)

## 1. Lệnh thực thi toàn bộ 21 bài kiểm thử
```powershell
cd "C:\Users\TIEN THANH\Desktop\ATLAS AI\backend"
uv run pytest -v
```

## 2. Kết quả thực thi thực tế
- Môi trường: `win32 — Python 3.12.13, pytest-9.2.0` + `Ollama 0.40.5 (gemma4:12b)`
- Tổng số bài kiểm thử: **21 passed in 45.85s (0 failed, 0 warnings)**

| STT | Mã bài kiểm thử | Nội dung kiểm chứng | Kết quả |
|---|---|---|---|
| 1 | `test_01_concurrent_budget_reservations_do_not_exceed_limit` | 2 worker giữ chỗ ngân sách song song (20tr + 20tr trên hạn mức 30tr) không vượt hạn mức; idempotent retry không nhân đôi. | `PASSED` |
| 2 | `test_02_retry_idempotency_no_duplicate_external_action` | Retry `gateway.execute()` không tạo 2 external actions (`send_count == 1`). | `PASSED` |
| 3 | `test_03_timeout_triggers_reconciliation` | Timeout sau khi gửi lệnh chuyển sang `unknown` và tự động `reconcile()` từ trạng thái bên ngoài. | `PASSED` |
| 4 | `test_04_crash_after_external_send_recovered_without_duplicate` | Tiến trình con crash (`os._exit(17)`) ngay sau khi gửi lệnh bên ngoài được khôi phục đúng mà không gửi lần 2. | `PASSED` |
| 5 | `test_05_expired_approval_and_payload_mutation_rejected` | Approval sai `payload_hash`, hết hạn (`expires_at`), hoặc sửa payload sau khi duyệt đều bị từ chối. | `PASSED` |
| 6 | `test_06_workspace_isolation_via_api` | Cô lập dữ liệu đa Workspace (`404`) và phân quyền `viewer` (`403` khi ghi) vs `owner`. | `PASSED` |
| 7 | `test_07_agent_cannot_call_unpermitted_tool` | Chặn Agent gọi tool ngoài danh sách cho phép (`ToolPermissionDenied`). | `PASSED` |
| 8 | `test_08_prompt_injection_in_external_source_is_contained` | Cô lập chỉ thị độc hại trong nguồn ngoài, không mở quyền, không lộ secret, không tự duyệt action. | `PASSED` |
| 9 | `test_09_worker_crash_and_resume_preserves_progress` | Worker chết giữa chừng được worker khác tiếp quản sau khi hết hạn lease mà không mất tiến độ đã lưu. | `PASSED` |
| 10 | `test_10_pause_and_cancel_block_actions` | Pause/Cancel chặn hành động mới và gửi yêu cầu dừng (`request_stop`) cho bài đã đăng. | `PASSED` |
| 11 | `test_11_agent_resource_limits_enforced` | Dừng có kiểm soát khi vượt `max_tool_calls` hoặc `max_tokens` (`LimitExceeded`). | `PASSED` |
| 12 | `test_12_provider_error_retry_and_fallback` | Xử lý lỗi model provider bằng retry và fallback an toàn có gắn nhãn giới hạn. | `PASSED` |
| 13 | `test_13_report_separates_verified_from_estimates` | Báo cáo tách bạch hoàn toàn `verified_results` và `estimates_not_verified`. | `PASSED` |
| 14 | `test_14_vertical_slice_e2e_and_revision_and_improvement` | Luồng E2E 12 bước + vòng lặp Reviewer yêu cầu sửa bài + Controlled Improvement Pipeline. | `PASSED` |
| 15 | `test_15_backup_and_restore_roundtrip` | Sao lưu (`backup_state`) và khôi phục (`restore_state`) toàn bộ DB + Object Store. | `PASSED` |
| 16 | `test_16_multi_agent_vs_single_agent_benchmark` | Benchmark trên 10 kịch bản (2 sạch, 8 gài bẫy thông số/bảo hành/injection): Single-Agent lọt 80% lỗi, Multi-Agent lọt 0% lỗi. | `PASSED` |
| 17 | `test_17_all_six_additional_domain_task_types_run_e2e` | Chạy E2E cả 6 loại nhiệm vụ mở rộng (`market_research`, `content_media`, `customer_care`, `software`, `data_analysis`, `docs_ops`). | `PASSED` |
| 18 | `test_18_public_http_readonly_connector_allowlist_and_live_fetch` | Connector `public_http_readonly` chặn SSRF và truy xuất tỷ giá VND trực tiếp qua HTTPS. | `PASSED` |
| 19 | `test_19_statistical_did_parallel_trends_and_closed_loop_optimization` | Kiểm định thống kê Parallel Trends ($p \ge 0.05$), Difference-in-Differences (95% CI, $t$-stat, $p < 0.05$), Funnel KPIs và Closed-Loop Optimization. | `PASSED` |
| 20 | `test_20_live_webhook_publisher_idempotency_and_withdrawal` | Connector `live_webhook_publisher` gửi HTTPS POST thật tới `https://httpbin.org/post` kèm header `X-Atlas-Idempotency-Key` + sinh microsite HTML + rút bài (`withdrawn_live`). | `PASSED` |
| 21 | `test_21_special_live_acceptance_pilot_no_demo_no_template_no_sandbox` | **Bài nghiệm thu đặc biệt**: `is_demo=False`, LLM thật `deepagents(ollama:gemma4:12b)`, nguồn HTTPS thực, `live_webhook_publisher` thực, đối soát ngân sách 3.500.000 ₫ và đóng vòng tối ưu chiến lược. | `PASSED` |
