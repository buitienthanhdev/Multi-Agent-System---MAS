"""Controlled improvement: candidate -> sandbox_eval -> heldout_eval -> limited_rollout -> promoted | rolled_back.
Only prompt/skill/workflow targets. Policies, budgets, permissions, evaluators and production code are excluded."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from atlas.evaluations.evaluator import evaluate_content
from atlas.models import Evaluation, ImprovementCandidate

ALLOWED_TARGETS = {"prompt", "skill", "workflow"}
FORBIDDEN_NAMES = {"policy", "budget", "permission", "evaluator", "approval"}
FLOW = {"candidate": "sandbox_passed", "sandbox_passed": "heldout_passed", "heldout_passed": "limited_rollout",
        "limited_rollout": "promoted"}

SANDBOX_SET = [{"draft": "[DEMO] OneCoat gợi ý chọn màu sơn cho ngôi nhà đón Tết. Nhắn tin fanpage để được tư vấn phối màu "
                         "miễn phí theo ảnh góc tường của bạn. Thông số do bộ phận kỹ thuật cung cấp."}]
HELDOUT_SET = [{"draft": "[DEMO] Sơn lại phòng khách cùng OneCoat: gửi ảnh, nhận gợi ý màu và cách chuẩn bị bề mặt. "
                         "Đội tư vấn phản hồi qua fanpage; không cam kết thông số khi chưa có tài liệu kỹ thuật."}]


def propose_from_failures(s: Session) -> ImprovementCandidate | None:
    fails = s.scalars(select(Evaluation).where(Evaluation.verdict != "accepted")).all()
    if not fails:
        return None
    findings = sorted({f for e in fails for f in e.findings})
    c = ImprovementCandidate(target_type="prompt", target_name="content.system_prompt",
                             description="Bổ sung ràng buộc vào prompt content dựa trên lỗi review lặp lại",
                             proposal={"append_rules": findings[:10]}, source_failures=[e.id for e in fails][:20])
    s.add(c)
    s.flush()
    return c


def _score(samples: list[dict[str, Any]]) -> float:
    ok = sum(evaluate_content(x["draft"], {"must_mention": ["OneCoat"]}, True).verdict == "accepted" for x in samples)
    return ok / len(samples)


def advance(s: Session, c: ImprovementCandidate, rollout_metrics: dict[str, Any] | None = None) -> ImprovementCandidate:
    if c.target_type not in ALLOWED_TARGETS or any(f in c.target_name.lower() for f in FORBIDDEN_NAMES):
        c.status = "rejected_forbidden_target"
        return c
    if c.status == "candidate":
        sc = _score(SANDBOX_SET)
        c.results = {**c.results, "sandbox_score": sc}
        c.status = "sandbox_passed" if sc >= 1.0 else "rolled_back"
    elif c.status == "sandbox_passed":
        sc = _score(HELDOUT_SET)
        c.results = {**c.results, "heldout_score": sc}
        c.status = "heldout_passed" if sc >= 1.0 else "rolled_back"
    elif c.status == "heldout_passed":
        c.status = "limited_rollout"
        c.results = {**c.results, "rollout_fraction": 0.1}
    elif c.status == "limited_rollout":
        if rollout_metrics is None:
            raise ValueError("limited rollout requires observed metrics before promotion")
        better = rollout_metrics.get("acceptance_rate", 0) >= rollout_metrics.get("baseline_acceptance_rate", 1)
        c.results = {**c.results, "rollout_metrics": rollout_metrics}
        c.status = "promoted" if better else "rolled_back"
    return c
