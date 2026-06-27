from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ProjectBrief:
    project: str
    task_type: str
    user_goal: str
    intent_summary: str
    required_capabilities: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    artifact_targets: list[str] = field(default_factory=list)
    long_project_governance: dict[str, Any] = field(default_factory=dict)


@dataclass
class PhasePlan:
    phase_id: str
    goal: str
    scope: list[str]
    inputs: list[str]
    outputs: list[str]
    acceptance_criteria: list[str]
    required_capabilities: list[str]
    recommended_skills: list[str]
    risk_flags: list[str]
    human_decision_points: list[str]
    evidence_required: list[str]


def to_plain_data(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return {key: to_plain_data(item) for key, item in asdict(value).items()}
    if isinstance(value, list):
        return [to_plain_data(item) for item in value]
    if isinstance(value, dict):
        return {str(key): to_plain_data(item) for key, item in value.items()}
    return value
