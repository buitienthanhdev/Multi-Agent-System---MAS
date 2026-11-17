"""Policy engine: deterministic, versioned rules. Agents/tool output cannot modify policies."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

DEFAULT_RULES: dict[str, Any] = {
    "external_action_types": ["publish.sandbox", "publish.live", "ads.launch", "message.send_customer", "budget.spend"],
    "always_require_approval": ["publish.sandbox", "publish.live", "ads.launch", "message.send_customer", "budget.spend"],
    "max_single_action_minor": 10_000_000,
    "blocked_content_patterns": ["bảo hành trọn đời", "cam kết 100%", "rẻ nhất thị trường", "chữa", "tốt nhất thế giới"],
    "allowed_mission_statuses_for_actions": ["active"],
}


@dataclass
class PolicyDecision:
    allowed: bool
    requires_approval: bool
    reasons: list[str] = field(default_factory=list)


def evaluate_action(rules: dict[str, Any], *, mission_status: str, permitted_actions: list[str], action_type: str,
                    payload: dict[str, Any], cost_minor: int) -> PolicyDecision:
    reasons: list[str] = []
    if mission_status not in rules["allowed_mission_statuses_for_actions"]:
        reasons.append(f"mission status '{mission_status}' does not allow new actions")
    if action_type not in permitted_actions:
        reasons.append(f"action '{action_type}' not in mission permitted_actions")
    if cost_minor > rules["max_single_action_minor"]:
        reasons.append("cost exceeds max_single_action_minor")
    text = " ".join(str(v) for v in payload.values()).lower()
    for pat in rules["blocked_content_patterns"]:
        if pat in text:
            reasons.append(f"blocked content pattern: {pat}")
    return PolicyDecision(allowed=not reasons, requires_approval=action_type in rules["always_require_approval"],
                          reasons=reasons)
