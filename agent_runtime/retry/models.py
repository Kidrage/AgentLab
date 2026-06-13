from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass
class RetryPolicy:
    enabled: bool = True
    loop: dict[str, Any] = field(default_factory=dict)
    budget: dict[str, Any] = field(default_factory=dict)
    routing: dict[str, Any] = field(default_factory=dict)
    review: dict[str, Any] = field(default_factory=dict)
    scorecard: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, Any] = field(default_factory=dict)


@dataclass
class RetryAttempt:
    task_id: str
    attempt_id: str
    attempt_index: int
    provider_id: str
    provider_type: str
    execution_mode: str
    input_handoff: Optional[str] = None
    route_report: Optional[str] = None
    execution_plan: Optional[str] = None
    result_envelope: Optional[str] = None
    review_verdict: Optional[str] = None
    review_report: Optional[str] = None
    retry_handoff: Optional[str] = None
    retry_decision: Optional[str] = None
    status: str = "planned"
    failure_reasons: list[str] = field(default_factory=list)
    estimated_cost_usd: Optional[float] = None
    created_at: Optional[str] = None


@dataclass
class RetryDecision:
    status: str
    reason: list[str] = field(default_factory=list)
    next_action: str = "stop"
    next_provider_id: Optional[str] = None
    retry_handoff_path: Optional[str] = None
    stop_reason: Optional[str] = None


@dataclass
class RetryLoopState:
    task_id: str
    task_type: str
    current_attempt: int
    max_attempts: int
    total_estimated_cost_usd: Optional[float] = 0.0
    status: str = "planned"
    attempts: list[RetryAttempt] = field(default_factory=list)
    decisions: list[RetryDecision] = field(default_factory=list)
    final_verdict: Optional[str] = None
    accepted: bool = False


@dataclass
class ProviderScorecardEntry:
    provider_id: str
    provider_type: str
    attempts: int = 0
    passes: int = 0
    pass_with_warnings: int = 0
    needs_revision: int = 0
    fails: int = 0
    blocked: int = 0
    average_quality_score: float = 0.0
    last_verdict: Optional[str] = None
    notes: list[str] = field(default_factory=list)
    total_quality_score: float = 0.0


@dataclass
class RetryLoopReport:
    task_id: str
    accepted: bool
    final_verdict: Optional[str]
    attempts: list[RetryAttempt] = field(default_factory=list)
    decisions: list[RetryDecision] = field(default_factory=list)
    scorecard: list[ProviderScorecardEntry] = field(default_factory=list)


def to_plain_data(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "__dataclass_fields__"):
        return {key: to_plain_data(item) for key, item in asdict(value).items()}
    if isinstance(value, list):
        return [to_plain_data(item) for item in value]
    if isinstance(value, dict):
        return {str(key): to_plain_data(item) for key, item in value.items()}
    return value
