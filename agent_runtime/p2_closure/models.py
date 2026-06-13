"""P2-F Closure data models."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass
class ProviderFeedback:
    task_id: str
    delivery_id: str
    provider_id: str
    executor: str
    review_verdict: str
    quality_score: float
    artifact_completeness: float
    test_confidence: float
    safety_confidence: float
    retry_recommended: bool
    failure_reasons: list[str] = field(default_factory=list)
    governance_recommendation: str = "neutral"
    cost_estimated_usd: Optional[float] = None
    latency_duration_sec: Optional[float] = None
    evidence: list[str] = field(default_factory=list)
    created_at: Optional[str] = None


@dataclass
class RouterFeedback:
    task_id: str
    provider_id: str
    recommendation: str
    reason: list[str] = field(default_factory=list)
    confidence: str = "medium"
    dry_run: bool = True
    apply_allowed: bool = False
    approval_required: bool = True
    evidence: list[str] = field(default_factory=list)


@dataclass
class RouterApplyResult:
    patch_id: str
    applied: bool
    applied_to: Optional[str] = None
    status: str = "NO_OP"
    reasons: list[str] = field(default_factory=list)
    rollback_plan_path: Optional[str] = None


@dataclass
class P2ClosureResult:
    task_id: str
    delivery_id: str
    verdict_status: str
    output_dir: Path

    capability_map_path: Optional[str] = None
    review_verdict_path: Optional[str] = None
    revision_packet_path: Optional[str] = None
    provider_feedback_path: Optional[str] = None
    router_feedback_path: Optional[str] = None
    router_dry_run_path: Optional[str] = None
    router_apply_result_path: Optional[str] = None
    router_rollback_path: Optional[str] = None
    closure_report_path: Optional[str] = None

    verdict_reasons: list[str] = field(default_factory=list)
    revision_required: bool = False
    provider_feedback: Optional[ProviderFeedback] = None
    router_feedback: Optional[RouterFeedback] = None
    router_apply: Optional[RouterApplyResult] = None
