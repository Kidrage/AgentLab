from __future__ import annotations

from pathlib import Path

import yaml

from agent_runtime.atomic_io import atomic_write_text, atomic_write_yaml
from agent_runtime.review.evidence_loader import collect_artifact_evidence
from agent_runtime.review.models import (
    ExploreSummary,
    RetryHandoff,
    ReviewFinding,
    ReviewReport,
    ReviewTarget,
    ReviewVerdict,
    to_plain_data,
)
from agent_runtime.review.policy import ReviewPolicy
from agent_runtime.review.risk_rules import safety_findings, scope_findings


SEVERITY_ORDER = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
VERDICT_BY_SEVERITY = {
    "critical": "BLOCKED",
    "high": "FAIL",
    "medium": "NEEDS_REVISION",
    "low": "PASS_WITH_WARNINGS",
}


def explore_review_target(
    target: ReviewTarget,
    policy: ReviewPolicy,
    output_dir: Path | None = None,
) -> ExploreSummary:
    artifacts, text_evidence = collect_artifact_evidence(target, policy)
    required_present = [name for name in policy.required_artifacts if (target.target_dir / name).is_file()]
    required_missing = [name for name in policy.required_artifacts if name not in required_present]
    optional_present = [name for name in policy.optional_artifacts if (target.target_dir / name).is_file()]
    report_text = _primary_report_text(target, text_evidence)
    sections_present = [
        section for section in policy.required_report_sections if _has_markdown_section(report_text, section)
    ]
    sections_missing = [
        section for section in policy.required_report_sections if section not in sections_present
    ]
    changed_files = target.changed_files or _extract_changed_files(text_evidence)
    claimed_tests = target.claimed_tests or _extract_claimed_tests(text_evidence)

    summary = ExploreSummary(
        task_id=target.task_id,
        target_dir=str(target.target_dir),
        artifacts=artifacts,
        required_artifacts_present=required_present,
        required_artifacts_missing=required_missing,
        optional_artifacts_present=optional_present,
        changed_files=changed_files,
        claimed_tests=claimed_tests,
        report_sections_present=sections_present,
        report_sections_missing=sections_missing,
        text_evidence=text_evidence,
    )
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "explore_summary.yml"
        atomic_write_yaml(path, to_plain_data(summary))
        summary.output_path = str(path)
    return summary


def examine_review_target(
    target: ReviewTarget,
    summary: ExploreSummary,
    policy: ReviewPolicy,
) -> list[ReviewFinding]:
    findings: list[ReviewFinding] = []
    for artifact in summary.required_artifacts_missing:
        findings.append(
            ReviewFinding(
                finding_id=f"missing-artifact-{artifact}",
                severity="high",
                category="evidence",
                message=f"Required artifact is missing: {artifact}",
                evidence=[artifact],
                recommendation="Regenerate the delivery with all required review artifacts.",
            )
        )

    for section in summary.report_sections_missing:
        findings.append(
            ReviewFinding(
                finding_id=f"missing-report-section-{section.lower().replace(' ', '-')}",
                severity="medium",
                category="evidence",
                message=f"Required report section is missing: {section}",
                evidence=[section],
                recommendation="Add the missing report section with concrete evidence.",
            )
        )

    if not summary.claimed_tests:
        findings.append(
            ReviewFinding(
                finding_id="claimed-tests-empty",
                severity="medium",
                category="tests",
                message="No claimed tests were found in the delivery evidence.",
                evidence=["claimed_tests=[]"],
                recommendation="List the validation commands and results in the report.",
            )
        )
    elif not _tests_match_report(summary.claimed_tests, summary.text_evidence):
        findings.append(
            ReviewFinding(
                finding_id="claimed-tests-report-mismatch",
                severity="medium",
                category="tests",
                message="Claimed tests are not reflected in the report evidence.",
                evidence=list(summary.claimed_tests),
                recommendation="Ensure claimed_tests and report Tests Run agree.",
            )
        )

    findings.extend(safety_findings(summary.text_evidence, policy))
    findings.extend(scope_findings(summary.changed_files, summary.text_evidence, policy))
    return _dedupe_by_id(findings)


def derive_review_verdict(findings: list[ReviewFinding], policy: ReviewPolicy) -> ReviewVerdict:
    if not findings:
        return ReviewVerdict(status="PASS", reasons=["No review findings."], required_actions=[])

    worst = max(findings, key=lambda finding: SEVERITY_ORDER.get(finding.severity, 0))
    status = policy.verdict_thresholds.get(f"{worst.severity}_finding") or VERDICT_BY_SEVERITY.get(
        worst.severity,
        "PASS",
    )
    reasons = [
        f"{finding.severity.upper()} {finding.category}: {finding.message}"
        for finding in findings
        if finding.status in {"warn", "fail"}
    ]
    required_actions = [
        finding.recommendation
        for finding in findings
        if finding.status == "fail" and finding.recommendation
    ]
    return ReviewVerdict(status=status, reasons=reasons, required_actions=list(dict.fromkeys(required_actions)))


def enhance_review_result(
    target: ReviewTarget,
    summary: ExploreSummary,
    findings: list[ReviewFinding],
    verdict: ReviewVerdict,
    policy: ReviewPolicy,
    output_dir: Path | None = None,
) -> RetryHandoff | None:
    if verdict.status in {"PASS", "PASS_WITH_WARNINGS"}:
        return None
    if policy.retry_handoff.get("enabled", True) is not True:
        return None

    output_root = output_dir or target.target_dir
    output_root.mkdir(parents=True, exist_ok=True)
    failed = [finding for finding in findings if finding.status == "fail"]
    commands = [
        "python -m compileall agent_runtime agentlab_app.py",
        "python -m pytest -q",
        f"python scripts/p2_review_check.py --target {target.target_dir}",
    ]
    criteria = [
        "All required artifacts are present.",
        "All required report sections include concrete evidence.",
        "Safety evidence contains no forbidden actions, private/local/file URL access, or secret-like values.",
        "Changed files avoid forbidden paths and explain high-risk path changes.",
        "The next 3E review verdict is PASS or PASS_WITH_WARNINGS.",
    ]
    handoff = RetryHandoff(
        path=output_root / "retry_handoff.md",
        failed_findings=failed,
        required_fixes=list(dict.fromkeys(verdict.required_actions)),
        reproduction_commands=commands,
        acceptance_criteria=criteria,
    )
    atomic_write_text(handoff.path, _render_retry_handoff(handoff, policy))
    return handoff


def run_three_e_review(
    target: ReviewTarget,
    policy: ReviewPolicy,
    output_dir: Path,
) -> ReviewReport:
    from agent_runtime.review.report_writer import write_review_report

    summary = explore_review_target(target, policy, output_dir=output_dir)
    findings = examine_review_target(target, summary, policy)
    verdict = derive_review_verdict(findings, policy)
    atomic_write_yaml(output_dir / "review_verdict.yml", to_plain_data(verdict))
    retry = enhance_review_result(target, summary, findings, verdict, policy, output_dir=output_dir)
    report = ReviewReport(target=target, summary=summary, findings=findings, verdict=verdict, retry_handoff=retry)
    write_review_report(report, output_dir)
    return report


def _render_retry_handoff(handoff: RetryHandoff, policy: ReviewPolicy) -> str:
    failed_lines = [
        f"- {finding.finding_id} ({finding.severity}/{finding.category}): {finding.message}"
        for finding in handoff.failed_findings
    ] or ["- No failed findings were provided."]
    fix_lines = [f"- {item}" for item in handoff.required_fixes] or ["- Resolve all failed review findings."]
    command_lines = [f"- `{command}`" for command in handoff.reproduction_commands]
    criteria_lines = [f"- {item}" for item in handoff.acceptance_criteria]
    scope_limit = "Do not add new features, expand scope, or modify unrelated modules."
    if policy.retry_handoff.get("forbid_scope_expansion", True) is not True:
        scope_limit = "Keep the retry scoped to failed review findings."
    lines = [
        "# Retry Handoff",
        "",
        "## Why this failed",
        *failed_lines,
        "",
        "## Required Fixes",
        *fix_lines,
        "",
        "## Scope Limits",
        f"- {scope_limit}",
        "",
        "## Reproduction Commands",
        *command_lines,
        "",
        "## Acceptance Criteria",
        *criteria_lines,
        "",
        "## Safety Constraints",
        "- Do not execute external scripts.",
        "- Do not start MCP servers.",
        "- Do not clone remote repositories.",
        "- Do not access private, local, or file URLs.",
        "- Do not expose secrets.",
        "- Do not copy third-party source code.",
        "",
    ]
    return "\n".join(lines)


def _primary_report_text(target: ReviewTarget, text_evidence: dict[str, str]) -> str:
    if target.report_path:
        report_name = target.report_path.name
        if report_name in text_evidence:
            return text_evidence[report_name]
    for name in ("p1_acceptance_report.md", "review_report.md", "external_handoff.md"):
        if name in text_evidence:
            return text_evidence[name]
    return "\n".join(text_evidence.values())


def _has_markdown_section(text: str, section: str) -> bool:
    needle = f"## {section}".lower()
    return any(line.strip().lower() == needle for line in text.splitlines())


def _extract_claimed_tests(text_evidence: dict[str, str]) -> list[str]:
    tests: list[str] = []
    for text in text_evidence.values():
        in_tests = False
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.lower().startswith("## tests run"):
                in_tests = True
                continue
            if in_tests and stripped.startswith("## "):
                in_tests = False
            if in_tests and stripped.startswith("-"):
                item = stripped.lstrip("- ").strip()
                if item:
                    tests.append(_strip_command_prefix(item))
    return list(dict.fromkeys(tests))


def _extract_changed_files(text_evidence: dict[str, str]) -> list[str]:
    changed: list[str] = []
    for name, text in text_evidence.items():
        if name.endswith((".yml", ".yaml")):
            try:
                data = yaml.safe_load(text) or {}
            except Exception:
                data = {}
            raw = data.get("changed_files") if isinstance(data, dict) else None
            if isinstance(raw, list):
                for item in raw:
                    if isinstance(item, str):
                        changed.append(item)
                    elif isinstance(item, dict) and item.get("path"):
                        changed.append(str(item["path"]))
        in_changed = False
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.lower().startswith(("## changed files", "## modified files")):
                in_changed = True
                continue
            if in_changed and stripped.startswith("## "):
                in_changed = False
            if in_changed and stripped.startswith("-"):
                item = stripped.lstrip("- ").strip()
                if item and not item.lower().startswith("none"):
                    changed.append(item.split(":", maxsplit=1)[0].strip())
    return list(dict.fromkeys(changed))


def _tests_match_report(claimed_tests: list[str], text_evidence: dict[str, str]) -> bool:
    combined = "\n".join(text_evidence.values()).lower()
    return all(test.lower().strip("`") in combined for test in claimed_tests)


def _strip_command_prefix(value: str) -> str:
    value = value.strip("`")
    if value.lower().startswith("command:"):
        return value.split(":", maxsplit=1)[1].strip().strip("`")
    return value


def _dedupe_by_id(findings: list[ReviewFinding]) -> list[ReviewFinding]:
    seen: set[str] = set()
    result: list[ReviewFinding] = []
    for finding in findings:
        if finding.finding_id not in seen:
            seen.add(finding.finding_id)
            result.append(finding)
    return result
