from __future__ import annotations

from pathlib import Path

import yaml

from agent_runtime.atomic_io import atomic_write_text, atomic_write_yaml
from agent_runtime.executors.ledger import record_execution_event
from agent_runtime.executors.models import ExecutionResultEnvelope
from agent_runtime.review import ReviewTarget, load_review_policy, run_three_e_review
from agent_runtime.review.models import ReviewVerdict


def ingest_execution_result(
    result_envelope_path: Path,
    output_dir: Path,
) -> ReviewTarget:
    data = yaml.safe_load(result_envelope_path.read_text(encoding="utf-8")) or {}
    envelope = ExecutionResultEnvelope(
        task_id=str(data.get("task_id") or ""),
        provider_id=str(data.get("provider_id") or ""),
        source=str(data.get("source") or ""),
        status=str(data.get("status") or "UNKNOWN"),
        changed_files=[str(item) for item in data.get("changed_files") or []],
        claimed_tests=[str(item) for item in data.get("claimed_tests") or []],
        output_artifacts=[str(item) for item in data.get("output_artifacts") or []],
        summary=str(data.get("summary") or ""),
        safety_attestation=dict(data.get("safety_attestation") or {}),
        review_target_dir=str(data.get("review_target_dir") or output_dir),
    )
    review_dir = output_dir / "review_input"
    review_dir.mkdir(parents=True, exist_ok=True)
    source_root = result_envelope_path.parent
    handoff_source = source_root.parent / "external_execution_handoff.md"
    handoff_text = handoff_source.read_text(encoding="utf-8") if handoff_source.exists() else "# External Agent Handoff\n\nMock/internal execution result.\n"
    atomic_write_text(review_dir / "external_handoff.md", handoff_text)
    ledger_source = source_root.parent / "execution_ledger.yml"
    if ledger_source.exists():
        atomic_write_text(review_dir / "skill_usage_ledger.yml", ledger_source.read_text(encoding="utf-8"))
        atomic_write_text(review_dir / "execution_ledger.yml", ledger_source.read_text(encoding="utf-8"))
    else:
        atomic_write_yaml(review_dir / "skill_usage_ledger.yml", {"task_id": envelope.task_id, "entries": []})
    atomic_write_yaml(review_dir / "execution_result_envelope.yml", data)
    atomic_write_text(review_dir / "result_summary.md", _render_review_summary(envelope))
    atomic_write_text(review_dir / "p1_acceptance_report.md", _render_review_summary(envelope))
    record_execution_event(
        output_dir / "execution_ledger.yml",
        envelope.task_id,
        "result_ingested",
        envelope.provider_id,
        "unknown",
        "unknown",
        envelope.status,
        ["execution result converted to P2-A review target"],
        ["review_input/external_handoff.md", "review_input/skill_usage_ledger.yml", "review_input/result_summary.md"],
    )
    return ReviewTarget(
        task_id=envelope.task_id,
        target_dir=review_dir,
        handoff_path=review_dir / "external_handoff.md",
        report_path=review_dir / "p1_acceptance_report.md",
        changed_files=envelope.changed_files,
        claimed_tests=envelope.claimed_tests,
    )


def review_execution_result_with_3e(
    review_target_dir: Path,
    review_output_dir: Path,
    policy_path: Path,
) -> ReviewVerdict:
    data_path = review_target_dir / "execution_result_envelope.yml"
    data = yaml.safe_load(data_path.read_text(encoding="utf-8")) if data_path.exists() else {}
    task_id = str((data or {}).get("task_id") or review_target_dir.name)
    changed_files = [str(item) for item in (data or {}).get("changed_files") or []]
    claimed_tests = [str(item) for item in (data or {}).get("claimed_tests") or []]
    target = ReviewTarget(
        task_id=task_id,
        target_dir=review_target_dir,
        handoff_path=review_target_dir / "external_handoff.md",
        report_path=review_target_dir / "p1_acceptance_report.md",
        changed_files=changed_files,
        claimed_tests=claimed_tests,
    )
    policy = load_review_policy(policy_path)
    report = run_three_e_review(target, policy, review_output_dir)
    ledger_path = review_target_dir.parent / "execution_ledger.yml"
    record_execution_event(
        ledger_path,
        task_id,
        "review_requested",
        str((data or {}).get("provider_id") or "unknown"),
        "unknown",
        "unknown",
        report.verdict.status,
        ["P2-A 3E review executed"],
        [str(report.markdown_path or ""), str(report.yaml_path or "")],
    )
    record_execution_event(
        ledger_path,
        task_id,
        "review_passed" if report.verdict.status in {"PASS", "PASS_WITH_WARNINGS"} else "review_failed",
        str((data or {}).get("provider_id") or "unknown"),
        "unknown",
        "unknown",
        report.verdict.status,
        report.verdict.reasons,
        [str(report.retry_handoff.path) if report.retry_handoff else ""],
    )
    return report.verdict


def _render_review_summary(envelope: ExecutionResultEnvelope) -> str:
    attest = envelope.safety_attestation
    tests = envelope.claimed_tests or ["No tests claimed."]
    return "\n".join(
        [
            "# Execution Result Review Summary",
            "",
            "## Summary",
            envelope.summary or "No summary provided.",
            "",
            "## Tests Run",
            *[f"- {item}" for item in tests],
            "",
            "## Safety Evidence",
            f"- external_scripts_executed: {str(attest.get('external_scripts_executed', None)).lower()}",
            f"- mcp_servers_started: {str(attest.get('mcp_servers_started', None)).lower()}",
            f"- remote_repos_cloned: {str(attest.get('remote_repos_cloned', None)).lower()}",
            f"- private_urls_accessed: {str(attest.get('private_urls_accessed', None)).lower()}",
            f"- secrets_exposed: {str(attest.get('secrets_exposed', None)).lower()}",
            f"- third_party_source_copied: {str(attest.get('third_party_source_copied', None)).lower()}",
            "",
            "## Known Limitations",
            "- External executor results are not accepted until P2-A review passes.",
            "",
            "## Verdict",
            f"- {envelope.status}",
            "",
        ]
    )
