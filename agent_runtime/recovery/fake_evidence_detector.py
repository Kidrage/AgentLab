"""S6 fake evidence detector.

This module intentionally uses strict deterministic checks. It does not decide
whether a source is true; it rejects factual-claim readiness when required source
metadata is missing or internally contradictory.
"""

from __future__ import annotations

from typing import Any


REQUIRED_SOURCE_FIELDS = {
    "content_hash": ("content_hash", "hash", "sha256"),
    "line_refs": ("line_refs", "line_range", "lines", "line_start"),
}


def _source_line_refs(source: dict[str, Any]) -> Any:
    """Extract supported line reference shapes from a source mapping."""

    return (
        source.get("line_refs")
        or source.get("line_range")
        or source.get("lines")
        or (
            [source.get("line_start"), source.get("line_end")]
            if source.get("line_start") is not None and source.get("line_end") is not None
            else None
        )
    )


def _source_issues(index: int, source: Any) -> list[str]:
    """Return deterministic evidence issues for one source entry."""

    if not isinstance(source, dict):
        return [f"source_{index}_not_mapping"]

    issues: list[str] = []
    if not (source.get("content_hash") or source.get("hash") or source.get("sha256")):
        issues.append(f"source_{index}_missing_content_hash")
    if _source_line_refs(source) in (None, [], ""):
        issues.append(f"source_{index}_missing_line_refs")
    return issues


def summarize_evidence_issues(report: dict[str, Any]) -> dict[str, object]:
    """Return compact issue counts for ledgers and acceptance evidence."""

    issues = list(report.get("issues") or [])
    source_issues = [issue for issue in issues if issue.startswith("source_")]
    policy_issues = [issue for issue in issues if not issue.startswith("source_")]
    return {
        "issue_count": len(issues),
        "source_issue_count": len(source_issues),
        "policy_issue_count": len(policy_issues),
        "hard_fail": bool(report.get("hard_fail")),
    }


def detect_fake_evidence(evidence_ledger: dict[str, Any] | None) -> dict[str, Any]:
    """Return a hard-fail report for missing or ungrounded evidence."""

    ledger = evidence_ledger or {}
    sources = ledger.get("sources") or []
    facts_allowed = bool(ledger.get("facts_allowed"))
    issues: list[str] = []

    if facts_allowed and not sources:
        issues.append("facts_allowed_without_sources")
    if not sources:
        issues.append("evidence_missing")

    for index, source in enumerate(sources):
        issues.extend(_source_issues(index, source))

    if ledger.get("claims") and not sources:
        issues.append("claims_without_sources")

    verdict = "fail" if issues else "pass"
    return {
        "schema_version": 1,
        "verdict": verdict,
        "hard_fail": verdict == "fail",
        "issues": sorted(set(issues)),
        "facts_allowed": facts_allowed and verdict == "pass",
        "source_count": len(sources),
        "policy": {
            "no_sources_no_factual_claims": True,
            "require_content_hash": True,
            "require_line_refs": True,
        },
    }
