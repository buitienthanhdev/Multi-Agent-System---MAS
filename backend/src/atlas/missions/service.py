"""Mission lifecycle service (state machine, versioning, outbox)."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from atlas.actions import gateway
from atlas.db import utcnow
from atlas.missions.compiler import NEVER_IMPLIED, MissionContract, compile_mission
from atlas.models import Action, BudgetAccount, Mission, MissionVersion, OutboxEvent, Task
from atlas.planning.planner import create_plan
from atlas.security import audit

TRANSITIONS = {
    "draft": {"active", "cancelled"},
    "active": {"paused", "cancelled", "completed", "failed"},
    "paused": {"active", "cancelled"},
    "completed": set(), "cancelled": set(), "failed": set(),
}


class InvalidTransition(Exception):
    pass


def _transition(m: Mission, to: str) -> None:
    if to not in TRANSITIONS[m.status]:
        raise InvalidTransition(f"{m.status} -> {to} not allowed")
    m.status = to
    m.updated_at = utcnow()


def create_mission(s: Session, workspace_id: str, user_id: str, request: str, is_demo: bool = True) -> Mission:
    contract = compile_mission(request)
    m = Mission(workspace_id=workspace_id, title=request[:120], raw_request=request, status="draft",
                task_type=contract.task_type, is_demo=is_demo, created_by=user_id, current_version=1)
    s.add(m)
    s.flush()
    s.add(MissionVersion(mission_id=m.id, version=1, contract=contract.model_dump(), change_reason="compiled", created_by=user_id))
    audit(s, workspace_id, user_id, "mission.created", {"mission_id": m.id}, m.id)
    return m


def current_contract(s: Session, m: Mission) -> dict[str, Any]:
    return s.scalar(select(MissionVersion.contract).where(MissionVersion.mission_id == m.id,
                                                          MissionVersion.version == m.current_version))


def update_contract(s: Session, m: Mission, user_id: str, changes: dict[str, Any], reason: str,
                    expected_lock_version: int | None = None) -> MissionVersion:
    if expected_lock_version is not None and expected_lock_version != m.lock_version:
        raise InvalidTransition("stale mission version (optimistic concurrency)")
    if m.status in ("completed", "cancelled", "failed"):
        raise InvalidTransition("mission is terminal")
    new = {**current_contract(s, m), **changes}
    granted = set(new.get("permitted_actions", [])) - set(current_contract(s, m).get("permitted_actions", []))
    MissionContract.model_validate(new)
    m.current_version += 1
    mv = MissionVersion(mission_id=m.id, version=m.current_version, contract=new, change_reason=reason, created_by=user_id)
    s.add(mv)
    audit(s, m.workspace_id, user_id, "mission.contract_changed",
          {"version": m.current_version, "fields": list(changes), "newly_granted": sorted(granted),
           "high_risk_grants": sorted(granted & set(NEVER_IMPLIED))}, m.id)
    return mv


def activate(s: Session, m: Mission, user_id: str) -> Mission:
    contract = current_contract(s, m)
    _transition(m, "active")
    budget = (contract.get("budget") or {}).get("amount_minor", 0)
    cur = (contract.get("budget") or {}).get("currency", "VND")
    if not s.scalar(select(BudgetAccount).where(BudgetAccount.mission_id == m.id)):
        # Total account + sub-accounts. Sub-account limits are explicit config (assumption, documented).
        s.add(BudgetAccount(workspace_id=m.workspace_id, mission_id=m.id, category="total", currency=cur, limit_minor=budget))
        s.add(BudgetAccount(workspace_id=m.workspace_id, mission_id=m.id, category="ads", currency=cur, limit_minor=budget * 7 // 10))
        s.add(BudgetAccount(workspace_id=m.workspace_id, mission_id=m.id, category="external_services", currency=cur,
                            limit_minor=budget * 2 // 10))
        s.add(BudgetAccount(workspace_id=m.workspace_id, mission_id=m.id, category="model_tools", currency=cur,
                            limit_minor=budget - budget * 7 // 10 - budget * 2 // 10))
        create_plan(s, m, contract, user_id)
    s.add(OutboxEvent(topic="mission.started", dedupe_key=f"mission.started:{m.id}", payload={"mission_id": m.id}))
    audit(s, m.workspace_id, user_id, "mission.activated", {}, m.id)
    return m


def pause(s: Session, m: Mission, user_id: str) -> Mission:
    _transition(m, "paused")
    audit(s, m.workspace_id, user_id, "mission.paused", {}, m.id)
    return m


def resume(s: Session, m: Mission, user_id: str) -> Mission:
    _transition(m, "active")
    s.add(OutboxEvent(topic="mission.nudge", dedupe_key=f"mission.nudge:{m.id}:{utcnow().isoformat()}", payload={"mission_id": m.id}))
    audit(s, m.workspace_id, user_id, "mission.resumed", {}, m.id)
    return m


def cancel(s: Session, m: Mission, user_id: str) -> dict[str, Any]:
    _transition(m, "cancelled")
    s.execute(update(Task).where(Task.mission_id == m.id, Task.status.in_(["planned", "blocked", "waiting_approval"]))
              .values(status="cancelled"))
    stops = []
    for a in s.scalars(select(Action).where(Action.mission_id == m.id)):
        if a.status in ("prepared", "awaiting_approval", "approved"):
            a.status = "cancelled"
        elif a.status == "succeeded":
            stops.append(gateway.request_stop(s, a, user_id))  # compensating action, verified or 'unconfirmed'
        elif a.status in ("executing", "unknown"):
            stops.append({"action_id": a.id, "stop": "unconfirmed_outcome_unknown"})
    audit(s, m.workspace_id, user_id, "mission.cancelled", {"stops": stops}, m.id)
    return {"mission_id": m.id, "status": m.status, "external_stops": stops}
