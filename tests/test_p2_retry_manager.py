from __future__ import annotations

from pathlib import Path

import yaml

from agent_runtime.executors import ExecutionRequest
from agent_runtime.retry.retry_manager import run_acceptance_retry_loop


ROOT = Path(__file__).resolve().parents[1]


def _request(task_id: str) -> ExecutionRequest:
    return ExecutionRequest(
        task_id=task_id,
        task_type="repo_patch",
        summary="Patch a small repo bug",
        repo_path=ROOT,
        allowed_files=["agent_runtime/retry/retry_manager.py"],
        forbidden_files=[".env", ".git/", "secrets/"],
        required_capabilities=["repo_patch"],
        requires_review=True,
        bounded_scope=True,
        reversible=True,
    )


def _run(tmp_path: Path, mode: str, task_id: str = "task"):
    return run_acceptance_retry_loop(
        _request(task_id),
        ROOT / "config" / "executor_router.yml",
        ROOT / "config" / "retry_policy.yml",
        ROOT / "config" / "review_policy.yml",
        tmp_path / task_id,
        mode=mode,
    )


def test_retry_loop_passes_first_attempt(tmp_path: Path):
    state = _run(tmp_path, "mock-pass-first", "pass_first")
    assert state.accepted is True
    assert len(state.attempts) == 1
    assert state.final_verdict == "PASS"
    assert (tmp_path / "pass_first" / "final_acceptance_receipt.yml").is_file()


def test_retry_loop_fail_then_pass(tmp_path: Path):
    state = _run(tmp_path, "mock-fail-then-pass", "fail_then_pass")
    assert state.accepted is True
    assert len(state.attempts) == 2
    assert state.attempts[0].retry_handoff
    assert state.final_verdict == "PASS"


def test_retry_loop_fails_until_max_attempts(tmp_path: Path):
    state = _run(tmp_path, "mock-fail-until-max", "fail_until_max")
    assert state.accepted is False
    assert state.status == "STOP_MAX_ATTEMPTS"
    assert len(state.attempts) == 3
    assert (tmp_path / "fail_until_max" / "final_rejection_receipt.yml").is_file()


def test_retry_loop_blocked_stops_immediately(tmp_path: Path):
    state = _run(tmp_path, "mock-blocked", "blocked")
    assert state.accepted is False
    assert state.status == "STOP_SAFETY_BLOCKED"
    assert len(state.attempts) == 1


def test_retry_loop_unreviewed_result_not_accepted(tmp_path: Path):
    state = _run(tmp_path, "dry-run", "dry")
    assert state.accepted is False
    assert state.status == "NEEDS_MANUAL_APPROVAL"
    assert not (tmp_path / "dry" / "final_acceptance_receipt.yml").exists()


def test_retry_loop_uses_p2_router(tmp_path: Path):
    _run(tmp_path, "mock-pass-first", "router")
    route = yaml.safe_load((tmp_path / "router" / "attempt_001" / "route_report.yml").read_text(encoding="utf-8"))
    assert route["decision"]["status"] == "ROUTED"
    assert route["plan"]["selected_provider_id"] == "agentlab.mock_patch"


def test_retry_loop_stops_cleanly_when_executor_policy_forbids_request(tmp_path: Path):
    request = _request("secret_blocked")
    request.contains_secrets = True

    state = run_acceptance_retry_loop(
        request,
        ROOT / "config" / "executor_router.yml",
        ROOT / "config" / "retry_policy.yml",
        ROOT / "config" / "review_policy.yml",
        tmp_path / "secret_blocked",
        mode="mock-pass-first",
    )

    assert state.status == "STOP_SAFETY_BLOCKED"
    assert state.accepted is False
    assert not (tmp_path / "secret_blocked" / "attempt_001" / "mock_result").exists()


def test_retry_loop_never_fabricates_mock_result_for_external_provider(tmp_path: Path):
    policy_data = yaml.safe_load((ROOT / "config" / "executor_router.yml").read_text())
    router = policy_data["executor_router"]
    router["routing"]["allow_mock_executor"] = False
    router["provider_priority"]["repo_patch"] = ["api.deepseek"]
    provider = next(item for item in router["providers"] if item["provider_id"] == "api.deepseek")
    provider["enabled"] = True
    provider["execution_mode"] = "approved_auto"
    provider["supports_auto_execution"] = True
    policy_path = tmp_path / "executor_router.yml"
    policy_path.write_text(yaml.safe_dump(policy_data, sort_keys=False), encoding="utf-8")
    request = _request("external_without_adapter")
    request.estimated_cost_usd = 0.05

    state = run_acceptance_retry_loop(
        request,
        policy_path,
        ROOT / "config" / "retry_policy.yml",
        ROOT / "config" / "review_policy.yml",
        tmp_path / "external_without_adapter",
        mode="mock-pass-first",
    )

    assert state.status == "NEEDS_MANUAL_APPROVAL"
    assert state.accepted is False
    assert not (tmp_path / "external_without_adapter" / "attempt_001" / "mock_result").exists()


def test_retry_loop_uses_p2_reviewer(tmp_path: Path):
    _run(tmp_path, "mock-pass-first", "reviewer")
    assert (tmp_path / "reviewer" / "attempt_001" / "review" / "review_report.yml").is_file()
    verdict = yaml.safe_load((tmp_path / "reviewer" / "attempt_001" / "review" / "review_verdict.yml").read_text(encoding="utf-8"))
    assert verdict["status"] == "PASS"
