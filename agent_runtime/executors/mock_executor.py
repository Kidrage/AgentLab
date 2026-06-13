from __future__ import annotations

from pathlib import Path

from agent_runtime.atomic_io import atomic_write_text, atomic_write_yaml
from agent_runtime.executors.ledger import record_execution_event
from agent_runtime.executors.models import ExecutionPlan, ExecutionRequest, ExecutionResultEnvelope, to_plain_data


SAFE_ATTESTATION = {
    "external_scripts_executed": False,
    "mcp_servers_started": False,
    "remote_repos_cloned": False,
    "private_urls_accessed": False,
    "secrets_exposed": False,
    "third_party_source_copied": False,
}


def run_mock_executor(
    request: ExecutionRequest,
    plan: ExecutionPlan,
    output_dir: Path,
) -> ExecutionResultEnvelope:
    mock_dir = output_dir / "mock_result"
    mock_dir.mkdir(parents=True, exist_ok=True)
    changed_files = request.allowed_files[:1] or ["tests/fixtures/p2_executor_router/mock_only.txt"]
    claimed_tests = ["python -m pytest -q tests/test_p2_executor_router.py"]
    summary = (
        "Deterministic mock executor result. No repository source files were modified; "
        "artifacts were written only inside the requested output directory."
    )
    atomic_write_text(
        mock_dir / "result_summary.md",
        "\n".join(
            [
                "# Result Summary",
                "",
                "## Summary",
                summary,
                "",
                "## Tests Run",
                "- python -m pytest -q tests/test_p2_executor_router.py (mock claimed; not executed by mock executor)",
                "",
                "## Safety Evidence",
                "- external_scripts_executed: false",
                "- mcp_servers_started: false",
                "- remote_repos_cloned: false",
                "- private_urls_accessed: false",
                "- secrets_exposed: false",
                "- third_party_source_copied: false",
                "",
                "## Known Limitations",
                "- Mock executor does not edit repository code.",
                "",
                "## Verdict",
                "- PASS",
                "",
            ]
        ),
    )
    atomic_write_yaml(mock_dir / "changed_files.yml", {"changed_files": changed_files})
    atomic_write_yaml(mock_dir / "claimed_tests.yml", {"claimed_tests": claimed_tests})
    envelope = ExecutionResultEnvelope(
        task_id=request.task_id,
        provider_id=plan.selected_provider_id,
        source="mock_executor",
        status="PASS",
        changed_files=changed_files,
        claimed_tests=claimed_tests,
        output_artifacts=[
            "mock_result/result_summary.md",
            "mock_result/changed_files.yml",
            "mock_result/claimed_tests.yml",
        ],
        summary=summary,
        safety_attestation=dict(SAFE_ATTESTATION),
        review_target_dir=str(output_dir / "review_input"),
    )
    atomic_write_yaml(mock_dir / "execution_result_envelope.yml", to_plain_data(envelope))
    atomic_write_yaml(output_dir / "execution_result_envelope.yml", to_plain_data(envelope))
    record_execution_event(
        output_dir / "execution_ledger.yml",
        request.task_id,
        "mock_executed",
        plan.selected_provider_id,
        plan.selected_provider_type,
        plan.execution_mode,
        envelope.status,
        [summary],
        [
            "mock_result/result_summary.md",
            "mock_result/changed_files.yml",
            "mock_result/claimed_tests.yml",
            "mock_result/execution_result_envelope.yml",
        ],
    )
    return envelope
