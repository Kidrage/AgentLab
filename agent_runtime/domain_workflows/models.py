"""Dataclasses for AgentLab S2 domain workflow planning.

The S2 model layer is intentionally plain and serializable.  It represents a
planned production workflow derived from a Mission Contract, not an executable
runtime graph.  No class in this module opens files, shells out, calls networks,
loads providers, or installs skills.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class WorkflowPhase:
    """One phase in a deterministic domain workflow plan."""

    phase_id: str
    title: str
    goal: str
    required_inputs: list[str] = field(default_factory=list)
    expected_artifacts: list[str] = field(default_factory=list)
    acceptance_gates: list[str] = field(default_factory=list)
    recommended_agents: list[str] = field(default_factory=list)
    recommended_skills: list[str] = field(default_factory=list)
    required_capabilities: list[str] = field(default_factory=list)
    human_decision_point: bool = False
    failure_recovery: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkflowPlanWarning:
    """Structured warning produced while building a workflow plan."""

    warning_id: str
    level: str
    message: str
    source: str = "workflow_planner"


@dataclass(frozen=True)
class WorkflowPlanDecisionPoint:
    """Human decision point preserved in a workflow plan."""

    decision_id: str
    title: str
    reason: str
    required: bool = True
    phase_id: str | None = None


@dataclass(frozen=True)
class DomainWorkflowTemplate:
    """A YAML-loaded S2 domain workflow template."""

    template_id: str
    display_name: str
    description: str
    trigger_task_types: list[str] = field(default_factory=list)
    trigger_signals: list[str] = field(default_factory=list)
    required_capabilities: list[str] = field(default_factory=list)
    recommended_agents: list[str] = field(default_factory=list)
    recommended_skills: list[str] = field(default_factory=list)
    phase_plan: list[WorkflowPhase] = field(default_factory=list)
    required_artifacts: list[str] = field(default_factory=list)
    acceptance_gates: list[str] = field(default_factory=list)
    risk_defaults: list[str] = field(default_factory=list)
    failure_recovery: dict[str, str] = field(default_factory=dict)
    human_decision_points: list[str] = field(default_factory=list)
    route_preferences: dict[str, Any] = field(default_factory=dict)
    risk_notes: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkflowPlan:
    """Mission Contract to domain workflow planning result."""

    task_id: str | None
    template_id: str
    domain: str
    source_mission_contract_path: str | None
    phases: list[WorkflowPhase] = field(default_factory=list)
    required_capabilities: list[str] = field(default_factory=list)
    recommended_agents: list[str] = field(default_factory=list)
    recommended_skills: list[str] = field(default_factory=list)
    expected_artifacts: list[str] = field(default_factory=list)
    acceptance_gates: list[str] = field(default_factory=list)
    human_decision_points: list[str] = field(default_factory=list)
    route_preferences: dict[str, Any] = field(default_factory=dict)
    warnings: list[WorkflowPlanWarning] = field(default_factory=list)
    decision_points: list[WorkflowPlanDecisionPoint] = field(default_factory=list)
