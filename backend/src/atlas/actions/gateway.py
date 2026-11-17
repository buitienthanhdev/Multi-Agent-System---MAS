"""Action Gateway: the ONLY path for external side effects.

Pipeline: authorize -> validate -> policy -> approval (bound to payload hash, expiring) -> budget reservation ->
persist 'executing' intent -> connector call with idempotency key -> receipt persistence / reconciliation -> audit.

Retry ownership: the gateway is the single owner of retries for external effects. Callers (engine/Temporal
activities) may re-invoke execute(); it is idempotent and reconciles before any re-send."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from atlas.budgets import ledger
from atlas.config import get_settings
from atlas.db import utcnow
from atlas.integrations.connectors import ConnectorError, ConnectorTimeout, NotConfigured, Receipt, get_connector
from atlas.models import Action, Approval, BudgetAccount, ExternalReceipt, Mission, MissionVersion, Policy, Role
from atlas.policies.engine import DEFAULT_RULES, evaluate_action
from atlas.security import audit, canonical_hash


class GatewayError(Exception):
    pass


class PolicyDenied(GatewayError):
    pass


class ApprovalInvalid(GatewayError):
    pass


class RetryableActionError(GatewayError):
    pass


def _rules(s: Session, workspace_id: str) -> dict[str, Any]:
    p = s.scalar(select(Policy).where(Policy.workspace_id == workspace_id, Policy.name == "default", Policy.active)
                 .order_by(Policy.version.desc()))
    return p.rules if p else DEFAULT_RULES


def _contract(s: Session, m: Mission) -> dict[str, Any]:
    mv = s.scalar(select(MissionVersion).where(MissionVersion.mission_id == m.id, MissionVersion.version == m.current_version))
    return mv.contract if mv else {}


def prepare_action(s: Session, mission: Mission, task_id: str | None, connector: str, action_type: str,
                   payload: dict[str, Any], cost_minor: int, actor: str, budget_category: str | None = None) -> Action:
    ph = canonical_hash({"connector": connector, "action_type": action_type, "payload": payload})
    key = f"{mission.id}:{task_id}:{action_type}:{ph[:16]}"
    existing = s.scalar(select(Action).where(Action.idempotency_key == key))
    if existing:
        return existing
    contract = _contract(s, mission)
    dec = evaluate_action(_rules(s, mission.workspace_id), mission_status=mission.status,
                          permitted_actions=contract.get("permitted_actions", []), action_type=action_type,
                          payload=payload, cost_minor=cost_minor)
    acc_id = None
    if budget_category:
        acc = s.scalar(select(BudgetAccount).where(BudgetAccount.mission_id == mission.id, BudgetAccount.category == budget_category))
        acc_id = acc.id if acc else None
    a = Action(workspace_id=mission.workspace_id, mission_id=mission.id, task_id=task_id, connector=connector,
               action_type=action_type, payload=payload, payload_hash=ph, idempotency_key=key, cost_estimate_minor=cost_minor,
               budget_account_id=acc_id, status="prepared",
               compensating_action="request_stop" if action_type.startswith("publish") else None)
    if not dec.allowed:
        a.status = "rejected"
        a.error = "; ".join(dec.reasons)
    elif dec.requires_approval:
        a.status = "awaiting_approval"
    s.add(a)
    s.flush()
    audit(s, mission.workspace_id, actor, "action.prepared", {"action_id": a.id, "status": a.status,
                                                               "reasons": dec.reasons, "payload_hash": ph}, mission.id)
    return a


def update_payload(s: Session, action: Action, payload: dict[str, Any], actor: str) -> Action:
    if action.status not in ("prepared", "awaiting_approval", "approved"):
        raise GatewayError(f"cannot edit payload in status {action.status}")
    action.payload = payload
    action.payload_hash = canonical_hash({"connector": action.connector, "action_type": action.action_type, "payload": payload})
    action.status = "awaiting_approval"  # previous approvals are bound to the old hash -> invalid
    audit(s, action.workspace_id, actor, "action.payload_changed", {"action_id": action.id, "payload_hash": action.payload_hash},
          action.mission_id)
    return action


def decide(s: Session, action: Action, user_id: str, decision: str, payload_hash: str, comment: str = "") -> Approval:
    role = s.scalar(select(Role).where(Role.workspace_id == action.workspace_id, Role.user_id == user_id))
    if not role or role.role not in ("owner", "approver"):
        raise ApprovalInvalid("user is not an approver in this workspace")
    if action.status != "awaiting_approval":
        raise ApprovalInvalid(f"action is {action.status}, not awaiting_approval")
    if payload_hash != action.payload_hash:
        raise ApprovalInvalid("payload hash mismatch: the payload you reviewed is not the current payload")
    ap = Approval(action_id=action.id, payload_hash=payload_hash, approver_id=user_id, decision=decision, comment=comment,
                  expires_at=utcnow() + timedelta(minutes=get_settings().approval_ttl_minutes))
    s.add(ap)
    action.status = "approved" if decision == "approved" else "rejected"
    action.updated_at = utcnow()
    audit(s, action.workspace_id, user_id, f"action.{decision}", {"action_id": action.id, "payload_hash": payload_hash},
          action.mission_id)
    return ap


def valid_approval(s: Session, action: Action) -> Approval | None:
    return s.scalar(select(Approval).where(Approval.action_id == action.id, Approval.decision == "approved",
                                           Approval.payload_hash == action.payload_hash, Approval.expires_at > utcnow())
                    .order_by(Approval.created_at.desc()))


def _record_success(s: Session, action: Action, r: Receipt, actor: str) -> None:
    if not s.scalar(select(ExternalReceipt).where(ExternalReceipt.connector == action.connector,
                                                  ExternalReceipt.external_id == r.external_id)):
        s.add(ExternalReceipt(action_id=action.id, connector=action.connector, external_id=r.external_id, status=r.status,
                              raw=r.raw, is_sandbox=r.is_sandbox))
    action.status = "succeeded"
    action.external_ref = r.external_id
    action.error = None
    action.updated_at = utcnow()
    if action.budget_account_id and action.cost_estimate_minor:
        ledger.commit(s, action.budget_account_id, action.cost_estimate_minor, action.id, action.id)
        # Settlement waits for provider-reconciled actual cost; sandbox reports actual = r.cost_minor.
        ledger.settle(s, action.budget_account_id, action.cost_estimate_minor, r.cost_minor, action.id, action.id)
    audit(s, action.workspace_id, actor, "action.succeeded", {"action_id": action.id, "external_id": r.external_id,
                                                               "sandbox": r.is_sandbox}, action.mission_id)


def reconcile(s: Session, action: Action, actor: str) -> str:
    """Query the external system by idempotency key before any re-send."""
    conn = get_connector(action.connector)
    try:
        r = conn.lookup(action.idempotency_key)
    except NotConfigured:
        return action.status
    if r is not None:
        _record_success(s, action, r, actor)
        audit(s, action.workspace_id, actor, "action.reconciled", {"action_id": action.id, "found": True}, action.mission_id)
    elif conn.supports_idempotency:
        action.status = "approved"  # confirmed not present remotely -> safe to resend with same key
        audit(s, action.workspace_id, actor, "action.reconciled", {"action_id": action.id, "found": False}, action.mission_id)
    else:
        action.status = "unknown"  # manual reconciliation queue
    return action.status


def execute(s: Session, action_id: str, actor: str) -> Action:
    a = s.get(Action, action_id)
    if a is None:
        raise GatewayError("action not found")
    if a.status == "succeeded":
        return a
    if a.status in ("executing", "unknown"):
        # Previous attempt's outcome unknown (crash/timeout): reconcile first, never blind-retry.
        reconcile(s, a, actor)
        s.commit()
        if a.status != "approved":
            return a
    if a.status != "approved":
        raise ApprovalInvalid(f"action status {a.status} is not executable")
    m = s.get(Mission, a.mission_id)
    if m.status != "active":
        raise PolicyDenied(f"mission is {m.status}; new actions are blocked")
    dec = evaluate_action(_rules(s, a.workspace_id), mission_status=m.status,
                          permitted_actions=_contract(s, m).get("permitted_actions", []), action_type=a.action_type,
                          payload=a.payload, cost_minor=a.cost_estimate_minor)
    if not dec.allowed:
        a.status = "rejected"
        a.error = "; ".join(dec.reasons)
        s.commit()
        raise PolicyDenied(a.error)
    if dec.requires_approval and not valid_approval(s, a):
        a.status = "awaiting_approval"
        a.error = "approval missing, expired, or bound to a different payload"
        audit(s, a.workspace_id, actor, "action.approval_invalid", {"action_id": a.id}, a.mission_id)
        s.commit()
        raise ApprovalInvalid(a.error)
    if a.budget_account_id and a.cost_estimate_minor:
        ledger.reserve(s, a.budget_account_id, a.cost_estimate_minor, a.id, a.id)
    a.status = "executing"
    a.attempts += 1
    a.updated_at = utcnow()
    s.commit()  # durable intent BEFORE external call

    conn = get_connector(a.connector)
    try:
        r = conn.execute(a.action_type, a.payload, a.idempotency_key)
    except ConnectorTimeout as e:
        a.status = "unknown"
        a.error = str(e)
        audit(s, a.workspace_id, actor, "action.outcome_unknown", {"action_id": a.id}, a.mission_id)
        s.commit()
        reconcile(s, a, actor)
        s.commit()
        return a
    except NotConfigured as e:
        a.status = "failed"
        a.error = str(e)
        if a.budget_account_id and a.cost_estimate_minor:
            ledger.release(s, a.budget_account_id, a.cost_estimate_minor, a.id, a.id)
        s.commit()
        return a
    except ConnectorError as e:
        a.error = str(e)
        if e.retryable and a.attempts < 3:
            a.status = "approved"
            s.commit()
            raise RetryableActionError(str(e)) from e
        a.status = "failed"
        if a.budget_account_id and a.cost_estimate_minor:
            ledger.release(s, a.budget_account_id, a.cost_estimate_minor, a.id, a.id)
        audit(s, a.workspace_id, actor, "action.failed", {"action_id": a.id, "error": str(e)}, a.mission_id)
        s.commit()
        return a
    _record_success(s, a, r, actor)
    s.commit()
    return a


def request_stop(s: Session, action: Action, actor: str) -> dict[str, Any]:
    """Compensating action for already-published content. Not a rollback: the content was public."""
    if action.status != "succeeded" or not action.external_ref:
        return {"action_id": action.id, "stop": "not_applicable"}
    try:
        r = get_connector(action.connector).request_stop(action.external_ref)
    except NotConfigured:
        r = None
    verified = r is not None and r.status.startswith("withdrawn")
    audit(s, action.workspace_id, actor, "action.stop_requested", {"action_id": action.id, "verified": verified}, action.mission_id)
    return {"action_id": action.id, "stop": "verified" if verified else "unconfirmed"}
