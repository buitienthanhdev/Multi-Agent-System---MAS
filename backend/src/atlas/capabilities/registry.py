"""Capability Registry + Team Composer."""
from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from atlas.agents.base import AgentLimits
from atlas.models import AgentRun, Capability, Evaluation, Task

CAPABILITIES: list[dict[str, Any]] = [
    {"name": "research", "version": "1.1", "implemented": True, "task_types": ["marketing_growth", "market_research", "general"],
     "tools": ["fixture_web.list", "fixture_web.read", "live_web.fetch"], "permissions": ["research.read_fixture", "research.read_live_web"],
     "input_schema": {"objective": "str"}, "output_schema": {"segments": "list", "hypotheses": "list"},
     "models": ["ollama:gemma4:12b", "template", "any-chat-model"], "cost_hint_minor": 0, "limits": {"max_tool_calls": 10},
     "failure_modes": ["prompt injection in sources", "unverifiable third-party claims"]},
    {"name": "content", "version": "1.1", "implemented": True, "task_types": ["marketing_growth", "content_media"],
     "tools": [], "permissions": ["content.draft"], "input_schema": {"brief": "dict"}, "output_schema": {"draft": "str"},
     "models": ["ollama:gemma4:12b", "template", "any-chat-model"], "cost_hint_minor": 0, "limits": {"max_tool_calls": 2},
     "failure_modes": ["invented specs/warranty", "missing demo label"]},
    {"name": "review", "version": "1.1", "implemented": True, "task_types": ["*"], "tools": [], "permissions": [],
     "input_schema": {"draft": "str"}, "output_schema": {"verdict": "str"}, "models": ["deterministic+ollama:gemma4:12b"],
     "cost_hint_minor": 0, "limits": {"max_tool_calls": 1}, "failure_modes": ["no semantic judgment without LLM judge"]},
    {"name": "analytics", "version": "1.1", "implemented": True, "task_types": ["marketing_growth", "data_analysis"],
     "tools": ["sales_fixture.read", "kpi_ledger.read", "kpi_ledger.closed_loop"], "permissions": ["analytics.read_fixture", "analytics.read_kpi_ledger"], "input_schema": {"mode": "baseline|results"},
     "output_schema": {"gross_revenue_minor": "int"}, "models": ["deterministic_did_parallel_trends"], "cost_hint_minor": 0,
     "limits": {"max_tool_calls": 5}, "failure_modes": ["confusing attribution with causality"]},
    {"name": "publishing", "version": "1.0", "implemented": True, "task_types": ["marketing_growth", "content_media"],
     "tools": ["gateway.prepare_or_execute"], "permissions": ["publish.sandbox"], "input_schema": {"draft": "str"},
     "output_schema": {"action_id": "str"}, "models": ["none"], "cost_hint_minor": 0, "limits": {"max_tool_calls": 2},
     "failure_modes": ["external timeout -> unknown"]},
    {"name": "report", "version": "1.0", "implemented": True, "task_types": ["*"], "tools": ["report.build"],
     "permissions": ["report.generate"], "input_schema": {}, "output_schema": {"report_id": "str"}, "models": ["deterministic"],
     "cost_hint_minor": 0, "limits": {"max_tool_calls": 2}, "failure_modes": []},
    {"name": "media", "version": "1.0", "implemented": True, "task_types": ["content_media", "marketing_growth"], "tools": [],
     "permissions": ["content.draft"], "input_schema": {"prompt": "str"}, "output_schema": {"format": "str"},
     "models": ["svg_wireframe_adapter"], "cost_hint_minor": 0, "limits": {"max_tool_calls": 2},
     "failure_modes": ["external raster/video provider not configured -> returns labeled wireframe only"]},
    {"name": "sales_assistance", "version": "1.0", "implemented": True, "task_types": ["customer_care", "marketing_growth"], "tools": [],
     "permissions": ["content.draft"], "input_schema": {}, "output_schema": {"playbook_ready": "bool"}, "models": ["deterministic"],
     "cost_hint_minor": 0, "limits": {"max_tool_calls": 2}, "failure_modes": ["outbound messaging requires explicit message.send_customer grant"]},
    {"name": "software_engineering", "version": "1.0", "implemented": True, "task_types": ["software", "docs_ops"],
     "tools": [], "permissions": [], "input_schema": {"target_module": "str"},
     "output_schema": {"sandbox_tests_passed": "bool"}, "models": ["sandbox_code_agent"], "cost_hint_minor": 0,
     "limits": {"max_tool_calls": 3},
     "failure_modes": ["produces patch proposal only; never auto-merges"]},
    {"name": "finance_cfo", "version": "1.0", "implemented": True, "task_types": ["finance_accounting", "marketing_growth", "strategy_consulting"],
     "tools": [], "permissions": ["content.draft"], "input_schema": {"objective": "str"}, "output_schema": {"deliverable": "str"},
     "models": ["ollama:gemma4:12b", "template"], "cost_hint_minor": 0, "limits": {"max_tool_calls": 2},
     "failure_modes": ["requires verified accounting ledger for final settlement"]},
    {"name": "legal_counsel", "version": "1.0", "implemented": True, "task_types": ["legal_compliance", "docs_ops", "marketing_growth"],
     "tools": [], "permissions": ["content.draft"], "input_schema": {"objective": "str"}, "output_schema": {"deliverable": "str"},
     "models": ["ollama:gemma4:12b", "template"], "cost_hint_minor": 0, "limits": {"max_tool_calls": 2},
     "failure_modes": ["advisory legal review only; does not replace licensed counsel sign-off"]},
    {"name": "hr_talent", "version": "1.0", "implemented": True, "task_types": ["hr_recruitment", "docs_ops"],
     "tools": [], "permissions": ["content.draft"], "input_schema": {"objective": "str"}, "output_schema": {"deliverable": "str"},
     "models": ["ollama:gemma4:12b", "template"], "cost_hint_minor": 0, "limits": {"max_tool_calls": 2},
     "failure_modes": ["requires human interviewer final hiring decision"]},
    {"name": "supply_chain", "version": "1.0", "implemented": True, "task_types": ["supply_chain_ops", "ecommerce_ops"],
     "tools": [], "permissions": ["content.draft"], "input_schema": {"objective": "str"}, "output_schema": {"deliverable": "str"},
     "models": ["ollama:gemma4:12b", "template"], "cost_hint_minor": 0, "limits": {"max_tool_calls": 2},
     "failure_modes": ["purchase orders require Action Gateway approval"]},
    {"name": "devops_sre", "version": "1.0", "implemented": True, "task_types": ["devops_cloud", "software", "docs_ops"],
     "tools": [], "permissions": ["content.draft"], "input_schema": {"objective": "str"}, "output_schema": {"deliverable": "str"},
     "models": ["ollama:gemma4:12b", "template"], "cost_hint_minor": 0, "limits": {"max_tool_calls": 2},
     "failure_modes": ["never mutates production infrastructure directly"]},
    {"name": "cyber_security", "version": "1.0", "implemented": True, "task_types": ["cybersecurity_audit", "software", "devops_cloud"],
     "tools": [], "permissions": ["content.draft"], "input_schema": {"objective": "str"}, "output_schema": {"deliverable": "str"},
     "models": ["ollama:gemma4:12b", "template"], "cost_hint_minor": 0, "limits": {"max_tool_calls": 2},
     "failure_modes": ["defensive threat modeling and audit only"]},
    {"name": "product_ux", "version": "1.0", "implemented": True, "task_types": ["product_management", "software", "content_media"],
     "tools": [], "permissions": ["content.draft"], "input_schema": {"objective": "str"}, "output_schema": {"deliverable": "str"},
     "models": ["ollama:gemma4:12b", "template"], "cost_hint_minor": 0, "limits": {"max_tool_calls": 2},
     "failure_modes": []},
    {"name": "seo_growth", "version": "1.0", "implemented": True, "task_types": ["seo_organic", "content_media", "marketing_growth"],
     "tools": [], "permissions": ["content.draft"], "input_schema": {"objective": "str"}, "output_schema": {"deliverable": "str"},
     "models": ["ollama:gemma4:12b", "template"], "cost_hint_minor": 0, "limits": {"max_tool_calls": 2},
     "failure_modes": []},
    {"name": "pr_comms", "version": "1.0", "implemented": True, "task_types": ["pr_crisis_comms", "content_media", "customer_care"],
     "tools": [], "permissions": ["content.draft"], "input_schema": {"objective": "str"}, "output_schema": {"deliverable": "str"},
     "models": ["ollama:gemma4:12b", "template"], "cost_hint_minor": 0, "limits": {"max_tool_calls": 2},
     "failure_modes": ["public press release requires Action Gateway approval"]},
    {"name": "data_engineer", "version": "1.0", "implemented": True, "task_types": ["data_engineering", "data_analysis", "software"],
     "tools": [], "permissions": ["content.draft"], "input_schema": {"objective": "str"}, "output_schema": {"deliverable": "str"},
     "models": ["ollama:gemma4:12b", "template"], "cost_hint_minor": 0, "limits": {"max_tool_calls": 2},
     "failure_modes": []},
    {"name": "rd_scientist", "version": "1.0", "implemented": True, "task_types": ["rd_product_lab", "market_research"],
     "tools": [], "permissions": ["content.draft"], "input_schema": {"objective": "str"}, "output_schema": {"deliverable": "str"},
     "models": ["ollama:gemma4:12b", "template"], "cost_hint_minor": 0, "limits": {"max_tool_calls": 2},
     "failure_modes": ["requires physical lab verification before warranty claims"]},
    {"name": "strategy_consultant", "version": "1.0", "implemented": True, "task_types": ["strategy_consulting", "market_research", "marketing_growth"],
     "tools": [], "permissions": ["content.draft"], "input_schema": {"objective": "str"}, "output_schema": {"deliverable": "str"},
     "models": ["ollama:gemma4:12b", "template"], "cost_hint_minor": 0, "limits": {"max_tool_calls": 2},
     "failure_modes": []},
    {"name": "qa_automation", "version": "1.0", "implemented": True, "task_types": ["qa_testing", "software", "devops_cloud"],
     "tools": [], "permissions": ["content.draft"], "input_schema": {"objective": "str"}, "output_schema": {"deliverable": "str"},
     "models": ["ollama:gemma4:12b", "template"], "cost_hint_minor": 0, "limits": {"max_tool_calls": 2},
     "failure_modes": []},
    {"name": "localization_pro", "version": "1.0", "implemented": True, "task_types": ["translation_localization", "content_media"],
     "tools": [], "permissions": ["content.draft"], "input_schema": {"objective": "str"}, "output_schema": {"deliverable": "str"},
     "models": ["ollama:gemma4:12b", "template"], "cost_hint_minor": 0, "limits": {"max_tool_calls": 2},
     "failure_modes": []},
    {"name": "business_analyst", "version": "1.0", "implemented": True, "task_types": ["business_analysis", "product_management", "docs_ops"],
     "tools": [], "permissions": ["content.draft"], "input_schema": {"objective": "str"}, "output_schema": {"deliverable": "str"},
     "models": ["ollama:gemma4:12b", "template"], "cost_hint_minor": 0, "limits": {"max_tool_calls": 2},
     "failure_modes": []},
    {"name": "ecommerce_merch", "version": "1.0", "implemented": True, "task_types": ["ecommerce_ops", "marketing_growth", "content_media"],
     "tools": [], "permissions": ["content.draft"], "input_schema": {"objective": "str"}, "output_schema": {"deliverable": "str"},
     "models": ["ollama:gemma4:12b", "template"], "cost_hint_minor": 0, "limits": {"max_tool_calls": 2},
     "failure_modes": []},
    {"name": "project_pmo", "version": "1.0", "implemented": True, "task_types": ["project_management", "strategy_consulting", "docs_ops"],
     "tools": [], "permissions": ["content.draft"], "input_schema": {"objective": "str"}, "output_schema": {"deliverable": "str"},
     "models": ["ollama:gemma4:12b", "template"], "cost_hint_minor": 0, "limits": {"max_tool_calls": 2},
     "failure_modes": []},
]

TEAM_LIMITS = {"max_agents_per_mission": 12, "max_delegation_depth": 1, "max_concurrency_per_mission": 2,
               "max_tasks_per_plan": 20, "max_revisions": 2}


def seed_capabilities(s: Session) -> None:
    for c in CAPABILITIES:
        if not s.scalar(select(Capability).where(Capability.name == c["name"], Capability.version == c["version"])):
            s.add(Capability(name=c["name"], version=c["version"], spec=c, implemented=c["implemented"]))


def spec(name: str) -> dict[str, Any]:
    for c in CAPABILITIES:
        if c["name"] == name:
            return c
    raise KeyError(name)


def limits_for(name: str) -> AgentLimits:
    l = spec(name).get("limits", {})
    return AgentLimits(max_tool_calls=l.get("max_tool_calls", 10))


def evaluation_stats(s: Session) -> dict[str, dict[str, Any]]:
    """Evaluation history per capability (from AgentRun + Evaluation tables)."""
    out: dict[str, dict[str, Any]] = {}
    for cap, status, n in s.execute(select(AgentRun.capability, AgentRun.status, func.count()).group_by(AgentRun.capability, AgentRun.status)):
        out.setdefault(cap, {"runs": 0, "succeeded": 0})
        out[cap]["runs"] += n
        if status == "succeeded":
            out[cap]["succeeded"] += n
    acc = dict(s.execute(select(Evaluation.verdict, func.count()).group_by(Evaluation.verdict)).all())
    out.setdefault("content", {"runs": 0, "succeeded": 0})["review_verdicts"] = acc
    return out


def compose_team(s: Session, required: list[str]) -> dict[str, Any]:
    """Pick one implementation per required capability. Prefer evaluated versions with higher success rate;
    fall back to explicit configuration (registry order) when no data."""
    stats = evaluation_stats(s)
    team, unavailable = [], []
    for name in dict.fromkeys(required):
        cands = [c for c in CAPABILITIES if c["name"] == name]
        if not cands or not any(c["implemented"] for c in cands):
            unavailable.append(name)
            continue
        best = sorted((c for c in cands if c["implemented"]), key=lambda c: -(stats.get(name, {}).get("succeeded", 0)))[0]
        team.append({"capability": name, "version": best["version"],
                     "selection_basis": "evaluation_history" if stats.get(name, {}).get("runs") else "explicit_config"})
    if len(team) > TEAM_LIMITS["max_agents_per_mission"]:
        raise ValueError("team exceeds max_agents_per_mission")
    return {"team": team, "unavailable": unavailable, "limits": TEAM_LIMITS}
