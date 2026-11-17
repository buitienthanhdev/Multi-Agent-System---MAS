"""Independent Evaluator. Separate from the planner/producer; cannot change objectives or acceptance criteria
(it receives them read-only and returns a verdict)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

from atlas.policies.engine import DEFAULT_RULES

SPEC_PATTERNS = [r"\d+\s*(m2|m²)\s*/\s*(lít|l)\b", r"bảo hành\s*\d+\s*(năm|tháng)", r"\d+\s*(giờ|phút)\s*(khô|khô bề mặt)",
                 r"chống thấm\s*\d+", r"giá\s*(chỉ)?\s*\d"]


@dataclass
class Verdict:
    verdict: str  # accepted|revision_requested|rejected|needs_human
    scores: dict[str, Any]
    findings: list[str] = field(default_factory=list)
    evaluator: str = "deterministic_v1"


def evaluate_content(content: str, criteria: Mapping[str, Any], is_demo: bool, use_llm_judge: bool = False) -> Verdict:
    criteria = MappingProxyType(dict(criteria))  # read-only view
    findings: list[str] = []
    low = content.lower()
    for pat in DEFAULT_RULES["blocked_content_patterns"]:
        if pat in low:
            findings.append(f"Nội dung chứa cụm bị cấm: '{pat}'")
    for pat in SPEC_PATTERNS:
        if re.search(pat, low):
            findings.append(f"Có thông số/giá/bảo hành chưa xác minh (mẫu '{pat}')")
    if is_demo and "[demo]" not in low:
        findings.append("Thiếu nhãn [DEMO] cho nội dung tạo từ dữ liệu demo")
    min_len, max_len = criteria.get("min_chars", 120), criteria.get("max_chars", 1500)
    if not (min_len <= len(content) <= max_len):
        findings.append(f"Độ dài {len(content)} ngoài khoảng [{min_len},{max_len}]")
    for kw in criteria.get("must_mention", []):
        if kw.lower() not in low:
            findings.append(f"Thiếu nội dung bắt buộc: {kw}")
    if re.search(r"(?i)ignore (all )?previous|ATLAS_[A-Z_]*SECRET", content):
        findings.append("Nội dung chứa chỉ thị độc hại từ nguồn ngoài")

    llm_judge_status: Any = "skipped_fast_mode"
    evaluator_name = "deterministic_v1"
    if use_llm_judge and not findings:
        try:
            from atlas.llm import get_provider
            prov = get_provider()
            if prov.name != "template(no-llm)":
                j_res = prov.generate(
                    "Bạn là giám khảo độc lập kiểm duyệt nội dung quảng cáo sơn. Chỉ trả lời 'PASS' nếu nội dung "
                    "rõ ràng, lịch sự, không hứa hẹn sai sự thật; hoặc 'FAIL: <lý do ngắn>' nếu vi phạm.",
                    f"Đánh giá đoạn nội dung sau:\n{content}",
                    "PASS",
                )
                evaluator_name = f"deterministic_v1+{prov.name}"
                llm_judge_status = j_res.text[:160]
                first_line = j_res.text.strip().splitlines()[0].upper() if j_res.text.strip() else ""
                if first_line.startswith("FAIL:"):
                    findings.append(f"LLM-as-Judge từ chối: {j_res.text.strip()[:120]}")
        except Exception as e:
            llm_judge_status = f"error:{type(e).__name__}"

    scores = {"deterministic_checks_passed": not findings, "n_findings": len(findings), "llm_judge": llm_judge_status}
    hard = any("độc hại" in f or "bị cấm" in f for f in findings)
    verdict = "accepted" if not findings else ("rejected" if hard and criteria.get("strict") else "revision_requested")
    return Verdict(verdict=verdict, scores=scores, findings=findings, evaluator=evaluator_name)


def evaluate_report_numbers(report: dict[str, Any]) -> list[str]:
    """Report must not present unreconciled/estimated numbers as verified."""
    problems = []
    for item in report.get("verified_results", []):
        if item.get("kind") != "verified_fact":
            problems.append(f"Non-verified item in verified_results: {item.get('claim')}")
    return problems
