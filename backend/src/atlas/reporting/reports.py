"""Reporting: builds reports only from stored evidence/ledger/actions. Scheduler is DB-deduplicated."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from atlas.budgets.ledger import summary
from atlas.models import Action, BudgetAccount, Decision, Evidence, Mission, MissionVersion, Report, Task


def _vnd(n: int | None) -> str:
    return "n/a" if n is None else f"{n:,}".replace(",", ".") + " ₫"


def build_report_content(s: Session, m: Mission) -> dict[str, Any]:
    contract = s.scalar(select(MissionVersion.contract).where(MissionVersion.mission_id == m.id,
                                                              MissionVersion.version == m.current_version)) or {}
    tasks = s.scalars(select(Task).where(Task.mission_id == m.id)).all()
    ev = s.scalars(select(Evidence).where(Evidence.mission_id == m.id)).all()
    accts = s.scalars(select(BudgetAccount).where(BudgetAccount.mission_id == m.id)).all()
    actions = s.scalars(select(Action).where(Action.mission_id == m.id)).all()
    decisions = s.scalars(select(Decision).where(Decision.mission_id == m.id).order_by(Decision.created_at.desc())).all()
    counts: dict[str, int] = {}
    for t in tasks:
        counts[t.status] = counts.get(t.status, 0) + 1

    def item(e: Evidence) -> dict[str, Any]:
        return {"claim": e.claim, "kind": e.kind, "source": e.source, "is_demo": e.is_demo, "value": e.value}

    verified = [item(e) for e in ev if e.kind == "verified_fact"]
    estimates = [item(e) for e in ev if e.kind == "estimate"]
    gross = next((e.value["amount_minor"] for e in ev if e.scope == "campaign_30d_treated_gross" and e.value), None)
    target = (contract.get("target") or {}).get("amount_minor")
    pending = [{"action_id": a.id, "type": a.action_type, "status": a.status} for a in actions
               if a.status in ("awaiting_approval", "unknown")]
    blockers = [{"task": t.key, "status": t.status, "reason": t.blocked_reason or t.error} for t in tasks
                if t.status in ("blocked", "failed", "waiting_approval")]
    return {
        "mission_id": m.id, "mission_status": m.status, "is_demo": m.is_demo,
        "data_label": "DEMO / fixture data - không phải số liệu kinh doanh thật" if m.is_demo else "live",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "progress": {"task_counts": counts, "total_tasks": len(tasks),
                     "target_minor": target, "target_interpretation": contract.get("target_interpretation"),
                     "gross_revenue_verified_minor": gross,
                     "target_progress_ratio": (gross / target) if (gross and target) else None},
        "verified_results": verified,
        "estimates_not_verified": estimates,
        "budget": [summary(a) for a in accts],
        "assumptions": contract.get("assumptions", []) + [e.claim for e in ev if e.kind == "assumption"][:5],
        "unknowns": [e.claim for e in ev if e.kind in ("unknown", "conflicting")],
        "blockers": blockers,
        "pending_user_actions": pending + [{"question": q} for q in contract.get("unresolved_questions", [])],
        "next_decision": decisions[0].summary if decisions else None,
        "next_decision_basis": decisions[0].rationale if decisions else None,
        "actions": [{"id": a.id, "type": a.action_type, "status": a.status, "external_ref": a.external_ref,
                     "sandbox": a.connector == "sandbox_publisher"} for a in actions],
    }


def to_markdown(c: dict[str, Any]) -> str:
    p = c["progress"]
    lines = [f"# Báo cáo Mission ({c['data_label']})", "",
             f"- Trạng thái: **{c['mission_status']}**; tasks: {p['task_counts']}",
             f"- Mục tiêu: {_vnd(p['target_minor'])} (cách hiểu: {p['target_interpretation']})",
             f"- Doanh thu tổng đã đối soát (fixture): {_vnd(p['gross_revenue_verified_minor'])}", "",
             "## Kết quả đã xác minh"] + [f"- {v['claim']} — nguồn {v['source']}" for v in c["verified_results"]] + \
            ["", "## Ước tính (CHƯA xác minh)"] + [f"- {v['claim']}" for v in c["estimates_not_verified"]] + \
            ["", "## Ngân sách"] + [f"- {b['category']}: hạn mức {_vnd(b['limit'])}, giữ chỗ {_vnd(b['reserved'])}, "
                                    f"cam kết {_vnd(b['committed'])}, đã đối soát {_vnd(b['settled'])}, còn {_vnd(b['available'])}"
                                    for b in c["budget"]] + \
            ["", "## Giả định"] + [f"- {a}" for a in c["assumptions"]] + \
            ["", "## Nút thắt"] + [f"- {b['task']}: {b['status']} ({b['reason']})" for b in c["blockers"]] + \
            ["", "## Cần người dùng xử lý"] + [f"- {x}" for x in c["pending_user_actions"]] + \
            ["", f"## Quyết định tiếp theo\n{c['next_decision']}\n\nCăn cứ: {c['next_decision_basis']}"]
    return "\n".join(lines)


def create_report(s: Session, m: Mission, period_key: str, kind: str) -> Report | None:
    existing = s.scalar(select(Report).where(Report.mission_id == m.id, Report.period_key == period_key))
    if existing:
        return existing
    content = build_report_content(s, m)
    content["markdown"] = to_markdown(content)
    r = Report(workspace_id=m.workspace_id, mission_id=m.id, period_key=period_key, kind=kind, content=content,
               delivery_status="not_sent_channel_not_configured")
    sp = s.begin_nested()
    try:
        s.add(r)
        s.flush()
        sp.commit()
    except IntegrityError:  # concurrent scheduler instance already created it
        sp.rollback()
        return s.scalar(select(Report).where(Report.mission_id == m.id, Report.period_key == period_key))
    return r


def run_due_reports(s: Session, now_utc: datetime | None = None) -> list[str]:
    now_utc = now_utc or datetime.now(timezone.utc)
    created = []
    for m in s.scalars(select(Mission).where(Mission.status.in_(["active", "paused"]))):
        contract = s.scalar(select(MissionVersion.contract).where(MissionVersion.mission_id == m.id,
                                                                  MissionVersion.version == m.current_version)) or {}
        sched = contract.get("reporting_schedule", {})
        tz = ZoneInfo(sched.get("timezone", "Asia/Ho_Chi_Minh"))
        local = now_utc.astimezone(tz)
        hour = int(sched.get("cron", "0 8 * * *").split()[1])
        if local.hour >= hour:
            key = f"daily:{local.date().isoformat()}"
            if not s.scalar(select(Report.id).where(Report.mission_id == m.id, Report.period_key == key)):
                create_report(s, m, key, "scheduled")
                created.append(m.id)
    return created
