"""S6 escalation policy helpers."""

from __future__ import annotations

from agent_runtime.recovery.failure_taxonomy import S6FailureType, normalize_failure_type


HUMAN_APPROVAL_REQUIRED = {
    S6FailureType.TOOL_UNAVAILABLE,
    S6FailureType.NETWORK_BLOCKED,
    S6FailureType.PROVIDER_FAILED,
    S6FailureType.SKILL_MISSING,
    S6FailureType.SKILL_FAILED,
    S6FailureType.AGENT_HALLUCINATED,
    S6FailureType.EVIDENCE_MISSING,
    S6FailureType.PERMISSION_MISSING,
    S6FailureType.CAPABILITY_GAP,
    S6FailureType.UNKNOWN,
}


def escalation_for_failure(failure_type: str | None) -> dict[str, object]:
    """Return approval and stop-policy metadata for a failure type."""

    normalized = normalize_failure_type(failure_type)
    return {
        "failure_type": normalized.value,
        "human_approval_required": normalized in HUMAN_APPROVAL_REQUIRED,
        "stop_on_missing_evidence": normalized in {
            S6FailureType.EVIDENCE_MISSING,
            S6FailureType.AGENT_HALLUCINATED,
        },
        "max_auto_retries": 0 if normalized in HUMAN_APPROVAL_REQUIRED else 1,
        "ledger_required": True,
    }