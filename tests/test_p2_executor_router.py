from pathlib import Path

from agent_runtime.executors import ExecutionRequest, load_executor_providers, load_executor_router_policy, route_execution_request


def _request(task_type="repo_patch", capability="repo_patch"):
    return ExecutionRequest(task_id="task", task_type=task_type, summary="Patch a bug", required_capabilities=[capability])


def test_router_selects_mock_executor_for_repo_patch():
    policy = load_executor_router_policy(Path("config/executor_router.yml"))
    decision = route_execution_request(_request(), load_executor_providers(policy), policy)
    assert decision.status == "ROUTED"
    assert decision.selected_provider_id == "agentlab.mock_patch"


def test_router_manual_codex_requires_approval():
    policy = load_executor_router_policy(Path("config/executor_router.yml"))
    policy.routing["allow_mock_executor"] = False
    policy.provider_priority["architecture_review"] = ["manual.codex"]
    decision = route_execution_request(_request("architecture_review", "code_review"), load_executor_providers(policy), policy)
    assert decision.status == "NEEDS_APPROVAL"
    assert decision.selected_provider_id == "manual.codex"


def test_router_returns_no_provider_when_no_capability_match():
    policy = load_executor_router_policy(Path("config/executor_router.yml"))
    decision = route_execution_request(_request("video_render", "video_render"), load_executor_providers(policy), policy)
    assert decision.status == "NO_PROVIDER"


def test_router_rejects_disabled_provider():
    policy = load_executor_router_policy(Path("config/executor_router.yml"))
    decision = route_execution_request(_request(), load_executor_providers(policy), policy)
    assert any(item["provider_id"] == "api.deepseek" for item in decision.rejected_providers)


def test_router_reports_rejected_provider_reasons():
    policy = load_executor_router_policy(Path("config/executor_router.yml"))
    decision = route_execution_request(_request("video_render", "video_render"), load_executor_providers(policy), policy)
    assert decision.rejected_providers
    assert all(item["reasons"] for item in decision.rejected_providers)


def test_unknown_cost_requires_approval():
    policy = load_executor_router_policy(Path("config/executor_router.yml"))
    policy.routing["allow_mock_executor"] = False
    policy.provider_priority["repo_patch"] = ["manual.codex"]
    decision = route_execution_request(_request(), load_executor_providers(policy), policy)
    assert decision.status == "NEEDS_APPROVAL"
    assert decision.approval_required is True


def test_unsafe_auto_provider_blocked_by_policy():
    policy = load_executor_router_policy(Path("tests/fixtures/p2_executor_router/unsafe_provider_policy.yml"))
    decision = route_execution_request(_request(), load_executor_providers(policy), policy)
    assert decision.status == "NO_PROVIDER"
    assert "auto execution disabled by policy" in decision.rejected_providers[0]["reasons"]
