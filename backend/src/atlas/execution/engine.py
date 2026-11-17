"""Durable task execution engine (DB-leased). Used directly by the local worker and wrapped by Temporal
activities when Temporal is configured. Progress is persisted per task in PostgreSQL; a crashed worker's
lease expires and another worker resumes from the last committed task."""
from __future__ import annotations

import logging
import time
from datetime import timedelta
from typing import Any

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session, aliased

from atlas.actions import gateway
from atlas.agents.base import AgentContext, AgentResult, LimitExceeded, ToolBox, ToolPermissionDenied
from atlas.agents.specialists import AGENTS, fixture_tools
from atlas.artifacts.store import save_artifact
from atlas.capabilities.registry import TEAM_LIMITS, limits_for, spec
from atlas.config import get_settings
from atlas.db import SessionLocal, utcnow
from atlas.models import (Action, AgentRun, Evaluation, Evidence, Mission, MissionVersion, Report, Task,
                          TaskDependency)
from atlas.reporting.reports import create_report
from atlas.security import audit
from atlas.telemetry import span

log = logging.getLogger("atlas.engine")
TERMINAL = ("completed", "failed", "cancelled")


def _runnable_query(mission_id: str | None):
    now = utcnow()
    Dep = aliased(Task)
    dep_task = (select(TaskDependency.task_id).join(Dep, Dep.id == TaskDependency.depends_on_id)
                .where(Dep.status != "completed").correlate(None))
    q = (select(Task.id).join(Mission, Mission.id == Task.mission_id)
         .where(Mission.status == "active", Task.id.not_in(dep_task),
                or_(and_(Task.status == "planned", or_(Task.lease_until.is_(None), Task.lease_until < now)),
                    and_(Task.status == "running", Task.lease_until < now)))
         .order_by(Task.created_at))
    if mission_id:
        q = q.where(Task.mission_id == mission_id)
    return q


def claim_next(s: Session, worker_id: str, mission_id: str | None = None) -> str | None:
    for tid in s.scalars(_runnable_query(mission_id).limit(10)).all():
        now = utcnow()
        res = s.execute(update(Task).where(Task.id == tid,
                                           or_(and_(Task.status == "planned", or_(Task.lease_until.is_(None), Task.lease_until < now)),
                                               and_(Task.status == "running", Task.lease_until < now)))
                        .values(status="running", lease_owner=worker_id, attempts=Task.attempts + 1,
                                lease_until=now + timedelta(seconds=get_settings().lease_seconds), updated_at=now))
        s.commit()
        if res.rowcount == 1:
            return tid
    return None


def _upstream(s: Session, task: Task) -> dict[str, dict[str, Any]]:
    rows = s.execute(select(Task.key, Task.output).where(Task.plan_id == task.plan_id, Task.status == "completed")).all()
    return {k: (o or {}) for k, o in rows}


def _tool_registry(s: Session, task: Task, mission: Mission, worker_id: str) -> dict[str, Any]:
    reg = fixture_tools()

    def prepare_or_execute(connector: str, action_type: str, payload: dict[str, Any], cost_minor: int) -> dict[str, Any]:
        a = s.scalar(select(Action).where(Action.task_id == task.id).order_by(Action.created_at.desc()))
        if a is None or a.status in ("rejected", "cancelled", "failed"):
            if a is not None and a.status == "rejected":
                return {"id": a.id, "status": a.status, "error": a.error, "external_ref": None}
            b_cat = ("ads" if cost_minor > 2_000_000 else "external_services") if cost_minor else None
            a = gateway.prepare_action(s, mission, task.id, connector, action_type, payload, cost_minor, f"agent:{worker_id}",
                                       budget_category=b_cat)
            s.commit()
        if a.status in ("approved", "executing", "unknown"):
            try:
                a = gateway.execute(s, a.id, f"worker:{worker_id}")
            except gateway.ApprovalInvalid:
                s.refresh(a)
        return {"id": a.id, "status": a.status, "error": a.error, "external_ref": a.external_ref}

    def build_report() -> dict[str, Any]:
        r = create_report(s, mission, f"final:{task.plan_id}", "final")
        s.flush()
        return {"id": r.id, "markdown": r.content["markdown"]}

    def live_web_fetch(url: str) -> dict[str, Any]:
        from atlas.integrations.connectors import PublicHttpReadOnlyConnector
        return PublicHttpReadOnlyConnector().fetch_json_or_text(url)

    def kpi_ledger_read() -> dict[str, Any]:
        from atlas.analytics_engine import analyze_business_kpis
        from atlas.models import BusinessKPIEvent
        events = s.scalars(select(BusinessKPIEvent).where(BusinessKPIEvent.mission_id == mission.id)).all()
        if not events:
            return {"count": 0, "summary": None}
        return {"count": len(events), "summary": analyze_business_kpis(list(events))}

    def kpi_ledger_closed_loop(summary_data: dict[str, Any]) -> dict[str, Any]:
        from atlas.analytics_engine import closed_loop_replan
        res = closed_loop_replan(s, mission, summary_data)
        s.flush()
        return res

    reg["gateway.prepare_or_execute"] = prepare_or_execute
    reg["report.build"] = build_report
    reg["live_web.fetch"] = live_web_fetch
    reg["kpi_ledger.read"] = kpi_ledger_read
    reg["kpi_ledger.closed_loop"] = kpi_ledger_closed_loop
    return reg


def run_task(task_id: str, worker_id: str) -> str:
    s = SessionLocal()
    try:
        return _run_task(s, task_id, worker_id)
    finally:
        s.close()


def _run_task(s: Session, task_id: str, worker_id: str) -> str:
    task = s.get(Task, task_id)
    mission = s.get(Mission, task.mission_id)
    contract = s.scalar(select(MissionVersion.contract).where(MissionVersion.mission_id == mission.id,
                                                              MissionVersion.version == mission.current_version))
    cap = spec(task.capability)
    run = AgentRun(task_id=task.id, mission_id=mission.id, capability=cap["name"], capability_version=cap["version"],
                   provider="pending", worker_id=worker_id, attempt=task.attempts)
    s.add(run)
    s.commit()
    tools = ToolBox(allowed=set(cap["tools"]), registry=_tool_registry(s, task, mission, worker_id), limits=limits_for(task.capability))
    ctx = AgentContext(mission_id=mission.id, workspace_id=mission.workspace_id, task_id=task.id, task_key=task.key,
                       contract=contract, task_input=dict(task.input or {}), upstream=_upstream(s, task), tools=tools,
                       is_demo=mission.is_demo)
    if get_settings().fault_sleep_seconds:
        time.sleep(get_settings().fault_sleep_seconds)  # test hook: widen crash window
    err: str | None = None
    result: AgentResult | None = None
    retryable = True
    with span("agent.run", capability=cap["name"], task=task.key, mission=mission.id) as sp_rec:
        try:
            result = AGENTS[task.capability](ctx)
        except (ToolPermissionDenied, LimitExceeded) as e:
            err, retryable = f"{type(e).__name__}: {e}", False
        except gateway.RetryableActionError as e:
            err = f"retryable external error: {e}"
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            log.exception("task %s failed", task.key)
        sp_rec["attrs"]["outcome"] = result.status if result else "error"
    s.refresh(task)
    s.refresh(mission)
    run.finished_at = utcnow()
    run.usage = {**(result.usage if result else {}), "tool_calls": len(tools.calls), "denied_tools": tools.denied}
    if task.lease_owner != worker_id:  # lost lease to another worker: discard, do not double-write
        run.status, run.error = "abandoned", "lease lost"
        s.commit()
        return "abandoned"
    if result is None:
        run.status, run.error = "failed", err
        if retryable and task.attempts < task.max_attempts:
            task.status, task.error = "planned", err
            task.lease_until = utcnow() + timedelta(seconds=2 ** task.attempts)  # backoff (not-before)
        else:
            task.status, task.error = "failed", err
            audit(s, mission.workspace_id, f"worker:{worker_id}", "task.dead_letter", {"task": task.key, "error": err}, mission.id)
        task.lease_owner = None
        s.commit()
        return task.status
    run.provider, run.limitations, run.next_steps = result.provider, result.limitations, result.next_steps
    run.status = "succeeded" if result.status in ("completed", "waiting_approval", "revision_requested") else result.status
    for e in result.evidence:
        kind = e.kind
        if kind == "verified_fact" and e.source_type == "agent_inference":
            kind = "assumption"  # agent-authored statements are never evidence of fact
        s.add(Evidence(workspace_id=mission.workspace_id, mission_id=mission.id, task_id=task.id, claim=e.claim, kind=kind,
                       source=e.source, source_type=e.source_type, scope=e.scope, value=e.value, is_demo=e.is_demo,
                       untrusted_flags=e.untrusted_flags))
    av_id = None
    for art in result.artifacts:
        av_id = save_artifact(s, workspace_id=mission.workspace_id, mission_id=mission.id, task_id=task.id, kind=art.kind,
                              title=art.title, content=art.content, is_demo=art.is_demo).id
    task.output = result.output
    task.lease_owner, task.lease_until = None, None
    if mission.status == "cancelled":
        task.status = "cancelled"
    elif result.status == "completed":
        task.status, task.error, task.blocked_reason = "completed", None, None
    elif result.status == "waiting_approval":
        task.status, task.blocked_reason = "waiting_approval", result.blocked_reason
    elif result.status == "blocked":
        task.status, task.blocked_reason = "blocked", result.blocked_reason
    elif result.status == "revision_requested":
        _handle_revision(s, task, result, mission)
    else:
        task.status, task.error = "failed", result.blocked_reason
    if task.capability == "review":
        content_task = s.scalar(select(Task).where(Task.plan_id == task.plan_id, Task.key == "content"))
        s.add(Evaluation(workspace_id=mission.workspace_id, mission_id=mission.id, task_id=content_task.id if content_task else None,
                         evaluator=result.output.get("evaluator", "deterministic_v1"), verdict=result.output["verdict"],
                         scores=result.output.get("scores", {}), findings=result.output.get("findings", [])))
    audit(s, mission.workspace_id, f"worker:{worker_id}", "task.finished", {"task": task.key, "status": task.status}, mission.id)
    _maybe_complete_mission(s, mission)
    s.commit()
    return task.status


def _handle_revision(s: Session, review_task: Task, result: AgentResult, mission: Mission) -> None:
    content_task = s.scalar(select(Task).where(Task.plan_id == review_task.plan_id, Task.key == "content"))
    rev = int((content_task.input or {}).get("revision", 0))
    if rev >= TEAM_LIMITS["max_revisions"]:
        review_task.status = "blocked"
        review_task.blocked_reason = "Vượt số lần sửa tối đa; cần người dùng xem xét (replanning trigger)."
        audit(s, mission.workspace_id, "engine", "replanning.triggered", {"reason": "max_revisions"}, mission.id)
        return
    inp = {k: v for k, v in (content_task.input or {}).items() if k != "force_draft"}
    content_task.input = {**inp, "revision": rev + 1, "revision_feedback": result.output.get("findings", [])}
    content_task.status = "planned"
    review_task.status = "planned"


def _maybe_complete_mission(s: Session, mission: Mission) -> None:
    s.flush()
    statuses = s.scalars(select(Task.status).where(Task.mission_id == mission.id)).all()
    if statuses and all(st == "completed" for st in statuses) and mission.status == "active":
        mission.status = "completed"
        audit(s, mission.workspace_id, "engine", "mission.completed", {}, mission.id)


def on_action_decided(s: Session, action: Action) -> None:
    """Approval/rejection resumes the waiting task (worker will execute through the gateway)."""
    if action.task_id:
        t = s.get(Task, action.task_id)
        if t and t.status == "waiting_approval":
            if action.status == "approved":
                t.status, t.lease_until = "planned", None
            elif action.status == "rejected":
                t.status, t.blocked_reason = "blocked", "Action bị từ chối; cần chỉnh nội dung hoặc lập lại kế hoạch"


def run_until_idle(worker_id: str, mission_id: str | None = None, max_tasks: int = 100) -> int:
    n = 0
    while n < max_tasks:
        s = SessionLocal()
        try:
            tid = claim_next(s, worker_id, mission_id)
        finally:
            s.close()
        if not tid:
            break
        run_task(tid, worker_id)
        n += 1
    return n


def mission_terminal(mission_id: str) -> bool:
    s = SessionLocal()
    try:
        return s.get(Mission, mission_id).status in ("completed", "cancelled", "failed")
    finally:
        s.close()
