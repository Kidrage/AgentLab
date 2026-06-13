from pathlib import Path

import yaml

from agent_runtime.executors import ExecutionPlan, ExecutionRequest
from agent_runtime.executors.mock_executor import SAFE_ATTESTATION, run_mock_executor
from agent_runtime.executors.result_ingestion import ingest_execution_result, review_execution_result_with_3e


def _plan():
    return ExecutionPlan(
        task_id="mock",
        selected_provider_id="agentlab.mock_patch",
        selected_provider_type="mock_executor",
        execution_mode="mock",
        approval_required=False,
        estimated_cost_usd=0.0,
        estimated_risk="low",
    )


def _request():
    return ExecutionRequest(task_id="mock", task_type="repo_patch", summary="Mock", allowed_files=["tests/fixtures/p2_executor_router/mock_only.txt"], required_capabilities=["repo_patch"])


def test_mock_executor_writes_result_envelope(tmp_path):
    run_mock_executor(_request(), _plan(), tmp_path)
    assert (tmp_path / "mock_result" / "execution_result_envelope.yml").is_file()


def test_mock_executor_does_not_modify_repo(tmp_path):
    run_mock_executor(_request(), _plan(), tmp_path)
    assert not Path("tests/fixtures/p2_executor_router/mock_only.txt").exists()


def test_mock_executor_safety_attestation_all_false(tmp_path):
    run_mock_executor(_request(), _plan(), tmp_path)
    data = yaml.safe_load((tmp_path / "mock_result" / "execution_result_envelope.yml").read_text())
    assert data["safety_attestation"] == SAFE_ATTESTATION


def test_result_ingestion_creates_review_target(tmp_path):
    run_mock_executor(_request(), _plan(), tmp_path)
    target = ingest_execution_result(tmp_path / "mock_result" / "execution_result_envelope.yml", tmp_path)
    assert target.target_dir.name == "review_input"
    assert (target.target_dir / "external_handoff.md").is_file()
    assert (target.target_dir / "skill_usage_ledger.yml").is_file()


def test_execution_result_requires_p2_review(tmp_path):
    run_mock_executor(_request(), _plan(), tmp_path)
    target = ingest_execution_result(tmp_path / "mock_result" / "execution_result_envelope.yml", tmp_path)
    assert not (target.target_dir / "accepted.yml").exists()


def test_review_bridge_passes_good_mock_result(tmp_path):
    run_mock_executor(_request(), _plan(), tmp_path)
    target = ingest_execution_result(tmp_path / "mock_result" / "execution_result_envelope.yml", tmp_path)
    verdict = review_execution_result_with_3e(target.target_dir, tmp_path / "review", Path("config/review_policy.yml"))
    assert verdict.status in {"PASS", "PASS_WITH_WARNINGS"}


def test_review_bridge_generates_retry_handoff_on_bad_result(tmp_path):
    bad = {
        "task_id": "bad",
        "provider_id": "agentlab.mock_patch",
        "source": "mock_executor",
        "status": "PASS",
        "changed_files": [".env"],
        "claimed_tests": [],
        "output_artifacts": [],
        "summary": "Bad",
        "safety_attestation": {"secrets_exposed": True},
        "review_target_dir": "review_input",
    }
    path = tmp_path / "execution_result_envelope.yml"
    path.write_text(yaml.safe_dump(bad), encoding="utf-8")
    target = ingest_execution_result(path, tmp_path)
    verdict = review_execution_result_with_3e(target.target_dir, tmp_path / "review", Path("config/review_policy.yml"))
    assert verdict.status in {"NEEDS_REVISION", "FAIL", "BLOCKED"}
    assert (tmp_path / "review" / "retry_handoff.md").is_file()


def test_unreviewed_result_not_marked_accepted(tmp_path):
    run_mock_executor(_request(), _plan(), tmp_path)
    ingest_execution_result(tmp_path / "mock_result" / "execution_result_envelope.yml", tmp_path)
    assert "accepted" not in (tmp_path / "execution_ledger.yml").read_text().lower()
