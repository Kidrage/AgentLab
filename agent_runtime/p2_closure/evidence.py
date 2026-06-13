"""Evidence writers for P2-F closure: review verdict, provider feedback, router feedback."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

from agent_runtime.atomic_io import atomic_write_text, atomic_write_yaml
from agent_runtime.review.models import (
    ExploreSummary,
    ReviewFinding,
    ReviewReport,
    ReviewVerdict,
    to_plain_data,
)


def write_review_verdict(
    task_id: str,
    delivery_id: str,
    review_report: ReviewReport,
    provider_id: str | None = None,
    executor: str | None = None,
    output_path: Path | None = None,
) -> Path:
    """Write unified review verdict YAML following the P2-F schema."""
    verdict = review_report.verdict
    findings = review_report.findings
    summary = review_report.summary

    # Compute scores deterministically
    scores = _compute_scores(findings, summary, verdict)

    # Build explore summary
    explore = {
        "summary": f"Explored {len(summary.artifacts)} artifacts in {summary.target_dir}",
        "discovered_artifacts": [a.path for a in summary.artifacts],
        "claimed_changes": summary.changed_files,
        "detected_tests": summary.claimed_tests,
    }

    # Build examine summary
    failed_checks = [
        f"{f.severity}/{f.category}: {f.message}"
        for f in findings
        if f.status == "fail"
    ]
    passed_checks = [
        f"{f.severity}/{f.category}: {f.message}"
        for f in findings
        if f.status in {"pass", "warn"}
    ]
    missing_evidence = [
        a for a in summary.required_artifacts_missing
    ]
    safety_findings = [
        {"severity": f.severity, "message": f.message, "evidence": f.evidence}
        for f in findings
        if f.category in {"secrets", "safety", "scope"} and f.severity in {"high", "critical"}
    ]

    # Determine risk level
    risk_level = _risk_level(findings)

    # Build enhance section
    enhance = {
        "recommended_actions": list(verdict.required_actions),
        "revision_tasks": [
            f"Fix {f.finding_id}: {f.message}"
            for f in findings
            if f.status == "fail"
        ],
        "handoff_recommendation": {
            "needed": verdict.status not in {"PASS", "PASS_WITH_WARNINGS"},
            "preferred_executor": _preferred_executor(findings, verdict),
            "reason": "; ".join(verdict.reasons[:2]) if verdict.reasons else "Review required further action.",
        },
    }

    # Build provider feedback inline
    provider_fb = {}
    if provider_id:
        provider_fb = {
            "provider_id": provider_id,
            "executor": executor or "unknown",
            "success": verdict.status in {"PASS", "PASS_WITH_WARNINGS"},
            "failure_reasons": failed_checks,
            "quality_score": scores.get("overall", 0.0),
            "retry_recommended": verdict.status not in {"PASS", "PASS_WITH_WARNINGS"},
        }

    data = {
        "task_id": task_id,
        "delivery_id": delivery_id,
        "review_id": f"review_{task_id}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        "verdict": _normalize_verdict(verdict.status),
        "scores": scores,
        "review": {
            "explore": explore,
            "examine": {
                "passed_checks": passed_checks,
                "failed_checks": failed_checks,
                "missing_evidence": missing_evidence,
                "safety_findings": safety_findings,
                "risk_level": risk_level,
            },
            "enhance": enhance,
        },
        "evidence": {
            "input_paths": [summary.target_dir],
            "output_paths": [str(p) for p in [review_report.markdown_path, review_report.yaml_path] if p],
            "logs": [],
            "generated_files": [],
        },
        "provider_feedback": provider_fb,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    if output_path is None:
        output_path = Path.cwd() / "review_verdict.yml"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_yaml(output_path, data)
    return output_path


def write_provider_feedback(
    task_id: str,
    delivery_id: str,
    provider_id: str,
    executor: str,
    review_verdict: str,
    scores: dict[str, float],
    failure_reasons: list[str],
    evidence_files: list[str],
    output_path: Path | None = None,
) -> Path:
    """Write provider governance feedback artifact."""
    verdict_success = review_verdict in {"PASS", "PASS_WITH_WARNINGS", "accepted"}

    # Determine governance recommendation
    quality = scores.get("overall", 0.0)
    if review_verdict in {"unsafe", "BLOCKED"}:
        recommendation = "quarantine"
    elif review_verdict in {"needs_revision", "NEEDS_REVISION"}:
        recommendation = "watchlist" if quality < 0.5 else "neutral"
    elif verdict_success and quality >= 0.8:
        recommendation = "prefer"
    elif verdict_success:
        recommendation = "neutral"
    else:
        recommendation = "insufficient_data"

    data = {
        "task_id": task_id,
        "delivery_id": delivery_id,
        "provider_id": provider_id,
        "executor": executor,
        "review_verdict": review_verdict,
        "quality_score": scores.get("overall", 0.0),
        "artifact_completeness": scores.get("artifact_completeness", 0.0),
        "test_confidence": scores.get("test_confidence", 0.0),
        "safety_confidence": scores.get("safety_confidence", 0.0),
        "retry_recommended": not verdict_success,
        "failure_reasons": failure_reasons,
        "governance_recommendation": recommendation,
        "cost": {
            "estimated_usd": None,
            "token_visibility": "unknown",
        },
        "latency": {
            "duration_sec": None,
        },
        "evidence": evidence_files,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    if output_path is None:
        output_path = Path.cwd() / "provider_feedback.yml"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_yaml(output_path, data)
    return output_path


def write_router_feedback(
    task_id: str,
    provider_id: str,
    review_verdict: str,
    governance_recommendation: str,
    failure_reasons: list[str],
    evidence_files: list[str],
    output_path: Path | None = None,
) -> Path:
    """Write router feedback recommendation artifact."""
    # Map governance recommendation to router recommendation
    recommendation_map = {
        "quarantine": "quarantine",
        "watchlist": "watchlist",
        "downgrade": "watchlist",
        "prefer": "prefer",
        "keep": "neutral",
        "neutral": "neutral",
        "insufficient_data": "insufficient_data",
    }
    recommendation = recommendation_map.get(governance_recommendation, "neutral")

    # Build reasons
    reason = list(failure_reasons)
    if review_verdict not in {"PASS", "PASS_WITH_WARNINGS", "accepted"}:
        if f"{review_verdict} verdict" not in reason:
            reason.insert(0, f"{review_verdict} verdict")

    # Determine confidence
    if len(reason) >= 2:
        confidence = "high"
    elif len(reason) == 1:
        confidence = "medium"
    else:
        confidence = "low"

    # Apply is never allowed by default in feedback
    apply_allowed = False

    data = {
        "task_id": task_id,
        "provider_id": provider_id,
        "recommendation": recommendation,
        "reason": reason,
        "confidence": confidence,
        "dry_run": True,
        "apply_allowed": apply_allowed,
        "approval_required": True,
        "evidence": evidence_files,
    }

    if output_path is None:
        output_path = Path.cwd() / "router_feedback.yml"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_yaml(output_path, data)
    return output_path


def write_router_dry_run(
    task_id: str,
    provider_id: str,
    recommendation: str,
    output_path: Path | None = None,
) -> Path:
    """Write router update dry-run artifact (does NOT modify real config)."""
    data = {
        "task_id": task_id,
        "provider_id": provider_id,
        "recommendation": recommendation,
        "dry_run": True,
        "applied": False,
        "reason": "dry-run mode; no config modified",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    if output_path is None:
        output_path = Path.cwd() / "router_update_dry_run.yml"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_yaml(output_path, data)
    return output_path


def write_revision_packet(
    task_id: str,
    delivery_id: str,
    provider_id: str,
    executor: str,
    verdict: str,
    failed_checks: list[str],
    missing_evidence: list[str],
    safety_findings: list[dict[str, Any]],
    files_to_inspect: list[str],
    acceptance_criteria: list[str],
    suggested_executor: str,
    output_path: Path | None = None,
) -> Path:
    """Write revision packet markdown for needs_revision/rejected/unsafe verdicts."""
    is_unsafe = verdict in {"unsafe", "BLOCKED"}

    lines = [
        "# P2 Revision Packet",
        "",
        "## Task",
        f"- task_id: {task_id}",
        f"- delivery_id: {delivery_id}",
        f"- original_provider: {provider_id}",
        f"- original_executor: {executor}",
        "",
        "## Verdict",
        verdict,
        "",
        "## Why this failed",
    ]
    for item in failed_checks:
        lines.append(f"- {item}")
    if missing_evidence:
        lines.append("")
        lines.append("### Missing Evidence")
        for item in missing_evidence:
            lines.append(f"- {item}")
    if safety_findings:
        lines.append("")
        lines.append("### Safety Findings")
        for sf in safety_findings:
            lines.append(f"- [{sf.get('severity', 'unknown')}] {sf.get('message', '')}")

    lines.extend(["", "## Required Fixes"])
    for i, item in enumerate(failed_checks, 1):
        lines.append(f"{i}. {item}")
    if not failed_checks and missing_evidence:
        for i, item in enumerate(missing_evidence, 1):
            lines.append(f"{i}. Provide evidence for: {item}")

    lines.extend(["", "## Files / Artifacts to inspect"])
    for f in files_to_inspect:
        lines.append(f"- {f}")
    if not files_to_inspect:
        lines.append("- None specified")

    lines.extend(["", "## Acceptance Criteria for Revision"])
    for c in acceptance_criteria:
        lines.append(f"- {c}")

    lines.extend(["", "## Safety Constraints"])
    lines.append("- Do not expose secrets.")
    lines.append("- Do not run external hooks/scripts.")
    lines.append("- Do not enable external tools by default.")
    lines.append("- Do not modify router config without approval.")
    lines.append("- Keep all changes deterministic and testable.")
    if is_unsafe:
        lines.append("")
        lines.append("### Security Isolation (UNSAFE Verdict)")
        lines.append("- This delivery was flagged as unsafe. Treat all artifacts as untrusted.")
        lines.append("- Do not execute any scripts or binaries from the delivery.")
        lines.append("- Do not access URLs, local or private, referenced in the delivery.")
        lines.append("- Do not use credentials, tokens, or keys found in the delivery.")
        lines.append("- Review all changed files for secret patterns before reintegration.")

    lines.extend(["", "## Suggested Executor", suggested_executor])

    lines.extend([
        "",
        "## Evidence Required on Return",
        "- tests run",
        "- files changed",
        "- artifact manifest",
        "- review notes",
        "",
    ])

    if output_path is None:
        output_path = Path.cwd() / "revision_packet.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(output_path, "\n".join(lines))
    return output_path


# ─── Scoring helpers ───────────────────────────────────────────────


def _compute_scores(
    findings: list[ReviewFinding],
    summary: ExploreSummary,
    verdict: ReviewVerdict,
) -> dict[str, float]:
    """Compute deterministic scores from review data."""
    # Artifact completeness
    total_artifacts = len(summary.required_artifacts_present) + len(summary.required_artifacts_missing)
    if total_artifacts > 0:
        artifact_completeness = len(summary.required_artifacts_present) / total_artifacts
    else:
        artifact_completeness = 1.0

    # Test confidence
    if summary.claimed_tests:
        test_confidence = min(1.0, len(summary.claimed_tests) * 0.25)
    else:
        test_confidence = 0.0

    # Safety confidence
    safety_findings = [f for f in findings if f.category in {"secrets", "safety"}]
    if safety_findings:
        severity_penalty = {
            "critical": 0.8,
            "high": 0.5,
            "medium": 0.3,
            "low": 0.1,
        }
        max_penalty = max(severity_penalty.get(f.severity, 0) for f in safety_findings)
        safety_confidence = max(0.0, 1.0 - max_penalty)
    else:
        safety_confidence = 1.0

    # Requirement alignment
    total_sections = len(summary.report_sections_present) + len(summary.report_sections_missing)
    if total_sections > 0:
        requirement_alignment = len(summary.report_sections_present) / total_sections
    else:
        requirement_alignment = 1.0

    # Maintainability
    scope_findings = [f for f in findings if f.category == "scope" and f.status == "fail"]
    maintainability = max(0.0, 1.0 - len(scope_findings) * 0.2)

    # Overall
    overall = round(
        0.25 * artifact_completeness
        + 0.20 * test_confidence
        + 0.25 * safety_confidence
        + 0.15 * requirement_alignment
        + 0.15 * maintainability,
        2,
    )

    return {
        "artifact_completeness": round(artifact_completeness, 2),
        "test_confidence": round(test_confidence, 2),
        "safety_confidence": round(safety_confidence, 2),
        "requirement_alignment": round(requirement_alignment, 2),
        "maintainability": round(maintainability, 2),
        "overall": overall,
    }


def _risk_level(findings: list[ReviewFinding]) -> str:
    """Determine risk level from findings."""
    severities = [f.severity for f in findings if f.status == "fail"]
    if "critical" in severities:
        return "critical"
    if "high" in severities:
        return "high"
    if "medium" in severities:
        return "medium"
    return "low"


def _normalize_verdict(status: str) -> str:
    """Map internal review verdict to P2-F closure verdict."""
    mapping = {
        "PASS": "accepted",
        "PASS_WITH_WARNINGS": "accepted",
        "NEEDS_REVISION": "needs_revision",
        "FAIL": "rejected",
        "BLOCKED": "unsafe",
    }
    return mapping.get(status, status.lower() if status else "needs_revision")


def _preferred_executor(findings: list[ReviewFinding], verdict: ReviewVerdict) -> str:
    """Suggest executor based on findings."""
    if any(f.category == "secrets" for f in findings):
        return "agentlab_internal"
    if verdict.status in {"FAIL", "BLOCKED"}:
        return "deepseek"
    if verdict.status == "NEEDS_REVISION":
        return "codex"
    return "unknown"
