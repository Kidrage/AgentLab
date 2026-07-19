"""Fail-closed narrative seal gate.

This module owns the small set of facts that can authorize a candidate seal.
It does not run a model and does not infer task intent from prose.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


_BLOCKING_STATUSES = {"block", "blocked", "fail", "failed", "rejected"}
_PASS_STATUSES = {"pass", "passed", "complete", "completed", "accepted"}


@dataclass(frozen=True)
class SealDecision:
    status: str
    allow_seal: bool
    requires_revision: bool
    blocking_reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["blocking_reasons"] = list(self.blocking_reasons)
        return result

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SealDecision":
        reasons = value.get("blocking_reasons")
        return cls(
            status=str(value.get("status") or "blocked"),
            allow_seal=bool(value.get("allow_seal")),
            requires_revision=bool(value.get("requires_revision")),
            blocking_reasons=tuple(str(item) for item in reasons)
            if isinstance(reasons, (list, tuple))
            else (),
        )


def _status(document: Mapping[str, Any]) -> str:
    return str(document.get("status") or document.get("verdict") or "").lower()


def _has_blocking_status(document: Mapping[str, Any]) -> bool:
    return any(
        str(document.get(key) or "").lower() in _BLOCKING_STATUSES
        for key in ("status", "verdict")
    )


def _candidate_hash(document: Mapping[str, Any]) -> str | None:
    for key in ("candidate_sha256", "artifact_sha256", "body_sha256"):
        value = document.get(key)
        if value:
            return str(value)
    return None


def _quality_is_blocking(scorecard: Mapping[str, Any]) -> bool:
    if _has_blocking_status(scorecard):
        return True
    dimensions = scorecard.get("dimensions")
    if isinstance(dimensions, Mapping):
        for value in dimensions.values():
            if isinstance(value, Mapping) and str(value.get("severity") or "").lower() == "blocking":
                return True
    return False


def evaluate_narrative_seal(
    *,
    fiction_review: Mapping[str, Any] | None,
    continuity_failure_report: Mapping[str, Any] | None,
    narrative_quality_scorecard: Mapping[str, Any] | None = None,
    candidate_sha256: str | None = None,
    audit_source_integrity: Mapping[str, Any] | None = None,
    required_audits: tuple[str, ...] = (
        "fiction_review",
        "continuity_failure_report",
    ),
    require_independent_reaudit: bool = False,
    independent_reaudit: Mapping[str, Any] | None = None,
    promotion_requested: bool = False,
    user_acceptance_receipt: Mapping[str, Any] | None = None,
    expected_lease_token: str | None = None,
    receipt_lease_token: str | None = None,
) -> SealDecision:
    """Return one deterministic seal decision from structured evidence."""
    invalid: list[str] = []
    content: list[str] = []
    documents = (
        ("fiction_review", fiction_review),
        ("continuity_failure_report", continuity_failure_report),
    )
    required = set(required_audits)
    for name, document in documents:
        if not isinstance(document, Mapping):
            invalid.append(f"missing_{name}")
        elif _status(document) not in {"pass", "passed", "warn", "warning"} and not _has_blocking_status(document):
            invalid.append(f"invalid_{name}_status")

    if not candidate_sha256:
        invalid.append("missing_candidate_sha256")
    if not isinstance(audit_source_integrity, Mapping):
        invalid.append("missing_audit_source_integrity")
    elif _status(audit_source_integrity) not in _PASS_STATUSES:
        invalid.extend(
            str(issue)
            for issue in (audit_source_integrity.get("issues") or ["audit_source_integrity_blocked"])
        )
    elif candidate_sha256 and _candidate_hash(audit_source_integrity) != candidate_sha256:
        invalid.append("audit_source_integrity_candidate_hash_mismatch")

    if isinstance(fiction_review, Mapping):
        if _has_blocking_status(fiction_review) or bool(fiction_review.get("blocking")):
            content.append("fiction_review_blocked")
    if isinstance(continuity_failure_report, Mapping):
        try:
            blocking_count = int(continuity_failure_report.get("blocking_issue_count") or 0)
        except (TypeError, ValueError):
            invalid.append("invalid_continuity_blocking_issue_count")
            blocking_count = 0
        if _has_blocking_status(continuity_failure_report) or blocking_count > 0:
            content.append("continuity_blocked")
    if isinstance(narrative_quality_scorecard, Mapping):
        if _quality_is_blocking(narrative_quality_scorecard):
            content.append("literary_quality_blocked")
        elif _status(narrative_quality_scorecard) not in {
            "pass", "passed", "warn", "warning"
        }:
            invalid.append("invalid_narrative_quality_scorecard_status")
    elif "narrative_quality_scorecard" in required:
        invalid.append("missing_narrative_quality_scorecard")

    if candidate_sha256:
        bound_documents = list(documents)
        if isinstance(narrative_quality_scorecard, Mapping):
            bound_documents.append(("narrative_quality_scorecard", narrative_quality_scorecard))
        for name, document in bound_documents:
            if not isinstance(document, Mapping):
                continue
            audited_hash = _candidate_hash(document)
            if not audited_hash:
                invalid.append(f"{name}_candidate_hash_missing")
            elif audited_hash != candidate_sha256:
                invalid.append(f"{name}_candidate_hash_mismatch")

    if require_independent_reaudit:
        if not isinstance(independent_reaudit, Mapping):
            invalid.append("missing_independent_reaudit")
        elif _status(independent_reaudit) not in _PASS_STATUSES:
            invalid.append("independent_reaudit_not_passed")
        elif independent_reaudit.get("independent_context") is not True:
            invalid.append("independent_reaudit_context_unproven")
        elif not independent_reaudit.get("audit_task_id"):
            invalid.append("independent_reaudit_task_missing")
        elif not independent_reaudit.get("source_audit_task_id"):
            invalid.append("independent_reaudit_source_task_missing")
        elif independent_reaudit.get("audit_task_id") == independent_reaudit.get("source_audit_task_id"):
            invalid.append("independent_reaudit_reused_source_task")
        elif candidate_sha256 and _candidate_hash(independent_reaudit) != candidate_sha256:
            invalid.append("independent_reaudit_candidate_hash_mismatch")

    if promotion_requested:
        if not isinstance(user_acceptance_receipt, Mapping):
            invalid.append("missing_user_acceptance_receipt")
        elif _status(user_acceptance_receipt) not in {"accepted", "pass", "passed"}:
            invalid.append("user_acceptance_not_accepted")
        elif candidate_sha256 and _candidate_hash(user_acceptance_receipt) != candidate_sha256:
            invalid.append("stale_user_acceptance_receipt")

    if expected_lease_token and receipt_lease_token != expected_lease_token:
        invalid.append("attempt_lease_expired")

    reasons = tuple(dict.fromkeys([*invalid, *content]))
    if invalid:
        return SealDecision("blocked", False, False, reasons)
    if content:
        return SealDecision("revision_required", False, True, reasons)
    return SealDecision("pass", True, False, ())
