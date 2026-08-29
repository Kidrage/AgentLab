"""Evidence-bound capability promotion and rollback policy."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Sequence
import hashlib
import json

from agent_runtime.capability_vault import (
    CapabilityPackage,
    CapabilityVaultError,
)

PROMOTION_TARGETS = {
    ("supervisor_reviewed", "canary"),
    ("canary", "active"),
}
REQUIRED_FIXTURE_COUNT = 5
MINIMUM_NON_REGRESSING = 4


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _evidence_sha256(value: object) -> str:
    body = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def _binding_findings(
    evidence: Mapping[str, Any] | None,
    *,
    label: str,
    package: CapabilityPackage,
    required_schema: str,
    require_pass: bool = True,
) -> list[str]:
    if not isinstance(evidence, Mapping):
        return [f"{label}:evidence_required"]
    findings: list[str] = []
    if evidence.get("schema_version") != required_schema:
        findings.append(f"{label}:schema_version_mismatch")
    if evidence.get("package_id") != package.package_id:
        findings.append(f"{label}:package_id_mismatch")
    if evidence.get("version") != package.version:
        findings.append(f"{label}:version_mismatch")
    if evidence.get("source_digest") != package.source_digest:
        findings.append(f"{label}:source_digest_mismatch")
    if require_pass and evidence.get("status") != "pass":
        findings.append(f"{label}:status_not_pass")
    return findings


def _fixture_findings(
    fixtures: Sequence[Mapping[str, Any]],
) -> tuple[list[str], dict[str, Any]]:
    findings: list[str] = []
    domains: set[str] = set()
    non_regressing = 0
    passing = 0
    for index, fixture in enumerate(fixtures):
        domain = str(fixture.get("domain") or "").strip()
        if not domain:
            findings.append(f"fixture_domain_required:{index}")
            continue
        if domain in domains:
            findings.append(f"fixture_domain_duplicate:{domain}")
            continue
        domains.add(domain)
        if fixture.get("security_contract") != "pass":
            findings.append(f"fixture_security_contract_failed:{domain}")
        if fixture.get("status") == "pass":
            passing += 1
        else:
            findings.append(f"fixture_task_failed:{domain}")
        delta = fixture.get("baseline_delta")
        if (
            isinstance(delta, (int, float))
            and not isinstance(delta, bool)
            and float(delta) >= 0.0
        ):
            non_regressing += 1
    if len(domains) < REQUIRED_FIXTURE_COUNT:
        findings.append("five_distinct_fixture_domains_required")
    if non_regressing < MINIMUM_NON_REGRESSING:
        findings.append("fixture_non_regressing_below_four")
    summary = {
        "domain_count": len(domains),
        "domains": sorted(domains),
        "passing_count": passing,
        "non_regressing_count": non_regressing,
        "security_contracts_all_pass": not any(
            finding.startswith("fixture_security_contract_failed:")
            for finding in findings
        ),
    }
    return findings, summary


def evaluate_capability_promotion(
    manifest: Mapping[str, Any],
    *,
    current_status: str,
    target_status: str,
    static_audit: Mapping[str, Any],
    audition: Mapping[str, Any],
    supervisor_review: Mapping[str, Any],
    fixture_results: Sequence[Mapping[str, Any]],
    user_approval_receipt: Mapping[str, Any] | None = None,
    canary_health: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Decide one lifecycle transition from immutable, hash-bound evidence."""

    try:
        package = CapabilityPackage.from_mapping(manifest)
    except CapabilityVaultError as exc:
        return {
            "schema_version": "capability-promotion-decision/v1",
            "status": "blocked",
            "blocking_findings": [f"invalid_manifest:{exc}"],
        }
    findings: list[str] = []
    if (current_status, target_status) not in PROMOTION_TARGETS:
        findings.append("invalid_promotion_transition")
    findings.extend(
        _binding_findings(
            static_audit,
            label="static_audit",
            package=package,
            required_schema="capability-static-audit/v1",
        )
    )
    findings.extend(
        _binding_findings(
            audition,
            label="audition",
            package=package,
            required_schema="capability-audition/v1",
        )
    )
    findings.extend(
        _binding_findings(
            supervisor_review,
            label="supervisor_review",
            package=package,
            required_schema="capability-supervisor-review/v1",
        )
    )
    fixture_findings, fixture_summary = _fixture_findings(fixture_results)
    findings.extend(fixture_findings)
    if package.requires_user_approval:
        approval_findings = (
            _binding_findings(
                user_approval_receipt,
                label="user_approval",
                package=package,
                required_schema="capability-user-approval/v1",
                require_pass=False,
            )
            if isinstance(user_approval_receipt, Mapping)
            else []
        )
        if (
            not isinstance(user_approval_receipt, Mapping)
            or user_approval_receipt.get("approved") is not True
        ):
            approval_findings.append("user_approval_required")
        findings.extend(approval_findings)
    if target_status == "active":
        findings.extend(
            _binding_findings(
                canary_health,
                label="canary_health",
                package=package,
                required_schema="capability-canary-health/v1",
            )
        )
    findings = sorted(set(findings))
    evidence = {
        "static_audit_sha256": _evidence_sha256(static_audit),
        "audition_sha256": _evidence_sha256(audition),
        "supervisor_review_sha256": _evidence_sha256(supervisor_review),
        "fixtures_sha256": _evidence_sha256(list(fixture_results)),
    }
    if user_approval_receipt is not None:
        evidence["user_approval_sha256"] = _evidence_sha256(
            user_approval_receipt
        )
    if canary_health is not None:
        evidence["canary_health_sha256"] = _evidence_sha256(canary_health)
    return {
        "schema_version": "capability-promotion-decision/v1",
        "status": "approved" if not findings else "blocked",
        "package_id": package.package_id,
        "version": package.version,
        "source_digest": package.source_digest,
        "transition": {"from": current_status, "to": target_status},
        "fixture_summary": fixture_summary,
        "approval": {
            "user_approval_required": package.requires_user_approval,
            "user_approval_present": isinstance(
                user_approval_receipt, Mapping
            )
            and user_approval_receipt.get("approved") is True,
        },
        "evidence": evidence,
        "blocking_findings": findings,
        "decided_at": _utc_now(),
    }


def evaluate_capability_rollback(
    manifest: Mapping[str, Any],
    *,
    current_status: str,
    health_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    """Select the declared rollback version after health failure or digest drift."""

    try:
        package = CapabilityPackage.from_mapping(manifest)
    except CapabilityVaultError as exc:
        return {
            "schema_version": "capability-rollback-decision/v1",
            "status": "blocked",
            "blocking_findings": [f"invalid_manifest:{exc}"],
        }
    findings: list[str] = []
    if current_status not in {"canary", "active"}:
        findings.append("rollback_requires_canary_or_active")
    bound_id = health_receipt.get("package_id") == package.package_id
    bound_version = health_receipt.get("version") == package.version
    if not bound_id:
        findings.append("health_receipt_package_id_mismatch")
    if not bound_version:
        findings.append("health_receipt_version_mismatch")
    drift = health_receipt.get("source_digest") != package.source_digest
    failed = health_receipt.get("status") not in {"pass", "healthy"}
    trigger = (
        "source_digest_drift"
        if drift
        else "health_failure"
        if failed
        else None
    )
    if trigger is None:
        findings.append("rollback_trigger_not_present")
    rollback_version = str(package.document.get("rollback_version") or "")
    if not rollback_version or rollback_version == package.version:
        findings.append("valid_rollback_version_required")
    findings = sorted(set(findings))
    return {
        "schema_version": "capability-rollback-decision/v1",
        "status": "approved" if not findings else "blocked",
        "package_id": package.package_id,
        "source_digest": package.source_digest,
        "current_status": current_status,
        "trigger": trigger,
        "rollback": {
            "from_version": package.version,
            "to_version": rollback_version,
            "resulting_status": "active",
        },
        "health_evidence_sha256": _evidence_sha256(health_receipt),
        "blocking_findings": findings,
        "decided_at": _utc_now(),
    }
