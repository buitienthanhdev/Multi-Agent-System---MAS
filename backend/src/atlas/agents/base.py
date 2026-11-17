"""Agent contracts, tool permission guard and resource limits."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel, Field


class EvidenceItem(BaseModel):
    claim: str
    kind: str  # verified_fact|assumption|estimate|unknown|conflicting
    source: str
    source_type: str  # fixture|user|connector|agent_inference|computed
    scope: str = ""
    value: dict[str, Any] | None = None
    is_demo: bool = False
    untrusted_flags: list[str] = Field(default_factory=list)


class ArtifactOut(BaseModel):
    kind: str
    title: str
    content: str
    is_demo: bool = False


class AgentResult(BaseModel):
    status: str = "completed"  # completed|waiting_approval|blocked|revision_requested|failed
    output: dict[str, Any] = Field(default_factory=dict)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    artifacts: list[ArtifactOut] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    usage: dict[str, Any] = Field(default_factory=dict)
    next_steps: list[str] = Field(default_factory=list)
    provider: str = "none"
    blocked_reason: str | None = None


class ToolPermissionDenied(Exception):
    pass


class LimitExceeded(Exception):
    pass


@dataclass
class AgentLimits:
    max_tool_calls: int = 20
    max_tokens: int = 50_000
    max_seconds: float = 120.0
    max_delegation_depth: int = 1
    max_iterations: int = 8


@dataclass
class ToolBox:
    """All agent tool calls go through here. Permission = capability.tools; limits enforced per run."""
    allowed: set[str]
    registry: dict[str, Callable[..., Any]]
    limits: AgentLimits
    calls: list[str] = field(default_factory=list)
    started: float = field(default_factory=time.time)
    tokens: int = 0
    denied: list[str] = field(default_factory=list)

    def call(self, name: str, *args: Any, **kwargs: Any) -> Any:
        if name not in self.allowed or name not in self.registry:
            self.denied.append(name)
            raise ToolPermissionDenied(f"tool '{name}' not permitted for this capability")
        self.check_limits()
        self.calls.append(name)
        return self.registry[name](*args, **kwargs)

    def add_tokens(self, n: int) -> None:
        self.tokens += n
        self.check_limits()

    def check_limits(self) -> None:
        if len(self.calls) >= self.limits.max_tool_calls:
            raise LimitExceeded(f"max_tool_calls={self.limits.max_tool_calls} reached")
        if self.tokens > self.limits.max_tokens:
            raise LimitExceeded(f"max_tokens={self.limits.max_tokens} exceeded")
        if time.time() - self.started > self.limits.max_seconds:
            raise LimitExceeded(f"max_seconds={self.limits.max_seconds} exceeded")


@dataclass
class AgentContext:
    mission_id: str
    workspace_id: str
    task_id: str
    task_key: str
    contract: dict[str, Any]
    task_input: dict[str, Any]
    upstream: dict[str, dict[str, Any]]  # task_key -> output
    tools: ToolBox
    is_demo: bool
    services: dict[str, Any] = field(default_factory=dict)
