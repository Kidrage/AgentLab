"""S6 fake evidence detector.

This module intentionally uses strict deterministic checks. It does not decide
whether a source is true; it rejects factual-claim readiness when required source
metadata is missing or internally contradictory.
"""

from __future__ import annotations

from typing import Any


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
        if not isinstance(source, dict):
            issues.append(f"source_{index}_not_mapping")
            continue
        if not (source.get("content_hash") or source.get("hash") or source.get("sha256")):
            issues.append(f"source_{index}_missing_content_hash")
        line_refs = (
            source.get("line_refs")
            or source.get("line_range")
            or source.get("lines")
            or (
                [source.get("line_start"), source.get("line_end")]
                if source.get("line_start") is not None and source.get("line_end") is not None
                else None
            )
        )
        if line_refs in (None, [], ""):
            issues.append(f"source_{index}_missing_line_refs")

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