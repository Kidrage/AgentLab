"""S6 failure taxonomy for alternative route planning.

The older P2 recovery layer classifies local execution failures. S6 adds a
broader, task-production taxonomy that can reason about missing capabilities,
missing evidence, provider failures, and safe escalation without executing any
route automatically.
"""

from __future__ import annotations

from enum import Enum


class S6FailureType(str, Enum):
    """S6 recovery brain failure types."""

    TOOL_UNAVAILABLE = "tool_unavailable"
    NETWORK_BLOCKED = "network_blocked"
    PROVIDER_FAILED = "provider_failed"
    SKILL_MISSING = "skill_missing"
    SKILL_FAILED = "skill_failed"
    ARTIFACT_FAILED_VALIDATION = "artifact_failed_validation"
    QUALITY_FAILED = "quality_failed"
    AGENT_HALLUCINATED = "agent_hallucinated"
    EVIDENCE_MISSING = "evidence_missing"
    PERMISSION_MISSING = "permission_missing"
    CONTEXT_INSUFFICIENT = "context_insufficient"
    BUDGET_EXCEEDED = "budget_exceeded"
    CAPABILITY_GAP = "capability_gap"
    UNKNOWN = "unknown"


LEGACY_FAILURE_MAP: dict[str, S6FailureType] = {
    "syntax_error": S6FailureType.ARTIFACT_FAILED_VALIDATION,
    "test_failure": S6FailureType.QUALITY_FAILED,
    "import_error": S6FailureType.TOOL_UNAVAILABLE,
    "missing_dependency": S6FailureType.TOOL_UNAVAILABLE,
    "missing_artifact": S6FailureType.ARTIFACT_FAILED_VALIDATION,
    "text_integrity_failure": S6FailureType.ARTIFACT_FAILED_VALIDATION,
    "remote_raw_failure": S6FailureType.ARTIFACT_FAILED_VALIDATION,
    "yaml_parse_failure": S6FailureType.ARTIFACT_FAILED_VALIDATION,
    "config_error": S6FailureType.ARTIFACT_FAILED_VALIDATION,
    "cli_usage_error": S6FailureType.TOOL_UNAVAILABLE,
    "context_budget_exceeded": S6FailureType.BUDGET_EXCEEDED,
    "context_missing": S6FailureType.CONTEXT_INSUFFICIENT,
    "secret_leak_risk": S6FailureType.PERMISSION_MISSING,
    "resource_limit": S6FailureType.BUDGET_EXCEEDED,
    "timeout": S6FailureType.PROVIDER_FAILED,
    "permission_error": S6FailureType.PERMISSION_MISSING,
    "network_disabled_or_unavailable": S6FailureType.NETWORK_BLOCKED,
    "external_tool_unavailable": S6FailureType.TOOL_UNAVAILABLE,
    "no_local_evidence": S6FailureType.EVIDENCE_MISSING,
    "s4_trust_gate_not_passed": S6FailureType.PERMISSION_MISSING,
}


def normalize_failure_type(value: str | None) -> S6FailureType:
    """Normalize raw, legacy, or S6 labels into an S6FailureType."""

    raw = str(value or "").strip().lower()
    if not raw:
        return S6FailureType.UNKNOWN
    try:
        return S6FailureType(raw)
    except ValueError:
        return LEGACY_FAILURE_MAP.get(raw, S6FailureType.UNKNOWN)


def all_s6_failure_types() -> list[str]:
    """Return all documented S6 failure type labels."""

    return [item.value for item in S6FailureType]