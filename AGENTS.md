# AGENTS.md — Quy ước phát triển cho ATLAS

1. **Ngôn ngữ**: Tài liệu và giao diện người dùng viết bằng tiếng Việt. Code, tên hàm/biến, cột database và API contracts viết bằng tiếng Anh.
2. **An toàn thực thi**:
   - Mọi hành động ra ngoài hệ thống (publishing, quảng cáo, nhắn tin khách hàng, chi tiêu) **bắt buộc** đi qua `atlas/actions/gateway.py`.
   - Không bao giờ tự suy diễn quyền `budget.spend` hay `publish.live` từ câu mục tiêu của người dùng.
   - Không dùng kiểu `float` cho tiền tệ; mọi số tiền lưu ở dạng số nguyên đơn vị nhỏ nhất (`amount_minor`, với VND là `1 VND = 1`).
3. **Tính trung thực dữ liệu**:
   - Không gán nhãn `verified_fact` cho nội dung do agent tự suy luận (`source_type="agent_inference"`).
   - Dữ liệu demo/fixture phải luôn có `is_demo=True` và nhãn rõ ràng.
4. **Kiểm thử**: Chạy `cd backend && uv run pytest -v` trước khi hoàn tất bất kỳ thay đổi nào.
