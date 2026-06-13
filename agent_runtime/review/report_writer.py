from __future__ import annotations

from pathlib import Path

from agent_runtime.atomic_io import atomic_write_text, atomic_write_yaml
from agent_runtime.review.models import ReviewReport, to_plain_data


def write_review_report(report: ReviewReport, output_dir: Path) -> ReviewReport:
    output_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = output_dir / "review_report.md"
    yaml_path = output_dir / "review_report.yml"
    atomic_write_text(markdown_path, render_review_report(report))
    atomic_write_yaml(yaml_path, to_plain_data(report))
    report.markdown_path = markdown_path
    report.yaml_path = yaml_path
    return report


def render_review_report(report: ReviewReport) -> str:
    summary = report.summary
    findings = report.findings
    verdict = report.verdict
    retry_text = str(report.retry_handoff.path) if report.retry_handoff else "Not required."
    artifact_lines = [
        f"- {artifact.path}: {'present' if artifact.exists else 'missing'}"
        for artifact in summary.artifacts
    ] or ["- No artifacts scanned."]
    finding_lines = [
        f"- {finding.finding_id} ({finding.severity}/{finding.category}): {finding.message}"
        for finding in findings
    ] or ["- No findings."]
    action_lines = [f"- {item}" for item in verdict.required_actions] or ["- No required actions."]
    lines = [
        "# AgentLab 3E Review Report",
        "",
        "## Summary",
        f"Review target `{summary.task_id}` completed with verdict `{verdict.status}`.",
        "",
        "## Explore",
        f"- target_dir: {summary.target_dir}",
        f"- required artifacts present: {', '.join(summary.required_artifacts_present) or 'none'}",
        f"- required artifacts missing: {', '.join(summary.required_artifacts_missing) or 'none'}",
        f"- claimed tests: {', '.join(summary.claimed_tests) or 'none'}",
        *artifact_lines,
        "",
        "## Examine Findings",
        *finding_lines,
        "",
        "## Verdict",
        verdict.status,
        "",
        "## Required Actions",
        *action_lines,
        "",
        "## Retry Handoff",
        retry_text,
        "",
        "## Safety Notes",
        "- Review is deterministic and does not execute external tools.",
        "- Safety checks inspect submitted text evidence for forbidden affirmative claims.",
        "",
        "## Known Limitations",
        "- No real external executor integration.",
        "- No automatic code repair.",
        "- Safety checks are text-evidence based and conservative.",
        "",
    ]
    return "\n".join(lines)
