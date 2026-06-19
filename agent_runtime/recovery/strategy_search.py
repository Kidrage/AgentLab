"""Deterministic S6 recovery strategy search."""

from __future__ import annotations

from dataclasses import dataclass


from agent_runtime.recovery.failure_taxonomy import S6FailureType, normalize_failure_type


@dataclass
class RecoveryStrategy:
    """Recommended next action for a failure type."""

    failure_type: str
    next_action: str
    rationale: str
    safe_to_auto_execute: bool
    requires_human_approval: bool
    max_attempts: int

    def to_dict(self) -> dict[str, object]:
        return {
            "failure_type": self.failure_type,
            "next_action": self.next_action,
            "rationale": self.rationale,
            "safe_to_auto_execute": self.safe_to_auto_execute,
            "requires_human_approval": self.requires_human_approval,
            "max_attempts": self.max_attempts,
        }


STRATEGY_TABLE: dict[S6FailureType, RecoveryStrategy] = {
    S6FailureType.TOOL_UNAVAILABLE: RecoveryStrategy(
        S6FailureType.TOOL_UNAVAILABLE.value,
        "fallback_manual_template",
        "A required tool is unavailable; produce a manual/local fallback rather than executing missing tooling.",
        False,
        True,
        0,
    ),
    S6FailureType.NETWORK_BLOCKED: RecoveryStrategy(
        S6FailureType.NETWORK_BLOCKED.value,
        "fallback_manual_template",
        "Network is blocked by policy or environment; use local fixtures, cached evidence, or ask for approval.",
        False,
        True,
        0,
    ),
    S6FailureType.PROVIDER_FAILED: RecoveryStrategy(
        S6FailureType.PROVIDER_FAILED.value,
        "retry_with_stronger_model",
        "Provider failures may be retried once with an approved alternate provider or downgraded safely.",
        False,
        True,
        1,
    ),
    S6FailureType.SKILL_MISSING: RecoveryStrategy(
        S6FailureType.SKILL_MISSING.value,
        "search_skill",
        "Search or incubate a skill candidate, but do not install or execute it without S4 gates.",
        False,
        True,
        0,
    ),
    S6FailureType.SKILL_FAILED: RecoveryStrategy(
        S6FailureType.SKILL_FAILED.value,
        "switch_external_agent",
        "A failed skill should be quarantined or replaced through an approved alternate route.",
        False,
        True,
        0,
    ),
    S6FailureType.ARTIFACT_FAILED_VALIDATION: RecoveryStrategy(
        S6FailureType.ARTIFACT_FAILED_VALIDATION.value,
        "decompose_smaller",
        "Regenerate or repair the smallest invalid artifact and rerun its validator.",
        False,
        False,
        1,
    ),
    S6FailureType.QUALITY_FAILED: RecoveryStrategy(
        S6FailureType.QUALITY_FAILED.value,
        "decompose_smaller",
        "Split the failed quality target into a smaller patch/review loop with focused checks.",
        False,
        False,
        1,
    ),
    S6FailureType.AGENT_HALLUCINATED: RecoveryStrategy(
        S6FailureType.AGENT_HALLUCINATED.value,
        "stop_safely",
        "Hallucinated evidence or claims must stop delivery until grounded evidence is collected.",
        False,
        True,
        0,
    ),
    S6FailureType.EVIDENCE_MISSING: RecoveryStrategy(
        S6FailureType.EVIDENCE_MISSING.value,
        "stop_safely",
        "Missing evidence is a hard fail for factual claims; collect sources before continuing.",
        False,
        True,
        0,
    ),
    S6FailureType.PERMISSION_MISSING: RecoveryStrategy(
        S6FailureType.PERMISSION_MISSING.value,
        "ask_user",
        "A policy or permission gate is missing; request an explicit decision before proceeding.",
        False,
        True,
        0,
    ),
    S6FailureType.CONTEXT_INSUFFICIENT: RecoveryStrategy(
        S6FailureType.CONTEXT_INSUFFICIENT.value,
        "retry_same",
        "Refresh the context pack once, then stop if the necessary context remains unavailable.",
        False,
        False,
        1,
    ),
    S6FailureType.BUDGET_EXCEEDED: RecoveryStrategy(
        S6FailureType.BUDGET_EXCEEDED.value,
        "decompose_smaller",
        "Reduce scope, use cheaper local checks, or defer optional work.",
        False,
        False,
        0,
    ),
    S6FailureType.CAPABILITY_GAP: RecoveryStrategy(
        S6FailureType.CAPABILITY_GAP.value,
        "install_capability",
        "Generate a decision card for the missing capability; installation is approval-gated.",
        False,
        True,
        0,
    ),
    S6FailureType.UNKNOWN: RecoveryStrategy(
        S6FailureType.UNKNOWN.value,
        "ask_user",
        "The failure is not classifiable enough for safe autonomous recovery.",
        False,
        True,
        0,
    ),
}


def search_recovery_strategy(failure_type: str | None) -> RecoveryStrategy:
    """Return the deterministic strategy for a failure type."""

    normalized = normalize_failure_type(failure_type)
    return STRATEGY_TABLE.get(normalized, STRATEGY_TABLE[S6FailureType.UNKNOWN])