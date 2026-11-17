"""HTTP API (FastAPI). Every object access is checked against the caller's workspace role."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Iterator

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from atlas.actions import gateway
from atlas.artifacts.store import LocalObjectStore, sign_url, verify_signature
from atlas.budgets.ledger import summary
from atlas.capabilities.registry import CAPABILITIES, TEAM_LIMITS, evaluation_stats
from atlas.config import get_settings
from atlas.db import SessionLocal, create_all, session_scope
from atlas.execution.engine import on_action_decided
from atlas.missions import service
from atlas.missions.compiler import compile_mission
from atlas.models import (Action, AgentRun, Approval, Artifact, ArtifactVersion, AuditEvent, BudgetAccount, BudgetEntry,
                          BusinessKPIEvent, Connector, Decision, Evaluation, Evidence, ExternalReceipt, Mission,
                          MissionVersion, Plan, Report, Role, Task, TaskDependency, User, Workspace)
from atlas.reporting.reports import create_report
from atlas.security import hash_token
from atlas.seed import seed

@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    create_all()
    with session_scope() as s:
        seed(s)
    yield


app = FastAPI(title="ATLAS API", version="0.1.0", lifespan=_lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def db() -> Iterator[Session]:
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


def current_user(authorization: str = Header(default=""), s: Session = Depends(db)) -> User:
    token = authorization.removeprefix("Bearer ").strip()
    u = s.scalar(select(User).where(User.api_token_hash == hash_token(token))) if token else None
    if not u:
        raise HTTPException(401, "invalid or missing token")
    return u


WRITE_ROLES = {"owner", "operator", "approver"}


def require_role(s: Session, user: User, workspace_id: str, write: bool = False) -> str:
    r = s.scalar(select(Role).where(Role.workspace_id == workspace_id, Role.user_id == user.id))
    if not r:
        raise HTTPException(404, "not found")  # do not leak existence across workspaces
    if write and r.role not in WRITE_ROLES:
        raise HTTPException(403, "insufficient role")
    return r.role


def load_mission(s: Session, user: User, mission_id: str, write: bool = False) -> Mission:
    m = s.get(Mission, mission_id)
    if not m:
        raise HTTPException(404, "not found")
    require_role(s, user, m.workspace_id, write)
    return m


def row(o: Any, exclude: tuple[str, ...] = ()) -> dict[str, Any]:
    return {c.name: getattr(o, c.name) for c in o.__table__.columns if c.name not in exclude}


@app.get("/api/health")
def health() -> dict[str, Any]:
    st = get_settings()
    return {"status": "ok", "llm": st.llm_model, "llm_mode": "template(no-llm)" if st.llm_model == "template" else "model",
            "temporal": "configured" if st.temporal_address else "not_configured(local engine)",
            "langfuse": "configured" if st.langfuse_enabled else "not_configured",
            "database": st.database_url.split(":")[0]}


@app.get("/api/me")
def me(user: User = Depends(current_user), s: Session = Depends(db)) -> dict[str, Any]:
    roles = s.execute(select(Role, Workspace).join(Workspace, Workspace.id == Role.workspace_id).where(Role.user_id == user.id)).all()
    return {"id": user.id, "email": user.email, "name": user.name,
            "workspaces": [{"id": w.id, "name": w.name, "role": r.role} for r, w in roles]}


class CompileIn(BaseModel):
    request: str


@app.post("/api/missions/compile")
def compile_preview(body: CompileIn, user: User = Depends(current_user)) -> dict[str, Any]:
    return compile_mission(body.request).model_dump()


class MissionIn(BaseModel):
    workspace_id: str
    request: str
    is_demo: bool = True


@app.post("/api/missions", status_code=201)
def create(body: MissionIn, user: User = Depends(current_user), s: Session = Depends(db)) -> dict[str, Any]:
    require_role(s, user, body.workspace_id, write=True)
    m = service.create_mission(s, body.workspace_id, user.id, body.request, body.is_demo)
    s.commit()
    return mission_detail(m.id, user, s)


@app.get("/api/missions")
def list_missions(workspace_id: str, user: User = Depends(current_user), s: Session = Depends(db)) -> list[dict[str, Any]]:
    require_role(s, user, workspace_id)
    return [row(m) for m in s.scalars(select(Mission).where(Mission.workspace_id == workspace_id).order_by(Mission.created_at.desc()))]


@app.get("/api/missions/{mission_id}")
def mission_detail(mission_id: str, user: User = Depends(current_user), s: Session = Depends(db)) -> dict[str, Any]:
    m = load_mission(s, user, mission_id)
    versions = s.scalars(select(MissionVersion).where(MissionVersion.mission_id == m.id).order_by(MissionVersion.version)).all()
    return {**row(m), "contract": service.current_contract(s, m),
            "versions": [{"version": v.version, "change_reason": v.change_reason, "created_at": v.created_at} for v in versions]}


class ContractPatch(BaseModel):
    changes: dict[str, Any]
    reason: str
    lock_version: int


@app.patch("/api/missions/{mission_id}/contract")
def patch_contract(mission_id: str, body: ContractPatch, user: User = Depends(current_user), s: Session = Depends(db)) -> dict[str, Any]:
    m = load_mission(s, user, mission_id, write=True)
    if any(k in body.changes for k in ("permitted_actions", "budget", "approval_policy")):
        if require_role(s, user, m.workspace_id) != "owner":
            raise HTTPException(403, "only owner can change permissions/budget/approval policy")
    try:
        service.update_contract(s, m, user.id, body.changes, body.reason, body.lock_version)
        s.commit()
    except (service.InvalidTransition, StaleDataError) as e:
        s.rollback()
        raise HTTPException(409, str(e))
    except ValueError as e:
        s.rollback()
        raise HTTPException(422, str(e))
    return mission_detail(m.id, user, s)


@app.post("/api/missions/{mission_id}/{op}")
def lifecycle(mission_id: str, op: str, user: User = Depends(current_user), s: Session = Depends(db)) -> dict[str, Any]:
    if op not in ("activate", "pause", "resume", "cancel"):
        raise HTTPException(404, "unknown operation")
    m = load_mission(s, user, mission_id, write=True)
    try:
        extra = getattr(service, op)(s, m, user.id)
        s.commit()
    except service.InvalidTransition as e:
        s.rollback()
        raise HTTPException(409, str(e))
    out = mission_detail(m.id, user, s)
    if isinstance(extra, dict):
        out["cancel_result"] = extra
    return out


@app.get("/api/missions/{mission_id}/plan")
def plan(mission_id: str, user: User = Depends(current_user), s: Session = Depends(db)) -> dict[str, Any]:
    m = load_mission(s, user, mission_id)
    p = s.scalar(select(Plan).where(Plan.mission_id == m.id).order_by(Plan.version.desc()))
    if not p:
        return {"plan": None, "tasks": [], "dependencies": [], "decisions": []}
    tasks = s.scalars(select(Task).where(Task.plan_id == p.id).order_by(Task.created_at)).all()
    deps = s.scalars(select(TaskDependency).where(TaskDependency.task_id.in_([t.id for t in tasks]))).all()
    decisions = s.scalars(select(Decision).where(Decision.mission_id == m.id)).all()
    return {"plan": row(p), "tasks": [row(t) for t in tasks],
            "dependencies": [{"task_id": d.task_id, "depends_on_id": d.depends_on_id} for d in deps],
            "decisions": [row(d) for d in decisions]}


@app.get("/api/missions/{mission_id}/runs")
def runs(mission_id: str, user: User = Depends(current_user), s: Session = Depends(db)) -> list[dict[str, Any]]:
    m = load_mission(s, user, mission_id)
    return [row(r) for r in s.scalars(select(AgentRun).where(AgentRun.mission_id == m.id).order_by(AgentRun.started_at))]


@app.get("/api/missions/{mission_id}/artifacts")
def artifacts(mission_id: str, user: User = Depends(current_user), s: Session = Depends(db)) -> list[dict[str, Any]]:
    m = load_mission(s, user, mission_id)
    out = []
    for a in s.scalars(select(Artifact).where(Artifact.mission_id == m.id).order_by(Artifact.created_at)):
        vs = s.scalars(select(ArtifactVersion).where(ArtifactVersion.artifact_id == a.id).order_by(ArtifactVersion.version)).all()
        out.append({**row(a), "versions": [{**row(v), "download_url": sign_url(v.id)} for v in vs]})
    return out


@app.get("/api/files/{version_id}", response_class=PlainTextResponse)
def file(version_id: str, exp: int = Query(...), sig: str = Query(...), s: Session = Depends(db)) -> str:
    if not verify_signature(version_id, exp, sig):
        raise HTTPException(403, "invalid or expired signature")
    v = s.get(ArtifactVersion, version_id)
    if not v:
        raise HTTPException(404, "not found")
    return LocalObjectStore().get(v.storage_uri).decode("utf-8")


@app.get("/api/missions/{mission_id}/evidence")
def evidence(mission_id: str, user: User = Depends(current_user), s: Session = Depends(db)) -> list[dict[str, Any]]:
    m = load_mission(s, user, mission_id)
    return [row(e) for e in s.scalars(select(Evidence).where(Evidence.mission_id == m.id).order_by(Evidence.collected_at))]


@app.get("/api/missions/{mission_id}/evaluations")
def evaluations(mission_id: str, user: User = Depends(current_user), s: Session = Depends(db)) -> list[dict[str, Any]]:
    m = load_mission(s, user, mission_id)
    return [row(e) for e in s.scalars(select(Evaluation).where(Evaluation.mission_id == m.id).order_by(Evaluation.created_at))]


@app.get("/api/missions/{mission_id}/actions")
def actions(mission_id: str, user: User = Depends(current_user), s: Session = Depends(db)) -> list[dict[str, Any]]:
    m = load_mission(s, user, mission_id)
    out = []
    for a in s.scalars(select(Action).where(Action.mission_id == m.id).order_by(Action.created_at)):
        aps = s.scalars(select(Approval).where(Approval.action_id == a.id)).all()
        rcs = s.scalars(select(ExternalReceipt).where(ExternalReceipt.action_id == a.id)).all()
        out.append({**row(a), "approvals": [row(x) for x in aps], "receipts": [row(x) for x in rcs]})
    return out


class DecisionIn(BaseModel):
    decision: str
    payload_hash: str
    comment: str = ""


@app.post("/api/actions/{action_id}/decide")
def decide(action_id: str, body: DecisionIn, user: User = Depends(current_user), s: Session = Depends(db)) -> dict[str, Any]:
    a = s.get(Action, action_id)
    if not a:
        raise HTTPException(404, "not found")
    require_role(s, user, a.workspace_id)
    if body.decision not in ("approved", "rejected"):
        raise HTTPException(422, "decision must be approved|rejected")
    try:
        gateway.decide(s, a, user.id, body.decision, body.payload_hash, body.comment)
        on_action_decided(s, a)
        from atlas.models import OutboxEvent
        from atlas.db import utcnow
        s.add(OutboxEvent(topic="mission.nudge", dedupe_key=f"nudge:{a.id}:{utcnow().isoformat()}", payload={"mission_id": a.mission_id}))
        s.commit()
    except gateway.ApprovalInvalid as e:
        s.rollback()
        raise HTTPException(409, str(e))
    return row(a)


@app.get("/api/missions/{mission_id}/budget")
def budget(mission_id: str, user: User = Depends(current_user), s: Session = Depends(db)) -> dict[str, Any]:
    m = load_mission(s, user, mission_id)
    accts = s.scalars(select(BudgetAccount).where(BudgetAccount.mission_id == m.id)).all()
    entries = s.scalars(select(BudgetEntry).where(BudgetEntry.account_id.in_([a.id for a in accts])).order_by(BudgetEntry.created_at)).all()
    return {"accounts": [summary(a) for a in accts], "entries": [row(e) for e in entries],
            "note": "Chi phí model/tool là ước tính; chi phí quảng cáo chỉ được tính là đã đối soát sau khi có số liệu provider."}


@app.get("/api/missions/{mission_id}/reports")
def reports(mission_id: str, user: User = Depends(current_user), s: Session = Depends(db)) -> list[dict[str, Any]]:
    m = load_mission(s, user, mission_id)
    return [row(r) for r in s.scalars(select(Report).where(Report.mission_id == m.id).order_by(Report.created_at.desc()))]


@app.post("/api/missions/{mission_id}/reports")
def report_now(mission_id: str, user: User = Depends(current_user), s: Session = Depends(db)) -> dict[str, Any]:
    m = load_mission(s, user, mission_id, write=True)
    from atlas.db import utcnow
    r = create_report(s, m, f"manual:{utcnow().isoformat()}", "event")
    s.commit()
    return row(r)


@app.get("/api/missions/{mission_id}/audit")
def audit_log(mission_id: str, user: User = Depends(current_user), s: Session = Depends(db)) -> list[dict[str, Any]]:
    m = load_mission(s, user, mission_id)
    return [row(e) for e in s.scalars(select(AuditEvent).where(AuditEvent.mission_id == m.id).order_by(AuditEvent.created_at))]


@app.get("/api/connectors")
def connectors(workspace_id: str, user: User = Depends(current_user), s: Session = Depends(db)) -> list[dict[str, Any]]:
    require_role(s, user, workspace_id)
    import os
    out = []
    for c in s.scalars(select(Connector).where(Connector.workspace_id == workspace_id)):
        d = row(c)
        d["secret_present"] = bool(c.secret_ref and os.getenv(c.secret_ref))  # never return the value
        out.append(d)
    return out


@app.get("/api/capabilities")
def capabilities(user: User = Depends(current_user), s: Session = Depends(db)) -> dict[str, Any]:
    return {"capabilities": CAPABILITIES, "limits": TEAM_LIMITS, "evaluation_stats": evaluation_stats(s)}


@app.post("/api/worker/step")
def worker_step(mission_id: str | None = None, user: User = Depends(current_user), s: Session = Depends(db)) -> dict[str, Any]:
    """Run one cycle of the local worker (for interactive inspection or single-step execution on the dashboard)."""
    from atlas.execution import engine
    from atlas.worker import dispatch_outbox
    if mission_id:
        load_mission(s, user, mission_id, write=True)
    dispatched = dispatch_outbox()
    ran = engine.run_until_idle(f"api-worker:{user.id[:8]}", mission_id=mission_id, max_tasks=10)
    return {"outbox_dispatched": dispatched, "tasks_executed": ran}


@app.get("/api/benchmark")
def benchmark_endpoint(user: User = Depends(current_user)) -> dict[str, Any]:
    from atlas.benchmark import run_benchmark
    return run_benchmark()


@app.get("/api/improvements")
def list_improvements(user: User = Depends(current_user), s: Session = Depends(db)) -> list[dict[str, Any]]:
    from atlas.models import ImprovementCandidate
    return [row(c) for c in s.scalars(select(ImprovementCandidate).order_by(ImprovementCandidate.created_at.desc()))]


@app.post("/api/improvements/propose")
def propose_improvement(user: User = Depends(current_user), s: Session = Depends(db)) -> dict[str, Any]:
    from atlas.improvement import propose_from_failures
    c = propose_from_failures(s)
    if not c:
        raise HTTPException(409, "No rejected/revision evaluations found to derive a candidate from")
    s.commit()
    return row(c)


class AdvanceIn(BaseModel):
    rollout_metrics: dict[str, Any] | None = None


@app.post("/api/improvements/{candidate_id}/advance")
def advance_improvement(candidate_id: str, body: AdvanceIn, user: User = Depends(current_user), s: Session = Depends(db)) -> dict[str, Any]:
    from atlas.improvement import advance
    from atlas.models import ImprovementCandidate
    c = s.get(ImprovementCandidate, candidate_id)
    if not c:
        raise HTTPException(404, "not found")
    try:
        advance(s, c, body.rollout_metrics)
        s.commit()
    except ValueError as e:
        s.rollback()
        raise HTTPException(422, str(e))
    return row(c)


@app.post("/api/demo/reset")
def demo_reset_endpoint(user: User = Depends(current_user)) -> dict[str, Any]:
    from atlas.ops import reset_demo
    ws = reset_demo()
    return {"status": "reset", "workspaces": ws}


class KPIEventIn(BaseModel):
    event_date: str
    period: str  # pre_campaign | campaign
    cohort: str  # treated | control
    channel: str = "direct"
    impressions: int = 0
    clicks: int = 0
    leads: int = 0
    qualified_leads: int = 0
    orders: int = 0
    revenue_minor: int = 0
    cogs_minor: int = 0
    ad_spend_minor: int = 0
    confounder_note: str = ""


class KPIBatchIn(BaseModel):
    events: list[KPIEventIn]


@app.post("/api/missions/{mission_id}/kpis", status_code=201)
def ingest_kpis(mission_id: str, body: KPIBatchIn, user: User = Depends(current_user), s: Session = Depends(db)) -> dict[str, Any]:
    m = load_mission(s, user, mission_id, write=True)
    for ev in body.events:
        s.add(
            BusinessKPIEvent(
                workspace_id=m.workspace_id,
                mission_id=m.id,
                **ev.model_dump(),
            )
        )
    s.commit()
    from atlas.analytics_engine import analyze_business_kpis
    rows = s.scalars(select(BusinessKPIEvent).where(BusinessKPIEvent.mission_id == m.id)).all()
    return {"ingested": len(body.events), "total_rows": len(rows), "summary": analyze_business_kpis(list(rows))}


@app.get("/api/missions/{mission_id}/kpis")
def get_kpis(mission_id: str, user: User = Depends(current_user), s: Session = Depends(db)) -> dict[str, Any]:
    from atlas.analytics_engine import analyze_business_kpis
    m = load_mission(s, user, mission_id)
    rows = s.scalars(select(BusinessKPIEvent).where(BusinessKPIEvent.mission_id == m.id)).all()
    if not rows:
        return {"total_rows": 0, "summary": None}
    return {"total_rows": len(rows), "summary": analyze_business_kpis(list(rows))}


class QuickDispatchIn(BaseModel):
    workspace_id: str
    request: str
    is_demo: bool = True
    fast_mode: bool = True  # when true, runs one immediate worker pass so agents reply right away in chat


@app.post("/api/missions/dispatch", status_code=201)
def quick_dispatch_mission(body: QuickDispatchIn, user: User = Depends(current_user), s: Session = Depends(db)) -> dict[str, Any]:
    """One-step chat dispatch: creates the Mission, activates it (compiling Contract & DAG Plan), and immediately
    runs ready tasks so the AI community starts conversing and producing artifacts right away."""
    from atlas.execution import engine
    from atlas.llm import TemplateProvider, set_provider
    from atlas.worker import dispatch_outbox

    require_role(s, user, body.workspace_id, write=True)
    m = service.create_mission(s, body.workspace_id, user.id, body.request, body.is_demo)
    service.activate(s, m, user.id)
    s.commit()
    mid = m.id

    dispatch_outbox()
    if body.fast_mode and body.is_demo:
        set_provider(TemplateProvider())
        try:
            engine.run_until_idle(f"community:{user.id[:6]}", mission_id=mid, max_tasks=10)
        finally:
            set_provider(None)
    else:
        engine.run_until_idle(f"community:{user.id[:6]}", mission_id=mid, max_tasks=2)
    return mission_detail(mid, user, s)


@app.post("/api/missions/{mission_id}/optimize")
def trigger_closed_loop_optimization(mission_id: str, user: User = Depends(current_user), s: Session = Depends(db)) -> dict[str, Any]:
    from atlas.analytics_engine import analyze_business_kpis, closed_loop_replan
    m = load_mission(s, user, mission_id, write=True)
    rows = s.scalars(select(BusinessKPIEvent).where(BusinessKPIEvent.mission_id == m.id)).all()
    if not rows:
        raise HTTPException(409, "No BusinessKPIEvent rows found for this mission")
    summary_data = analyze_business_kpis(list(rows))
    dec = closed_loop_replan(s, m, summary_data)
    s.commit()
    return dec


