from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional


PATCH_RESULT_STATUSES = {
    "STAGED",
    "APPROVAL_REQUIRED",
    "APPLIED_TO_COPY",
    "APPLIED_TO_TARGET",
    "BLOCKED",
    "VALIDATION_FAILED",
    "NO_OP",
}

PATCH_OPERATION_TYPES = {
    "set_requires_approval",
    "set_enabled",
    "set_execution_mode",
    "adjust_priority",
    "add_watchlist_note",
    "add_quarantine_note",
    "no_op",
}

EXTERNAL_PROVIDER_TYPES = {"codex_cli", "cline", "ecc", "api_model", "manual_handoff"}


@dataclass
class RouterUpdatePolicy:
    enabled: bool = True
    safety: dict[str, Any] = field(default_factory=dict)
    approval: dict[str, Any] = field(default_factory=dict)
    recommendations: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, Any] = field(default_factory=dict)


@dataclass
class RouterPatchOperation:
    operation_id: str
    provider_id: str
    operation_type: str
    target_path: str
    old_value: Any | None
    new_value: Any | None
    reason: list[str] = field(default_factory=list)
    source_recommendation: str = ""
    safety_level: str = "approval_required"
    requires_approval: bool = True


@dataclass
class RouterPolicyPatch:
    patch_id: str
    source_recommendations_path: str
    router_policy_path: str
    operations: list[RouterPatchOperation] = field(default_factory=list)
    apply_automatically: bool = False
    requires_human_approval: bool = True
    created_at: Optional[str] = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class RouterPatchPlan:
    patch: RouterPolicyPatch
    output_dir: str
    artifacts: dict[str, str] = field(default_factory=dict)


@dataclass
class RouterPatchApprovalRequest:
    patch_id: str
    required: bool
    reason: list[str] = field(default_factory=list)
    approval_method: str = "file_token"
    approval_token_hint: Optional[str] = None
    allowed_apply_targets: list[str] = field(default_factory=list)


@dataclass
class RouterPatchApproval:
    patch_id: str
    approved: bool
    approval_method: str = "file_token"
    reason: list[str] = field(default_factory=list)


@dataclass
class RouterPatchResult:
    patch_id: str
    applied: bool
    applied_to: Optional[str]
    status: str
    operations_applied: int = 0
    rollback_plan_path: Optional[str] = None
    reasons: list[str] = field(default_factory=list)


@dataclass
class RouterRollbackPlan:
    patch_id: str
    restore_method: str
    affected_providers: list[str] = field(default_factory=list)
    affected_task_types: list[str] = field(default_factory=list)
    operations: list[dict[str, Any]] = field(default_factory=list)
    original_router_policy: dict[str, Any] = field(default_factory=dict)
    patched_router_policy: dict[str, Any] = field(default_factory=dict)


@dataclass
class RouterUpdateLedgerEntry:
    event: str
    patch_id: str
    status: str
    reason: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    created_at: Optional[str] = None


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
