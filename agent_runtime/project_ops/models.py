"""ProjectOps data models for AgentLab S2.5.

These models intentionally avoid runtime execution semantics. They describe
repository hygiene, project routing, task compaction, agent contributions, and
lightweight packets so other layers can stay auditable and compact.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class HygieneFinding:
    """A single repository hygiene finding."""

    severity: str
    path: str
    code: str
    message: str
    suggested_destination: str | None = None


@dataclass(frozen=True)
class HygieneReport:
    """Repository root hygiene scan result."""

    root: str
    hard_violation_count: int
    warning_count: int
    findings: list[HygieneFinding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.hard_violation_count == 0


@dataclass(frozen=True)
class ProjectRouteDecision:
    """Decision for mapping an invocation to a project."""

    outcome: str
    project_id: str | None
    project_type: str
    reason: str
    requires_user_decision: bool = False
    suggested_project_id: str | None = None


@dataclass(frozen=True)
class ProjectInitResult:
    """Result from deterministic project initialization."""

    project_id: str
    root_path: str
    created_paths: list[str]
    existing_paths: list[str]


@dataclass(frozen=True)
class TaskCompactionResult:
    """Result from task compaction."""

    project_id: str
    task_id: str
    compact_dir: str
    created_files: list[str]
    raw_files_preserved: list[str]
    memory_promotion_count: int
    prune_executed: bool = False


@dataclass(frozen=True)
class AgentContributionSummary:
    """Summary of one agent's contribution."""

    agent_id: str
    role: str
    status: str
    artifacts_created: list[str] = field(default_factory=list)
    findings: list[dict[str, Any]] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    estimated_input_tokens: int = 0
    estimated_output_tokens: int = 0
    estimated_cost_usd: float | None = None
    accepted_by_supervisor: bool | None = None


@dataclass(frozen=True)
class AgentPacket:
    """Small structured handoff packet between AgentLab agents."""

    packet_id: str
    project_id: str
    task_id: str
    sender: str
    receiver: str
    purpose: str
    max_context_budget_tokens: int
    must_read: list[str]
    summary: dict[str, Any]
    requested_action: dict[str, Any]
    forbidden: list[str]

    def validate(self) -> None:
        if self.max_context_budget_tokens <= 0:
            raise ValueError("max_context_budget_tokens must be positive")
        if self.max_context_budget_tokens > 4000:
            raise ValueError("agent packets must stay compact; budget exceeds 4000 tokens")
        if not self.must_read:
            raise ValueError("agent packet must point to at least one must_read artifact")
        if not self.forbidden:
            raise ValueError("agent packet must declare forbidden actions")


def as_path(value: str | Path) -> Path:
    return value if isinstance(value, Path) else Path(value)
