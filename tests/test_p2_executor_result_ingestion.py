from pathlib import Path

import pytest
import yaml

from agent_runtime.executors import (
    ExecutionRequest,
    load_executor_providers,
    load_executor_router_policy,
    route_execution_request,
)
from agent_runtime.executors.authorization import assert_execution_plan_authorized
from agent_runtime.executors.handoff_bridge import create_execution_plan
from agent_runtime.executors.mock_executor import SAFE_ATTESTATION, run_mock_executor
from agent_runtime.executors.result_ingestion import ingest_execution_result, review_execution_result_with_3e


def _request(output_dir: Path):
    return ExecutionRequest(
        task_id="mock",
        task_type="repo_patch",
        summary="Mock",
        allowed_files=["tests/fixtures/p2_executor_router/mock_only.txt"],
        required_capabilities=["repo_patch"],
        bounded_scope=True,
        reversible=True,
        output_dir=output_dir,
    )


def _plan(request: ExecutionRequest, output_dir: Path):
    policy = load_executor_router_policy(Path("config/executor_router.yml"))
    providers = load_executor_providers(policy)
    decision = route_execution_request(request, providers, policy)
    return create_execution_plan(request, decision, policy, output_dir, providers)


def _run_mock(output_dir: Path):
    request = _request(output_dir)
    plan = _plan(request, output_dir)
    return run_mock_executor(request, plan, output_dir)


def test_mock_executor_writes_result_envelope(tmp_path):
    _run_mock(tmp_path)
    assert (tmp_path / "mock_result" / "execution_result_envelope.yml").is_file()


def test_mock_executor_rejects_request_changed_after_auto_approval(tmp_path):
    request = _request(tmp_path)
    plan = _plan(request, tmp_path)
    request.summary = "Changed after approval"

    with pytest.raises(PermissionError, match="execution_request_mismatch"):
        run_mock_executor(request, plan, tmp_path)

    assert not (tmp_path / "mock_result").exists()


def test_mock_executor_rejects_provider_changed_after_auto_approval(tmp_path):
    request = _request(tmp_path)
    plan = _plan(request, tmp_path)
    plan.selected_provider_id = "tampered.provider"

    with pytest.raises(PermissionError, match="approved_provider_missing"):
        run_mock_executor(request, plan, tmp_path)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("selected_provider_type", "api_model"),
        ("execution_mode", "approved_auto"),
    ],
)
def test_mock_executor_rejects_non_mock_plan_at_public_boundary(tmp_path, field, value):
    request = _request(tmp_path)
    plan = _plan(request, tmp_path)
    setattr(plan, field, value)

    with pytest.raises(PermissionError, match="invalid_mock_executor_plan"):
        run_mock_executor(request, plan, tmp_path)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("task_id", "tampered-task"),
        ("estimated_cost_usd", 0.01),
        ("estimated_risk", "critical"),
        ("review_required", False),
    ],
)
def test_mock_executor_rejects_plan_changed_after_auto_approval(tmp_path, field, value):
    request = _request(tmp_path)
    plan = _plan(request, tmp_path)
    setattr(plan, field, value)

    with pytest.raises(PermissionError, match="execution_plan_binding_mismatch"):
        run_mock_executor(request, plan, tmp_path)


def test_mock_executor_rejects_output_directory_changed_after_approval(tmp_path):
    approved_output = tmp_path / "approved"
    actual_output = tmp_path / "different"
    request = _request(approved_output)
    plan = _plan(request, approved_output)

    with pytest.raises(PermissionError, match="execution_plan_binding_mismatch"):
        run_mock_executor(request, plan, actual_output)


def test_execution_authorization_rejects_router_safety_change(tmp_path):
    request = _request(tmp_path)
    plan = _plan(request, tmp_path)
    policy = load_executor_router_policy(Path("config/executor_router.yml"))
    policy.safety["forbid_network_execution"] = not policy.safety.get("forbid_network_execution", False)

    with pytest.raises(PermissionError, match="execution_plan_binding_mismatch"):
        assert_execution_plan_authorized(request, plan, tmp_path, policy)


def test_mock_executor_does_not_modify_repo(tmp_path):
    _run_mock(tmp_path)
    assert not Path("tests/fixtures/p2_executor_router/mock_only.txt").exists()


def test_mock_executor_safety_attestation_all_false(tmp_path):
    _run_mock(tmp_path)
    data = yaml.safe_load((tmp_path / "mock_result" / "execution_result_envelope.yml").read_text())
    assert data["safety_attestation"] == SAFE_ATTESTATION


def test_result_ingestion_creates_review_target(tmp_path):
    _run_mock(tmp_path)
    target = ingest_execution_result(tmp_path / "mock_result" / "execution_result_envelope.yml", tmp_path)
    assert target.target_dir.name == "review_input"
    assert (target.target_dir / "external_handoff.md").is_file()
    assert (target.target_dir / "skill_usage_ledger.yml").is_file()


def test_execution_result_requires_p2_review(tmp_path):
    _run_mock(tmp_path)
    target = ingest_execution_result(tmp_path / "mock_result" / "execution_result_envelope.yml", tmp_path)
    assert not (target.target_dir / "accepted.yml").exists()


def test_review_bridge_passes_good_mock_result(tmp_path):
    _run_mock(tmp_path)
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
    _run_mock(tmp_path)
    ingest_execution_result(tmp_path / "mock_result" / "execution_result_envelope.yml", tmp_path)
    assert "accepted" not in (tmp_path / "execution_ledger.yml").read_text().lower()
