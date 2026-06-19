"""S6 escalation policy helpers.

This module keeps the approval decision separate from strategy selection.
``strategy_search`` answers "what route might recover this task?", while this
module answers "what gates must be satisfied before that route is acted on?".
The split is intentionally explicit so future S6 routes can add policy metadata
without weakening the hard stop behavior for missing evidence.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent_runtime.recovery.failure_taxonomy import S6FailureType, normalize_failure_type


HUMAN_APPROVAL_REQUIRED: set[S6FailureType] = {
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


STOP_ON_MISSING_EVIDENCE: set[S6FailureType] = {
    S6FailureType.AGENT_HALLUCINATED,
    S6FailureType.EVIDENCE_MISSING,
}


AUTO_RETRY_ALLOWED: set[S6FailureType] = {
    S6FailureType.ARTIFACT_FAILED_VALIDATION,
    S6FailureType.QUALITY_FAILED,
    S6FailureType.CONTEXT_INSUFFICIENT,
}


LEDGER_REASON_BY_FAILURE: dict[S6FailureType, str] = {
    S6FailureType.TOOL_UNAVAILABLE: "Record unavailable tool and selected fallback.",
    S6FailureType.NETWORK_BLOCKED: "Record blocked network route and local evidence fallback.",
    S6FailureType.PROVIDER_FAILED: "Record provider failure and approved alternate provider.",
    S6FailureType.SKILL_MISSING: "Record missing skill and requested discovery/install decision.",
    S6FailureType.SKILL_FAILED: "Record failed skill and replacement or quarantine decision.",
    S6FailureType.ARTIFACT_FAILED_VALIDATION: "Record invalid artifact and focused repair attempt.",
    S6FailureType.QUALITY_FAILED: "Record quality gate failure and reduced-scope retry.",
    S6FailureType.AGENT_HALLUCINATED: "Record hallucinated claim and halt delivery.",
    S6FailureType.EVIDENCE_MISSING: "Record missing source evidence and halt factual delivery.",
    S6FailureType.PERMISSION_MISSING: "Record missing permission and user decision.",
    S6FailureType.CONTEXT_INSUFFICIENT: "Record missing context and refreshed context attempt.",
    S6FailureType.BUDGET_EXCEEDED: "Record budget gate and reduced-scope route.",
    S6FailureType.CAPABILITY_GAP: "Record missing capability and decision card outcome.",
    S6FailureType.UNKNOWN: "Record unclassified failure before requesting direction.",
}


@dataclass(frozen=True)
class EscalationProfile:
    """Approval and stop metadata for an S6 failure type."""

    failure_type: S6FailureType
    human_approval_required: bool
    stop_on_missing_evidence: bool
    max_auto_retries: int
    ledger_required: bool
    approval_reason: str
    allowed_without_approval: bool

    def to_dict(self) -> dict[str, object]:
        """Return the stable dict shape consumed by route planning output."""

        return {
            "failure_type": self.failure_type.value,
            "human_approval_required": self.human_approval_required,
            "stop_on_missing_evidence": self.stop_on_missing_evidence,
            "max_auto_retries": self.max_auto_retries,
            "ledger_required": self.ledger_required,
            "approval_reason": self.approval_reason,
            "allowed_without_approval": self.allowed_without_approval,
        }


def _max_auto_retries(failure_type: S6FailureType) -> int:
    """Return the bounded retry count for failures that can be repaired locally."""

    if failure_type in AUTO_RETRY_ALLOWED:
        return 1
    return 0


def _profile_for_failure(failure_type: S6FailureType) -> EscalationProfile:
    """Build an escalation profile from the policy sets above."""

    requires_approval = failure_type in HUMAN_APPROVAL_REQUIRED
    stop_on_evidence = failure_type in STOP_ON_MISSING_EVIDENCE
    retries = _max_auto_retries(failure_type)
    return EscalationProfile(
        failure_type=failure_type,
        human_approval_required=requires_approval,
        stop_on_missing_evidence=stop_on_evidence,
        max_auto_retries=retries,
        ledger_required=True,
        approval_reason=LEDGER_REASON_BY_FAILURE.get(
            failure_type,
            LEDGER_REASON_BY_FAILURE[S6FailureType.UNKNOWN],
        ),
        allowed_without_approval=not requires_approval and not stop_on_evidence,
    )


def escalation_for_failure(failure_type: str | None) -> dict[str, object]:
    """Return approval and stop-policy metadata for a failure type."""

    normalized = normalize_failure_type(failure_type)
    return _profile_for_failure(normalized).to_dict()
