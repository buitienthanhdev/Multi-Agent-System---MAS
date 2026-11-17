"""Canonical business schema. PostgreSQL is the source of truth in production; SQLite is used for local/tests.

Money is always integer minor units (VND has no minor unit, so 1 VND = 1 unit)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (JSON, BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer,
                        String, Text, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column

from atlas.db import Base, new_id, utcnow


def pk() -> Mapped[str]:
    return mapped_column(String(32), primary_key=True, default=new_id)


def ts() -> Mapped[datetime]:
    return mapped_column(DateTime, default=utcnow, nullable=False)


class Workspace(Base):
    __tablename__ = "workspaces"
    id: Mapped[str] = pk()
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = ts()


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = pk()
    email: Mapped[str] = mapped_column(String(320), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    api_token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = ts()


class Role(Base):
    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id"),
                      CheckConstraint("role in ('owner','approver','operator','viewer')", name="ck_role"))
    id: Mapped[str] = pk()
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(20))


class Mission(Base):
    __tablename__ = "missions"
    __table_args__ = (Index("ix_missions_ws_status", "workspace_id", "status"),)
    id: Mapped[str] = pk()
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(300))
    raw_request: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    lock_version: Mapped[int] = mapped_column(Integer, default=1)  # optimistic concurrency
    task_type: Mapped[str] = mapped_column(String(40), default="marketing_growth")
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = ts()
    updated_at: Mapped[datetime] = ts()
    __mapper_args__ = {"version_id_col": lock_version}


class MissionVersion(Base):
    __tablename__ = "mission_versions"
    __table_args__ = (UniqueConstraint("mission_id", "version"),)
    id: Mapped[str] = pk()
    mission_id: Mapped[str] = mapped_column(ForeignKey("missions.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer)
    contract: Mapped[dict[str, Any]] = mapped_column(JSON)
    change_reason: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = ts()


class Plan(Base):
    __tablename__ = "plans"
    __table_args__ = (UniqueConstraint("mission_id", "version"),)
    id: Mapped[str] = pk()
    mission_id: Mapped[str] = mapped_column(ForeignKey("missions.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    options: Mapped[list[Any]] = mapped_column(JSON, default=list)
    chosen_option: Mapped[str] = mapped_column(String(100))
    replanning_triggers: Mapped[list[Any]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[datetime] = ts()


TASK_STATUSES = ("planned", "running", "waiting_approval", "blocked", "completed", "failed", "cancelled")


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (UniqueConstraint("plan_id", "key"),
                      Index("ix_tasks_mission_status", "mission_id", "status"),
                      CheckConstraint("status in ('planned','running','waiting_approval','blocked','completed','failed','cancelled')",
                                      name="ck_task_status"))
    id: Mapped[str] = pk()
    plan_id: Mapped[str] = mapped_column(ForeignKey("plans.id", ondelete="CASCADE"))
    mission_id: Mapped[str] = mapped_column(ForeignKey("missions.id", ondelete="CASCADE"))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(300))
    capability: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="planned")
    input: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    expected_output: Mapped[str] = mapped_column(Text, default="")
    acceptance_criteria: Mapped[list[Any]] = mapped_column(JSON, default=list)
    estimate: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    failure_handling: Mapped[str] = mapped_column(Text, default="")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    lease_owner: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    blocked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = ts()
    updated_at: Mapped[datetime] = ts()


class TaskDependency(Base):
    __tablename__ = "task_dependencies"
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True)
    depends_on_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True)


class AgentRun(Base):
    __tablename__ = "agent_runs"
    id: Mapped[str] = pk()
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    mission_id: Mapped[str] = mapped_column(ForeignKey("missions.id", ondelete="CASCADE"), index=True)
    capability: Mapped[str] = mapped_column(String(100))
    capability_version: Mapped[str] = mapped_column(String(20))
    provider: Mapped[str] = mapped_column(String(100))
    worker_id: Mapped[str] = mapped_column(String(100))
    attempt: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="running")
    usage: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    limitations: Mapped[list[Any]] = mapped_column(JSON, default=list)
    next_steps: Mapped[list[Any]] = mapped_column(JSON, default=list)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = ts()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Capability(Base):
    __tablename__ = "capabilities"
    __table_args__ = (UniqueConstraint("name", "version"),)
    id: Mapped[str] = pk()
    name: Mapped[str] = mapped_column(String(100))
    version: Mapped[str] = mapped_column(String(20))
    spec: Mapped[dict[str, Any]] = mapped_column(JSON)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    implemented: Mapped[bool] = mapped_column(Boolean, default=True)


class Artifact(Base):
    __tablename__ = "artifacts"
    id: Mapped[str] = pk()
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    mission_id: Mapped[str] = mapped_column(ForeignKey("missions.id", ondelete="CASCADE"), index=True)
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True)
    kind: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(300))
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = ts()


class ArtifactVersion(Base):
    __tablename__ = "artifact_versions"
    __table_args__ = (UniqueConstraint("artifact_id", "version"),)
    id: Mapped[str] = pk()
    artifact_id: Mapped[str] = mapped_column(ForeignKey("artifacts.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64))
    storage_uri: Mapped[str] = mapped_column(String(500))
    content_preview: Mapped[str] = mapped_column(Text, default="")
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = ts()


EVIDENCE_KINDS = ("verified_fact", "assumption", "estimate", "unknown", "conflicting")


class Evidence(Base):
    __tablename__ = "evidence"
    __table_args__ = (CheckConstraint("kind in ('verified_fact','assumption','estimate','unknown','conflicting')", name="ck_ev_kind"),
                      CheckConstraint("NOT (kind = 'verified_fact' AND source_type = 'agent_inference')", name="ck_ev_no_agent_fact"),
                      Index("ix_evidence_mission_kind", "mission_id", "kind"))
    id: Mapped[str] = pk()
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    mission_id: Mapped[str] = mapped_column(ForeignKey("missions.id", ondelete="CASCADE"))
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True)
    claim: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(20))
    source: Mapped[str] = mapped_column(String(500))
    source_type: Mapped[str] = mapped_column(String(30))  # fixture|user|connector|agent_inference|computed
    scope: Mapped[str] = mapped_column(String(200), default="")
    value: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    collected_at: Mapped[datetime] = ts()
    valid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    untrusted_flags: Mapped[list[Any]] = mapped_column(JSON, default=list)


class Decision(Base):
    __tablename__ = "decisions"
    id: Mapped[str] = pk()
    mission_id: Mapped[str] = mapped_column(ForeignKey("missions.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(50))
    summary: Mapped[str] = mapped_column(Text)
    rationale: Mapped[str] = mapped_column(Text)
    made_by: Mapped[str] = mapped_column(String(100))
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = ts()


class Policy(Base):
    __tablename__ = "policies"
    __table_args__ = (UniqueConstraint("workspace_id", "name", "version"),)
    id: Mapped[str] = pk()
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(100))
    version: Mapped[int] = mapped_column(Integer, default=1)
    rules: Mapped[dict[str, Any]] = mapped_column(JSON)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = ts()


class BudgetAccount(Base):
    __tablename__ = "budget_accounts"
    __table_args__ = (
        UniqueConstraint("mission_id", "category"),
        CheckConstraint("reserved_minor >= 0 AND committed_minor >= 0 AND settled_minor >= 0", name="ck_budget_nonneg"),
        CheckConstraint("reserved_minor + committed_minor + settled_minor <= limit_minor", name="ck_budget_limit"),
    )
    id: Mapped[str] = pk()
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    mission_id: Mapped[str] = mapped_column(ForeignKey("missions.id", ondelete="CASCADE"))
    category: Mapped[str] = mapped_column(String(50))  # total|ads|external_services|model_tools
    currency: Mapped[str] = mapped_column(String(3))
    limit_minor: Mapped[int] = mapped_column(BigInteger)
    reserved_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    committed_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    settled_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    overrun_minor: Mapped[int] = mapped_column(BigInteger, default=0)  # provider-reported spend beyond commitment
    estimated_untracked_minor: Mapped[int] = mapped_column(BigInteger, default=0)  # e.g. model cost estimates


class BudgetEntry(Base):
    __tablename__ = "budget_entries"
    __table_args__ = (UniqueConstraint("account_id", "idempotency_key"),
                      CheckConstraint("entry_type in ('allocation','reservation','commitment','settlement','release','adjustment','estimate')", name="ck_entry_type"))
    id: Mapped[str] = pk()
    account_id: Mapped[str] = mapped_column(ForeignKey("budget_accounts.id", ondelete="CASCADE"), index=True)
    entry_type: Mapped[str] = mapped_column(String(20))
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    idempotency_key: Mapped[str] = mapped_column(String(200))
    action_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_estimate: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = ts()


ACTION_STATUSES = ("prepared", "awaiting_approval", "approved", "executing", "succeeded", "failed", "unknown", "rejected", "cancelled")


class Action(Base):
    __tablename__ = "actions"
    __table_args__ = (Index("ix_actions_mission_status", "mission_id", "status"),)
    id: Mapped[str] = pk()
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    mission_id: Mapped[str] = mapped_column(ForeignKey("missions.id", ondelete="CASCADE"))
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True)
    connector: Mapped[str] = mapped_column(String(100))
    action_type: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    payload_hash: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)
    status: Mapped[str] = mapped_column(String(30), default="prepared")
    cost_estimate_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    budget_account_id: Mapped[str | None] = mapped_column(ForeignKey("budget_accounts.id"), nullable=True)
    external_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    compensating_action: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lock_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = ts()
    updated_at: Mapped[datetime] = ts()
    __mapper_args__ = {"version_id_col": lock_version}


class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[str] = pk()
    action_id: Mapped[str] = mapped_column(ForeignKey("actions.id", ondelete="CASCADE"), index=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    approver_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    decision: Mapped[str] = mapped_column(String(20))  # approved|rejected
    comment: Mapped[str] = mapped_column(Text, default="")
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = ts()


class ExternalReceipt(Base):
    __tablename__ = "external_receipts"
    __table_args__ = (UniqueConstraint("connector", "external_id"),)
    id: Mapped[str] = pk()
    action_id: Mapped[str] = mapped_column(ForeignKey("actions.id", ondelete="CASCADE"), index=True)
    connector: Mapped[str] = mapped_column(String(100))
    external_id: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(50))
    raw: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    is_sandbox: Mapped[bool] = mapped_column(Boolean, default=True)
    received_at: Mapped[datetime] = ts()


class Evaluation(Base):
    __tablename__ = "evaluations"
    id: Mapped[str] = pk()
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    mission_id: Mapped[str] = mapped_column(ForeignKey("missions.id", ondelete="CASCADE"), index=True)
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True)
    artifact_version_id: Mapped[str | None] = mapped_column(ForeignKey("artifact_versions.id", ondelete="SET NULL"), nullable=True)
    evaluator: Mapped[str] = mapped_column(String(100))
    verdict: Mapped[str] = mapped_column(String(30))  # accepted|revision_requested|rejected|needs_human
    scores: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    findings: Mapped[list[Any]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = ts()


class Report(Base):
    __tablename__ = "reports"
    __table_args__ = (UniqueConstraint("mission_id", "period_key"),)
    id: Mapped[str] = pk()
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    mission_id: Mapped[str] = mapped_column(ForeignKey("missions.id", ondelete="CASCADE"))
    period_key: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(30))  # scheduled|event|final
    content: Mapped[dict[str, Any]] = mapped_column(JSON)
    delivery_status: Mapped[str] = mapped_column(String(50), default="not_sent_channel_not_configured")
    created_at: Mapped[datetime] = ts()


class Connector(Base):
    __tablename__ = "connectors"
    __table_args__ = (UniqueConstraint("workspace_id", "name"),)
    id: Mapped[str] = pk()
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(50))
    mode: Mapped[str] = mapped_column(String(20))  # sandbox|live|not_configured
    secret_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)  # env var NAME, never the value
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    verification: Mapped[str] = mapped_column(String(30), default="not_verified")  # live_tested|mocked|not_configured
    created_at: Mapped[datetime] = ts()


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_ws_created", "workspace_id", "created_at"),)
    id: Mapped[str] = pk()
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    mission_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    actor: Mapped[str] = mapped_column(String(100))
    event_type: Mapped[str] = mapped_column(String(100))
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = ts()


class OutboxEvent(Base):
    """Transactional outbox: written in the same DB transaction as the state change, dispatched later."""
    __tablename__ = "outbox_events"
    __table_args__ = (Index("ix_outbox_status", "status", "available_at"),)
    id: Mapped[str] = pk()
    topic: Mapped[str] = mapped_column(String(100))
    dedupe_key: Mapped[str] = mapped_column(String(200), unique=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|done|dead
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    available_at: Mapped[datetime] = ts()
    created_at: Mapped[datetime] = ts()


class ImprovementCandidate(Base):
    __tablename__ = "improvement_candidates"
    id: Mapped[str] = pk()
    target_type: Mapped[str] = mapped_column(String(30))  # prompt|skill|workflow (never policy/budget/permission)
    target_name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text)
    proposal: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(30), default="candidate")
    results: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source_failures: Mapped[list[Any]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = ts()


class BusinessKPIEvent(Base):
    """Real business telemetry ledger: daily orders, ad spend, conversions, leads, and control-vs-treated region tag."""
    __tablename__ = "business_kpi_events"
    __table_args__ = (Index("ix_kpi_mission_date", "mission_id", "event_date"),)
    id: Mapped[str] = pk()
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    mission_id: Mapped[str] = mapped_column(ForeignKey("missions.id", ondelete="CASCADE"))
    event_date: Mapped[str] = mapped_column(String(20))  # YYYY-MM-DD
    period: Mapped[str] = mapped_column(String(20))  # pre_campaign | campaign
    cohort: Mapped[str] = mapped_column(String(20))  # treated | control
    channel: Mapped[str] = mapped_column(String(60), default="direct")
    impressions: Mapped[int] = mapped_column(Integer, default=0)
    clicks: Mapped[int] = mapped_column(Integer, default=0)
    leads: Mapped[int] = mapped_column(Integer, default=0)
    qualified_leads: Mapped[int] = mapped_column(Integer, default=0)
    orders: Mapped[int] = mapped_column(Integer, default=0)
    revenue_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    cogs_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    ad_spend_minor: Mapped[int] = mapped_column(BigInteger, default=0)
    confounder_note: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = ts()

