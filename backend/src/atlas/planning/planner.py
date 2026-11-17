"""Planner: produces strategic options (<=3) with explicit tradeoffs across ALL mission domains (Software, Research,
Content/Media, Customer Care, Data Analysis, Docs/SOP, General Open-Ended Execution, and Marketing Growth), chooses the
optimal feasible option, and emits a multi-agent DAG of tasks + dependencies."""
from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from atlas.capabilities.registry import TEAM_LIMITS, compose_team
from atlas.models import Decision, Mission, Plan, Task, TaskDependency
from atlas.security import audit


def _options_for_type(task_type: str, contract: dict[str, Any]) -> list[dict[str, Any]]:
    permitted = set(contract.get("permitted_actions", []))
    if task_type == "marketing_growth":
        return [
            {
                "id": "A_small_test_first",
                "summary": "Nghiên cứu + 1 nội dung thử nghiệm + đo baseline/đối chứng trước khi giải ngân lớn",
                "requires": ["publish.sandbox"],
                "est_spend_minor": 0,
                "feasible": "publish.sandbox" in permitted,
                "tradeoff": "An toàn vốn, xác định đúng thông điệp và kênh có Lead Quality cao trước khi mở rộng",
            },
            {
                "id": "B_paid_ads",
                "summary": "Giải ngân quảng cáo trả phí quy mô lớn ngay từ ngày đầu",
                "requires": ["ads.launch", "budget.spend"],
                "est_spend_minor": 20_000_000,
                "feasible": {"ads.launch", "budget.spend"} <= permitted,
                "tradeoff": "Nhanh nhưng rủi ro đốt ngân sách khi chưa kiểm định giả thuyết thông điệp",
            },
            {
                "id": "C_dealer_push",
                "summary": "Chiến dịch chăm sóc trực tiếp tệp khách hàng/đại lý qua tin nhắn",
                "requires": ["message.send_customer"],
                "est_spend_minor": 5_000_000,
                "feasible": "message.send_customer" in permitted,
                "tradeoff": "Tỷ lệ chuyển đổi cao nhưng yêu cầu cấp quyền gửi tin trực tiếp tới khách hàng",
            },
        ]
    if task_type == "software":
        return [
            {
                "id": "A_sandbox_tdd_patch",
                "summary": "Khảo sát yêu cầu → Viết module/patch kèm Unit Test trong Sandbox cô lập → Kiểm duyệt độc lập → Báo cáo bàn giao",
                "requires": [],
                "est_spend_minor": 0,
                "feasible": True,
                "tradeoff": "Đảm bảo 100% code chạy qua kiểm thử cú pháp (`ast.parse`) và unit test trước khi trình kỹ sư review",
            },
            {
                "id": "B_direct_production_deploy",
                "summary": "Tự động sửa mã nguồn và triển khai thẳng lên môi trường production",
                "requires": ["code.deploy_production"],
                "est_spend_minor": 0,
                "feasible": False,
                "tradeoff": "Bị cấm theo chính sách an toàn: Agent không bao giờ tự merge hoặc deploy production",
            },
        ]
    if task_type == "market_research":
        return [
            {
                "id": "A_multi_source_verified_synthesis",
                "summary": "Thu thập đa nguồn (HTTPS / Kho tri thức) → Quét lọc Prompt Injection → Đối chiếu & Phân loại Bằng chứng → Tổng hợp Báo cáo",
                "requires": [],
                "est_spend_minor": 0,
                "feasible": True,
                "tradeoff": "Tách biệt rõ sự thật đã xác minh (verified_fact) và giả thuyết (assumption), chống nhiễu thông tin",
            },
            {
                "id": "B_single_pass_llm_summary",
                "summary": "Tóm tắt nhanh một bước từ trí nhớ nội tại của mô hình ngôn ngữ",
                "requires": [],
                "est_spend_minor": 0,
                "feasible": True,
                "tradeoff": "Nhanh nhưng dễ gặp hiện tượng ảo giác (hallucination) và thiếu trích dẫn nguồn thực tế",
            },
        ]
    if task_type == "content_media":
        return [
            {
                "id": "A_research_draft_wireframe_review",
                "summary": "Nghiên cứu chủ đề → Soạn nội dung + Thiết kế bố cục SVG Wireframe → Kiểm duyệt độc lập (Independent Evaluator) → Bàn giao",
                "requires": [],
                "est_spend_minor": 0,
                "feasible": True,
                "tradeoff": "Đảm bảo cả phần chữ và bố cục hình ảnh đều đồng nhất, không vi phạm quy chuẩn thương hiệu",
            },
            {
                "id": "B_unreviewed_fast_draft",
                "summary": "Sinh nhanh bản nháp không qua cổng kiểm duyệt độc lập",
                "requires": [],
                "est_spend_minor": 0,
                "feasible": True,
                "tradeoff": "Tiết kiệm bước nhưng nguy cơ lọt thông số chưa kiểm chứng sang người dùng",
            },
        ]
    if task_type == "customer_care":
        return [
            {
                "id": "A_structured_playbook_with_escalation",
                "summary": "Phân tích tình huống khách hàng → Xây dựng Playbook tư vấn & ma trận xử lý khiếu nại → Kiểm duyệt tuân thủ → Bàn giao",
                "requires": [],
                "est_spend_minor": 0,
                "feasible": True,
                "tradeoff": "Chuẩn hóa quy trình phản hồi và giới hạn thẩm quyền rõ ràng trước khi áp dụng cho đội CSKH/Chatbot",
            },
            {
                "id": "B_auto_reply_live_customers",
                "summary": "Cho phép Agent tự động trả lời trực tiếp mọi khách hàng ngay lập tức",
                "requires": ["message.send_customer"],
                "est_spend_minor": 0,
                "feasible": "message.send_customer" in permitted,
                "tradeoff": "Rủi ro cam kết sai chính sách nếu chưa được cấp quyền message.send_customer",
            },
        ]
    if task_type == "data_analysis":
        return [
            {
                "id": "A_baseline_did_causal_audit",
                "summary": "Kiểm tra chất lượng dữ liệu & Xu hướng nền (Parallel Trends) → Phân tích đối chứng (DiD & 95% CI) → Xuất báo cáo tách biệt Verified/Estimate",
                "requires": [],
                "est_spend_minor": 0,
                "feasible": True,
                "tradeoff": "Chặt chẽ về mặt thống kê, tránh ngụy biện nhân quả từ biến nhiễu",
            },
            {
                "id": "B_descriptive_averages_only",
                "summary": "Chỉ tính trung bình cộng trước và sau sự kiện (không có nhóm đối chứng)",
                "requires": [],
                "est_spend_minor": 0,
                "feasible": True,
                "tradeoff": "Đơn giản nhưng dễ nhầm biến động mùa vụ thành hiệu quả thực",
            },
        ]
    if task_type == "docs_ops":
        return [
            {
                "id": "A_sop_with_verification_and_runbook",
                "summary": "Khảo sát hiện trạng → Soạn quy trình SOP, Checklist & Runbook xử lý sự cố → Kiểm duyệt độc lập → Xuất tài liệu chuẩn",
                "requires": [],
                "est_spend_minor": 0,
                "feasible": True,
                "tradeoff": "Tài liệu có thể áp dụng vận hành ngay, đầy đủ bước kiểm tra an toàn và khôi phục",
            },
        ]
    # general_execution (Universal Open-Ended Problem Solving)
    return [
        {
            "id": "A_universal_multi_agent_pipeline",
            "summary": "Thu thập & phân tích bối cảnh (Research) → Soạn giải pháp/đầu ra chuyên sâu (Content/Execution) → Kiểm duyệt độc lập (Review) → Báo cáo tổng hợp (Report)",
            "requires": [],
            "est_spend_minor": 0,
            "feasible": True,
            "tradeoff": "Phối hợp đa tác nhân có cổng kiểm duyệt độc lập giúp giải quyết mọi bài toán mở với độ tin cậy cao",
        },
        {
            "id": "B_single_step_direct_answer",
            "summary": "Trả lời trực tiếp trong một bước duy nhất không qua kiểm chứng",
            "requires": [],
            "est_spend_minor": 0,
            "feasible": True,
            "tradeoff": "Nhanh hơn cho câu hỏi đơn giản nhưng thiếu đối chiếu nguồn và kiểm duyệt chất lượng",
        },
    ]


def _tasks_marketing() -> list[dict[str, Any]]:
    return [
        {
            "key": "research",
            "title": "Nghiên cứu thị trường & giả thuyết",
            "capability": "research",
            "deps": [],
            "expected_output": "Brief phân khúc, kênh, giả thuyết có cách kiểm chứng",
            "acceptance": ["Mỗi giả thuyết có cách kiểm chứng", "Nguồn độc hại bị gắn cờ"],
            "estimate": {"minutes": 2, "cost_minor": 0},
        },
        {
            "key": "baseline",
            "title": "Đo baseline doanh thu",
            "capability": "analytics",
            "deps": [],
            "input": {"mode": "baseline"},
            "expected_output": "Doanh thu 30 ngày gần nhất + khoảng cách tới mục tiêu",
            "acceptance": ["Baseline có nguồn", "Phân biệt tổng và tăng thêm"],
            "estimate": {"minutes": 1, "cost_minor": 0},
        },
        {
            "key": "content",
            "title": "Soạn nội dung chiến dịch",
            "capability": "content",
            "deps": ["research"],
            "expected_output": "Bản nháp thông điệp truyền thông",
            "acceptance": ["Không thông số chưa xác minh"],
            "estimate": {"minutes": 2, "cost_minor": 0},
        },
        {
            "key": "review",
            "title": "Kiểm duyệt độc lập (Independent Evaluator)",
            "capability": "review",
            "deps": ["content"],
            "expected_output": "Verdict + findings",
            "acceptance": ["Validator tất định + LLM Judge chạy đủ"],
            "estimate": {"minutes": 1},
        },
        {
            "key": "publish",
            "title": "Thực thi xuất bản qua Action Gateway (cần duyệt)",
            "capability": "publishing",
            "deps": ["review", "baseline"],
            "expected_output": "Receipt từ connector",
            "acceptance": ["Approval khớp payload hash"],
            "estimate": {"minutes": 1, "cost_minor": 0},
        },
        {
            "key": "results",
            "title": "Phân tích kết quả đối chứng (DiD & Parallel Trends)",
            "capability": "analytics",
            "deps": ["publish"],
            "input": {"mode": "results"},
            "expected_output": "Doanh thu tổng, tăng thêm ước tính, kiểm định thống kê & tối ưu đóng vòng",
            "acceptance": ["Tách verified vs estimate"],
            "estimate": {"minutes": 1},
        },
        {
            "key": "report",
            "title": "Báo cáo tổng hợp",
            "capability": "report",
            "deps": ["results"],
            "expected_output": "Báo cáo trên dashboard",
            "acceptance": ["Không dùng số chưa đối soát như đã xác minh"],
            "estimate": {"minutes": 1},
        },
    ]


def _tasks_for_type(task_type: str) -> list[dict[str, Any]]:
    if task_type == "marketing_growth":
        return _tasks_marketing()
    if task_type == "content_media":
        return [
            {
                "key": "research",
                "title": "Nghiên cứu chủ đề, đối tượng & thông điệp cốt lõi",
                "capability": "research",
                "deps": [],
                "expected_output": "Brief chủ đề & góc tiếp cận",
                "acceptance": ["Có nguồn tham chiếu rõ ràng"],
                "estimate": {"minutes": 2},
            },
            {
                "key": "content",
                "title": "Biên soạn nội dung chi tiết",
                "capability": "content",
                "deps": ["research"],
                "expected_output": "Bản thảo hoàn chỉnh",
                "acceptance": ["Đúng cấu trúc, không bịa thông số"],
                "estimate": {"minutes": 2},
            },
            {
                "key": "media",
                "title": "Thiết kế bố cục trực quan (SVG Wireframe Spec)",
                "capability": "media",
                "deps": ["research"],
                "expected_output": "SVG Layout Wireframe",
                "acceptance": ["Gắn nhãn rõ ràng"],
                "estimate": {"minutes": 1},
            },
            {
                "key": "review",
                "title": "Kiểm duyệt chất lượng độc lập",
                "capability": "review",
                "deps": ["content"],
                "expected_output": "Verdict + findings",
                "acceptance": ["Đạt tiêu chí"],
                "estimate": {"minutes": 1},
            },
            {
                "key": "report",
                "title": "Đóng gói bộ hồ sơ Nội dung & Media",
                "capability": "report",
                "deps": ["review", "media"],
                "expected_output": "Báo cáo bàn giao",
                "acceptance": ["Đầy đủ"],
                "estimate": {"minutes": 1},
            },
        ]
    if task_type == "customer_care":
        return [
            {
                "key": "research",
                "title": "Phân tích nhu cầu, câu hỏi thường gặp & điểm đau của khách hàng",
                "capability": "research",
                "deps": [],
                "expected_output": "Danh mục tình huống khách hàng",
                "acceptance": ["Có nguồn"],
                "estimate": {"minutes": 2},
            },
            {
                "key": "sales_playbook",
                "title": "Xây dựng Playbook Tư vấn, Xử lý Khiếu nại & Quy trình Escalation",
                "capability": "sales_assistance",
                "deps": ["research"],
                "expected_output": "Playbook tư vấn chuẩn hóa",
                "acceptance": ["Không tự cam kết vượt thẩm quyền"],
                "estimate": {"minutes": 2},
            },
            {
                "key": "report",
                "title": "Báo cáo bàn giao Playbook Chăm sóc Khách hàng",
                "capability": "report",
                "deps": ["sales_playbook"],
                "expected_output": "Báo cáo tổng hợp",
                "acceptance": ["Đầy đủ"],
                "estimate": {"minutes": 1},
            },
        ]
    if task_type == "software":
        return [
            {
                "key": "research",
                "title": "Phân tích yêu cầu kỹ thuật, kiến trúc & ca kiểm thử biên (Edge Cases)",
                "capability": "research",
                "deps": [],
                "expected_output": "Đặc tả kỹ thuật & danh sách test cases",
                "acceptance": ["Xác định rõ input/output và ràng buộc an toàn"],
                "estimate": {"minutes": 1},
            },
            {
                "key": "code_patch",
                "title": "Viết mã nguồn (Patch) & Chạy kiểm thử tự động trong Sandbox cô lập",
                "capability": "software_engineering",
                "deps": ["research"],
                "expected_output": "Unified diff patch + kết quả chạy AST & unit test trong sandbox",
                "acceptance": ["Sandbox test pass 100%", "Không tự merge vào production"],
                "estimate": {"minutes": 2},
            },
            {
                "key": "report",
                "title": "Báo cáo kỹ thuật & Hướng dẫn tích hợp bản vá",
                "capability": "report",
                "deps": ["code_patch"],
                "expected_output": "Báo cáo bàn giao kỹ thuật",
                "acceptance": ["Đầy đủ"],
                "estimate": {"minutes": 1},
            },
        ]
    if task_type == "data_analysis":
        return [
            {
                "key": "baseline",
                "title": "Kiểm tra dữ liệu nền & Kiểm định xu hướng song song (Parallel Trends)",
                "capability": "analytics",
                "deps": [],
                "input": {"mode": "baseline"},
                "expected_output": "Thống kê baseline & p-value xu hướng nền",
                "acceptance": ["Có nguồn dữ liệu rõ ràng"],
                "estimate": {"minutes": 1},
            },
            {
                "key": "results",
                "title": "Phân tích thống kê chuyên sâu & Ước lượng khoảng tin cậy 95% CI",
                "capability": "analytics",
                "deps": ["baseline"],
                "input": {"mode": "results"},
                "expected_output": "Kết quả phân tích, sai số chuẩn & khuyến nghị tối ưu",
                "acceptance": ["Tách bạch verified_fact và estimate"],
                "estimate": {"minutes": 1},
            },
            {
                "key": "report",
                "title": "Báo cáo Khoa học Dữ liệu & Khuyến nghị Quyết định",
                "capability": "report",
                "deps": ["results"],
                "expected_output": "Báo cáo phân tích hoàn chỉnh",
                "acceptance": ["Không trộn số ước tính vào mục đã xác minh"],
                "estimate": {"minutes": 1},
            },
        ]
    if task_type == "docs_ops":
        return [
            {
                "key": "research",
                "title": "Khảo sát quy trình hiện hành, rủi ro vận hành & tiêu chuẩn tuân thủ",
                "capability": "research",
                "deps": [],
                "expected_output": "Khung yêu cầu SOP & danh mục kiểm soát rủi ro",
                "acceptance": ["Có nguồn"],
                "estimate": {"minutes": 2},
            },
            {
                "key": "content",
                "title": "Soạn thảo Quy trình Chuẩn (SOP), Checklist Vận hành & Runbook Sự cố",
                "capability": "content",
                "deps": ["research"],
                "expected_output": "Tài liệu SOP / Runbook chi tiết từng bước",
                "acceptance": ["Đầy đủ bước thực hiện, kiểm tra và khôi phục"],
                "estimate": {"minutes": 2},
            },
            {
                "key": "review",
                "title": "Kiểm duyệt tính tuân thủ & an toàn vận hành (Independent Evaluator)",
                "capability": "review",
                "deps": ["content"],
                "expected_output": "Verdict + findings",
                "acceptance": ["Đạt tiêu chí"],
                "estimate": {"minutes": 1},
            },
            {
                "key": "report",
                "title": "Báo cáo ban hành Tài liệu Vận hành Nội bộ",
                "capability": "report",
                "deps": ["review"],
                "expected_output": "Báo cáo tổng hợp",
                "acceptance": ["Đầy đủ"],
                "estimate": {"minutes": 1},
            },
        ]

    # Multi-disciplinary professional pipelines across 17 specialized careers
    SPECIALIZED_PIPELINES: dict[str, list[tuple[str, str, str, list[str]]]] = {
        "finance_accounting": [
            ("research", "Thu thập dữ liệu chi phí, doanh thu & thông số vĩ mô", "research", []),
            ("financial_model", "Lập Mô hình Tài chính CAPEX/OPEX, Điểm hòa vốn & Dòng tiền", "finance_cfo", ["research"]),
            ("legal_check", "Thẩm định tuân thủ thuế & quy chế kiểm soát tài chính", "legal_counsel", ["financial_model"]),
            ("report", "Báo cáo Thẩm định Tài chính & Ngân sách Tổng hợp", "report", ["legal_check"]),
        ],
        "legal_compliance": [
            ("research", "Tra cứu quy định pháp luật hiện hành & phạm vi điều chỉnh", "research", []),
            ("legal_review", "Soạn thảo & Thẩm định Điều khoản Hợp đồng / Chính sách Pháp chế", "legal_counsel", ["research"]),
            ("security_privacy", "Đánh giá tuân thủ Bảo vệ Dữ liệu Cá nhân & Bảo mật", "cyber_security", ["legal_review"]),
            ("report", "Báo cáo Kết luận Thẩm định Pháp chế & Tuân thủ", "report", ["security_privacy"]),
        ],
        "hr_recruitment": [
            ("research", "Khảo sát mặt bằng năng lực thị trường lao động & nhu cầu phòng ban", "research", []),
            ("hr_framework", "Xây dựng JD, Bộ Câu hỏi Phỏng vấn (Rubric) & Lộ trình Onboarding 30-60-90", "hr_talent", ["research"]),
            ("legal_labor", "Rà soát tuân thủ Bộ luật Lao động & Quy chế Nội bộ", "legal_counsel", ["hr_framework"]),
            ("report", "Báo cáo Bàn giao Bộ Khung Tuyển dụng & Đào tạo Nhân sự", "report", ["legal_labor"]),
        ],
        "supply_chain_ops": [
            ("research", "Phân tích nhu cầu tiêu thụ, Lead Time & năng lực nhà cung ứng", "research", []),
            ("supply_plan", "Tính toán Tồn kho An toàn (Safety Stock), Điểm đặt hàng (ROP) & Điều phối Logistics", "supply_chain", ["research"]),
            ("finance_working_cap", "Đánh giá Vốn lưu động (Working Capital) & Vòng quay Tồn kho", "finance_cfo", ["supply_plan"]),
            ("report", "Báo cáo Kế hoạch Chuỗi Cung ứng & Kho vận", "report", ["finance_working_cap"]),
        ],
        "devops_cloud": [
            ("research", "Khảo sát kiến trúc hệ thống, tải lượng & yêu cầu SLA/SLO", "research", []),
            ("sre_blueprint", "Thiết kế Pipeline CI/CD, Auto-Scaling, SLI/SLO & Khôi phục Thảm họa (DR)", "devops_sre", ["research"]),
            ("secops_audit", "Kiểm toán Bảo mật Hạ tầng Cloud & Chính sách Zero-Trust", "cyber_security", ["sre_blueprint"]),
            ("qa_gate", "Xác lập Cổng Kiểm thử Tự động trước khi Triển khai (Release Gate)", "qa_automation", ["secops_audit"]),
            ("report", "Báo cáo Kiến trúc DevOps/SRE & Sẵn sàng Vận hành", "report", ["qa_gate"]),
        ],
        "cybersecurity_audit": [
            ("research", "Thu thập bề mặt tấn công (Attack Surface) & danh mục tài sản số", "research", []),
            ("threat_model", "Phân tích Mối đe dọa STRIDE, Kiểm toán OWASP & An toàn AI", "cyber_security", ["research"]),
            ("sre_hardening", "Thiết kế Phương án Cô lập & Gia cố Hạ tầng (Hardening)", "devops_sre", ["threat_model"]),
            ("code_fix", "Sinh Bản vá Bảo mật (Security Patch) trong Sandbox Cô lập", "software_engineering", ["threat_model"]),
            ("report", "Báo cáo Kiểm toán An ninh Mạng & Khắc phục Lỗ hổng", "report", ["sre_hardening", "code_fix"]),
        ],
        "product_management": [
            ("research", "Nghiên cứu Nhu cầu Người dùng (JTBD) & Phân tích Đối thủ", "research", []),
            ("ba_process", "Phân tích Quy trình Nghiệp vụ BPMN & Đặc tả Quy tắc (BRD)", "business_analyst", ["research"]),
            ("prd_ux", "Biên soạn Tài liệu Sản phẩm (PRD), User Stories & Luồng Trải nghiệm UX", "product_ux", ["ba_process"]),
            ("qa_criteria", "Xây dựng Ma trận Kiểm thử Nghiệm thu (UAT Test Matrix)", "qa_automation", ["prd_ux"]),
            ("report", "Báo cáo Bàn giao Hồ sơ Sản phẩm (PRD + BRD + UAT)", "report", ["qa_criteria"]),
        ],
        "seo_organic": [
            ("research", "Phân tích Ý định Tìm kiếm (Search Intent) & Đối thủ trên SERP", "research", []),
            ("seo_cluster", "Xây dựng Cụm Chủ đề Từ khóa (Topic Cluster) & Kiến trúc On-Page", "seo_growth", ["research"]),
            ("content", "Biên soạn Bài viết Chuẩn SEO Chuyên sâu", "content", ["seo_cluster"]),
            ("review", "Kiểm duyệt Độc lập Chất lượng Nội dung & Chính sách", "review", ["content"]),
            ("report", "Báo cáo Chiến lược SEO & Tăng trưởng Lưu lượng Tự nhiên", "report", ["review"]),
        ],
        "pr_crisis_comms": [
            ("research", "Thu thập Thông tin Sự việc & Đánh giá Mức độ Ảnh hưởng Truyền thông", "research", []),
            ("pr_kit", "Soạn thảo Thông cáo Báo chí, Kịch bản Q&A & Quy trình Phản ứng 60 Phút đầu", "pr_comms", ["research"]),
            ("legal_clearance", "Thẩm định Rủi ro Pháp lý trong Phát ngôn Công chúng", "legal_counsel", ["pr_kit"]),
            ("review", "Kiểm duyệt Độc lập Tính Xác thực & Chuẩn mực Thương hiệu", "review", ["legal_clearance"]),
            ("report", "Báo cáo Ban hành Bộ Hồ sơ Quan hệ Công chúng / Xử lý Khủng hoảng", "report", ["review"]),
        ],
        "data_engineering": [
            ("research", "Khảo sát Hệ thống Nguồn, Tần suất Đồng bộ & Khối lượng Dữ liệu", "research", []),
            ("pipeline_spec", "Thiết kế Schema Kho Dữ liệu, Luồng ETL/ELT Idempotent & Data Quality", "data_engineer", ["research"]),
            ("code_patch", "Viết Module Kiểm tra Tính Toàn vẹn Dữ liệu trong Sandbox", "software_engineering", ["pipeline_spec"]),
            ("report", "Báo cáo Kiến trúc Kỹ thuật Dữ liệu & ETL Pipeline", "report", ["code_patch"]),
        ],
        "rd_product_lab": [
            ("research", "Tổng hợp Tài liệu Khoa học, Tiêu chuẩn ASTM/ISO/TCVN & Vật liệu", "research", []),
            ("rd_dossier", "Thiết kế Thí nghiệm Phòng Lab (DoE), Công thức & Tiêu chuẩn An toàn EHS", "rd_scientist", ["research"]),
            ("supply_sourcing", "Đánh giá Nguồn Cung ứng Nguyên vật liệu & Kiểm soát Chất lượng Đầu vào", "supply_chain", ["rd_dossier"]),
            ("report", "Báo cáo Hồ sơ Nghiên cứu & Phát triển Sản phẩm (R&D Dossier)", "report", ["supply_sourcing"]),
        ],
        "strategy_consulting": [
            ("research", "Khảo sát Thị trường Vĩ mô, Xu hướng Ngành & Vị thế Cạnh tranh", "research", []),
            ("strategy_deck", "Phân tích Chiến lược (SWOT / Porter's 5 Forces) & Bản đồ Mục tiêu OKR", "strategy_consultant", ["research"]),
            ("financial_projection", "Mô hình hóa Hiệu quả Tài chính & Phân bổ Nguồn lực Chiến lược", "finance_cfo", ["strategy_deck"]),
            ("pmo_roadmap", "Lập Lộ trình Triển khai Tổng thể (Master WBS & RACI)", "project_pmo", ["financial_projection"]),
            ("report", "Báo cáo Tư vấn Chiến lược Doanh nghiệp Toàn diện", "report", ["pmo_roadmap"]),
        ],
        "qa_testing": [
            ("research", "Phân tích Đặc tả Hệ thống & Nhận diện Các Điểm Rủi ro Cao", "research", []),
            ("qa_matrix", "Thiết kế Ma trận Kiểm thử Đa tầng (Unit/Integration/E2E/Boundary)", "qa_automation", ["research"]),
            ("code_test", "Viết & Chạy Script Kiểm thử Tự động trong Sandbox Cô lập", "software_engineering", ["qa_matrix"]),
            ("report", "Báo cáo Kế hoạch Đảm bảo Chất lượng & Kết quả Kiểm thử", "report", ["code_test"]),
        ],
        "translation_localization": [
            ("research", "Phân tích Ngữ cảnh Chuyên ngành & Quy chuẩn Thị trường Đích", "research", []),
            ("localization", "Biên dịch Đa ngôn ngữ, Xây dựng Bảng Thuật ngữ (Glossary) & Bản địa hóa", "localization_pro", ["research"]),
            ("review", "Kiểm duyệt Độc lập Độ Chính xác Thuật ngữ & Văn phong (LQA)", "review", ["localization"]),
            ("report", "Báo cáo Bàn giao Hồ sơ Dịch thuật & Bản địa hóa", "report", ["review"]),
        ],
        "business_analysis": [
            ("research", "Khảo sát Hiện trạng Quy trình (As-Is) & Nhu cầu Các Bên Liên quan", "research", []),
            ("brd_spec", "Xây dựng Tài liệu Yêu cầu Nghiệp vụ (BRD), Quy trình To-Be BPMN & Ma trận RTM", "business_analyst", ["research"]),
            ("ux_alignment", "Đồng bộ Luồng Trải nghiệm Người dùng & Tiêu chí Nghiệm thu", "product_ux", ["brd_spec"]),
            ("report", "Báo cáo Phân tích Nghiệp vụ & Đặc tả Quy trình", "report", ["ux_alignment"]),
        ],
        "ecommerce_ops": [
            ("research", "Khảo sát Hành vi Mua sắm trên Sàn TMĐT & Phân tích Gian hàng Đối thủ", "research", []),
            ("merch_plan", "Tối ưu Trang Sản phẩm (PDP), Chiến lược Bundling & Chỉ số Chuyển đổi (CRO)", "ecommerce_merch", ["research"]),
            ("supply_fulfillment", "Chuẩn hóa Quy trình Đóng gói, Tồn kho Sàn & SLA Giao hàng", "supply_chain", ["merch_plan"]),
            ("report", "Báo cáo Kế hoạch Vận hành & Tăng trưởng Gian hàng TMĐT", "report", ["supply_fulfillment"]),
        ],
        "project_management": [
            ("research", "Xác định Phạm vi Dự án, Nguồn lực & Ràng buộc Kỹ thuật/Nghiệp vụ", "research", []),
            ("pmo_plan", "Lập Cấu trúc Phân rã Công việc (WBS), Đường găng Tiến độ, RACI & Sổ Rủi ro", "project_pmo", ["research"]),
            ("finance_budget", "Lập Dự toán Ngân sách Dự án & Kế hoạch Kiểm soát Chi phí", "finance_cfo", ["pmo_plan"]),
            ("report", "Báo cáo Kế hoạch Quản trị Dự án Tổng thể (PMO Charter)", "report", ["finance_budget"]),
        ],
    }

    if task_type in SPECIALIZED_PIPELINES:
        return [
            {
                "key": k,
                "title": title,
                "capability": cap,
                "deps": deps,
                "expected_output": title,
                "acceptance": ["Hoàn thành đầy đủ chuyên môn", "Tuân thủ ranh giới an toàn"],
                "estimate": {"minutes": 2},
            }
            for k, title, cap, deps in SPECIALIZED_PIPELINES[task_type]
        ]
    # market_research OR general_execution (Universal Open-Ended Task Pipeline)
    return [
        {
            "key": "research",
            "title": "Thu thập dữ liệu, phân tích bối cảnh & xây dựng luận cứ",
            "capability": "research",
            "deps": [],
            "expected_output": "Báo cáo khảo sát đa nguồn & phân loại bằng chứng",
            "acceptance": ["Tách biệt verified_fact và assumption"],
            "estimate": {"minutes": 2},
        },
        {
            "key": "content",
            "title": "Xây dựng phương án giải quyết chi tiết / Tài liệu đầu ra",
            "capability": "content",
            "deps": ["research"],
            "expected_output": "Tài liệu giải pháp hoàn chỉnh đáp ứng mục tiêu",
            "acceptance": ["Rõ ràng, khả thi, có căn cứ"],
            "estimate": {"minutes": 2},
        },
        {
            "key": "review",
            "title": "Kiểm duyệt độc lập chất lượng đầu ra (Independent Evaluator)",
            "capability": "review",
            "deps": ["content"],
            "expected_output": "Verdict + findings",
            "acceptance": ["Đạt kiểm duyệt"],
            "estimate": {"minutes": 1},
        },
        {
            "key": "report",
            "title": "Tổng hợp Báo cáo Nghiệm thu & Đề xuất Bước tiếp theo",
            "capability": "report",
            "deps": ["review"],
            "expected_output": "Báo cáo tổng hợp cuối cùng",
            "acceptance": ["Nêu rõ kết quả, giả định và giới hạn"],
            "estimate": {"minutes": 1},
        },
    ]


def create_plan(s: Session, mission: Mission, contract: dict[str, Any], actor: str) -> Plan:
    task_type = contract.get("task_type", "general_execution")
    options = _options_for_type(task_type, contract)
    chosen = next((o for o in options if o["feasible"]), options[0] if options else None)
    specs = _tasks_for_type(task_type)
    if len(specs) > TEAM_LIMITS["max_tasks_per_plan"]:
        raise ValueError("plan too large")
    team = compose_team(s, [t["capability"] for t in specs])
    version = (s.scalar(select(func.max(Plan.version)).where(Plan.mission_id == mission.id)) or 0) + 1
    plan = Plan(
        mission_id=mission.id,
        version=version,
        options=options,
        chosen_option=chosen["id"] if chosen else "default_universal",
        replanning_triggers=[
            "Review độc lập từ chối quá 2 lần",
            "Action bên ngoài bị từ chối phê duyệt",
            "Dữ liệu đầu vào hoặc giả định nền thay đổi đáng kể",
            "Người dùng cập nhật mục tiêu hoặc phạm vi quyền hạn",
        ],
    )
    s.add(plan)
    s.flush()
    by_key: dict[str, Task] = {}
    for t in specs:
        task = Task(
            plan_id=plan.id,
            mission_id=mission.id,
            workspace_id=mission.workspace_id,
            key=t["key"],
            title=t["title"],
            capability=t["capability"],
            input=t.get("input", {}),
            expected_output=t["expected_output"],
            acceptance_criteria=t["acceptance"],
            estimate=t["estimate"],
            failure_handling="retry tối đa 3 lần với backoff; sau đó chuyển vào danh sách xử lý thủ công (dead-letter)",
        )
        s.add(task)
        s.flush()
        by_key[t["key"]] = task
        for d in t["deps"]:
            s.add(TaskDependency(task_id=task.id, depends_on_id=by_key[d].id))
    s.add(
        Decision(
            mission_id=mission.id,
            kind="plan_selection",
            summary=f"[{contract.get('domain_label', task_type)}] Chọn phương án {plan.chosen_option}",
            rationale=chosen["tradeoff"] if chosen else "Phối hợp đội agent chuyên môn theo quy trình có kiểm duyệt độc lập.",
            made_by="planner_v2_universal",
            data={"task_type": task_type, "options": options, "team": team},
        )
    )
    audit(s, mission.workspace_id, actor, "plan.created", {"plan_id": plan.id, "task_type": task_type, "tasks": len(specs)}, mission.id)
    return plan
