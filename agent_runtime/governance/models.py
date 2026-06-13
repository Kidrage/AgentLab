from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional


RECOMMENDATIONS = {
    "prefer",
    "keep",
    "watchlist",
    "downgrade",
    "quarantine",
    "require_manual_approval",
    "insufficient_data",
}

GOVERNANCE_STATUSES = {
    "HEALTHY",
    "WATCHLIST",
    "DOWNGRADED",
    "QUARANTINE_RECOMMENDED",
    "MANUAL_APPROVAL_REQUIRED",
    "INSUFFICIENT_DATA",
}


@dataclass
class ProviderPerformanceProfile:
    provider_id: str
    provider_type: str
    attempts: int = 0
    accepted: int = 0
    rejected: int = 0
    retry_count: int = 0
    pass_count: int = 0
    pass_with_warnings_count: int = 0
    needs_revision_count: int = 0
    fail_count: int = 0
    blocked_count: int = 0
    acceptance_rate: float = 0.0
    retry_rate: float = 0.0
    blocked_rate: float = 0.0
    average_quality_score: float = 0.0
    last_verdict: Optional[str] = None
    trend: str = "insufficient_data"
    notes: list[str] = field(default_factory=list)


@dataclass
class ProviderGovernancePolicy:
    enabled: bool = True
    minimum_data: dict[str, Any] = field(default_factory=dict)
    thresholds: dict[str, Any] = field(default_factory=dict)
    cost: dict[str, Any] = field(default_factory=dict)
    routing_feedback: dict[str, Any] = field(default_factory=dict)
    watchlist: dict[str, Any] = field(default_factory=dict)
    quarantine: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderCostProfile:
    provider_id: str
    cost_mode: str = "unknown"
    estimated_total_cost_usd: Optional[float] = None
    estimated_average_cost_usd: Optional[float] = None
    unknown_cost_events: int = 0
    cost_risk_level: str = "unknown"
    requires_manual_approval: bool = False
    notes: list[str] = field(default_factory=list)


@dataclass
class ProviderRiskProfile:
    provider_id: str
    risk_level: str = "unknown"
    reasons: list[str] = field(default_factory=list)


@dataclass
class ProviderRoutingRecommendation:
    provider_id: str
    recommendation: str
    reason: list[str] = field(default_factory=list)
    priority_delta: int = 0
    requires_human_review: bool = False
    apply_automatically: bool = False


@dataclass
class GovernanceDecision:
    provider_id: str
    status: str
    reasons: list[str] = field(default_factory=list)
    recommended_action: str = "keep"


@dataclass
class ProviderWatchlistEntry:
    provider_id: str
    reasons: list[str] = field(default_factory=list)
    requires_human_review: bool = False


@dataclass
class ProviderQuarantineRecommendation:
    provider_id: str
    reasons: list[str] = field(default_factory=list)
    requires_human_review: bool = True
    test_recommendation_only: bool = False


@dataclass
class GovernanceReport:
    profiles: list[ProviderPerformanceProfile] = field(default_factory=list)
    decisions: list[GovernanceDecision] = field(default_factory=list)
    watchlist: list[ProviderWatchlistEntry] = field(default_factory=list)
    quarantine_recommendations: list[ProviderQuarantineRecommendation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class CostGovernanceReport:
    cost_profiles: list[ProviderCostProfile] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class GovernanceInputBundle:
    root: Path
    execution_ledgers: list[dict[str, Any]] = field(default_factory=list)
    retry_attempt_ledgers: list[dict[str, Any]] = field(default_factory=list)
    provider_scorecards: list[dict[str, Any]] = field(default_factory=list)
    final_receipts: list[dict[str, Any]] = field(default_factory=list)
    manifest: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


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
