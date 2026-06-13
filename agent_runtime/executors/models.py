from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional


PROVIDER_TYPES = {
    "manual_handoff",
    "mock_executor",
    "codex_cli",
    "cline",
    "ecc",
    "api_model",
    "agentlab_internal",
}

EXECUTION_MODES = {
    "disabled",
    "dry_run",
    "manual_handoff_only",
    "mock",
    "approved_auto",
}

DECISION_STATUSES = {
    "ROUTED",
    "NEEDS_APPROVAL",
    "NO_PROVIDER",
    "BLOCKED_BY_POLICY",
    "DRY_RUN_ONLY",
}

EXTERNAL_PROVIDER_TYPES = {"codex_cli", "cline", "ecc", "api_model", "manual_handoff"}


@dataclass
class ExecutorProvider:
    provider_id: str
    provider_type: str
    display_name: str
    enabled: bool
    execution_mode: str
    capabilities: list[str] = field(default_factory=list)
    suitable_task_types: list[str] = field(default_factory=list)
    risk_level: str = "medium"
    requires_approval: bool = False
    cost_mode: str = "unknown"
    expected_cost_tier: str = "unknown"
    supports_auto_execution: bool = False
    supports_manual_handoff: bool = False
    notes: list[str] = field(default_factory=list)


@dataclass
class ExecutionRequest:
    task_id: str
    task_type: str
    summary: str
    repo_path: Optional[Path] = None
    allowed_files: list[str] = field(default_factory=list)
    forbidden_files: list[str] = field(default_factory=list)
    required_capabilities: list[str] = field(default_factory=list)
    risk_level: str = "low"
    max_cost_usd: Optional[float] = None
    requires_review: bool = True
    evidence_required: list[str] = field(default_factory=list)


@dataclass
class ExecutionPlan:
    task_id: str
    selected_provider_id: str
    selected_provider_type: str
    execution_mode: str
    approval_required: bool
    estimated_cost_usd: Optional[float]
    estimated_risk: str
    reason: list[str] = field(default_factory=list)
    handoff_artifact: Optional[str] = None
    expected_result_envelope: str = "execution_result_envelope.yml"
    review_required: bool = True


@dataclass
class ExecutorDecision:
    status: str
    selected_provider_id: Optional[str] = None
    rejected_providers: list[dict[str, Any]] = field(default_factory=list)
    reason: list[str] = field(default_factory=list)
    approval_required: bool = False


@dataclass
class ExecutionReceipt:
    task_id: str
    provider_id: str
    execution_mode: str
    started_at: Optional[str]
    completed_at: Optional[str]
    status: str
    artifacts: list[str] = field(default_factory=list)
    ledger_path: str = ""


@dataclass
class ExecutionResultEnvelope:
    task_id: str
    provider_id: str
    source: str
    status: str
    changed_files: list[str] = field(default_factory=list)
    claimed_tests: list[str] = field(default_factory=list)
    output_artifacts: list[str] = field(default_factory=list)
    summary: str = ""
    safety_attestation: dict[str, Any] = field(default_factory=dict)
    review_target_dir: str = ""


@dataclass
class ExecutionLedgerEntry:
    event: str
    provider_id: str
    provider_type: str
    execution_mode: str
    status: str
    reason: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    created_at: Optional[str] = None


@dataclass
class ExecutionRouteReport:
    task_id: str
    decision: ExecutorDecision
    plan: Optional[ExecutionPlan] = None
    rejected_providers: list[dict[str, Any]] = field(default_factory=list)


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
