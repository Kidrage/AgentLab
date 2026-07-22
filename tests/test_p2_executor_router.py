from pathlib import Path

import pytest

from agent_runtime.executors import ExecutionRequest, load_executor_providers, load_executor_router_policy, route_execution_request


def _request(task_type="repo_patch", capability="repo_patch"):
    return ExecutionRequest(
        task_id="task",
        task_type=task_type,
        summary="Patch a bug",
        required_capabilities=[capability],
        bounded_scope=True,
        reversible=True,
        output_dir=Path("/tmp/agentlab-executor-test"),
    )


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


def test_bounded_known_cost_external_executor_is_policy_auto_approved():
    policy = load_executor_router_policy(Path("config/executor_router.yml"))
    policy.routing["allow_mock_executor"] = False
    policy.routing["allow_auto_execution"] = True
    policy.safety["forbid_network_execution"] = False
    policy.provider_priority["repo_patch"] = ["api.bounded"]
    policy.providers.append(
        {
            "provider_id": "api.bounded",
            "provider_type": "api_model",
            "display_name": "Bounded API",
            "enabled": True,
            "execution_mode": "approved_auto",
            "capabilities": ["repo_patch"],
            "suitable_task_types": ["repo_patch"],
            "risk_level": "medium",
            "requires_approval": True,
            "cost_mode": "api_model",
            "expected_cost_tier": "free",
            "supports_auto_execution": True,
        }
    )

    decision = route_execution_request(_request(), load_executor_providers(policy), policy)

    assert decision.status == "ROUTED"
    assert decision.approval_required is False
    assert decision.approval_mode == "auto_approved"
    assert decision.approval_grant["actor"] == "policy:default-auto"
    assert decision.approval_grant["authorizes_execution"] is True


def test_known_external_estimate_below_limit_is_policy_auto_approved():
    policy = load_executor_router_policy(Path("config/executor_router.yml"))
    policy.routing["allow_mock_executor"] = False
    policy.routing["allow_auto_execution"] = True
    policy.safety["forbid_network_execution"] = False
    policy.provider_priority["repo_patch"] = ["api.deepseek"]
    provider = next(item for item in policy.providers if item["provider_id"] == "api.deepseek")
    provider["enabled"] = True
    provider["execution_mode"] = "approved_auto"
    provider["supports_auto_execution"] = True
    request = _request()
    request.estimated_cost_usd = 0.05

    providers = [
        item
        for item in load_executor_providers(policy)
        if item.provider_id == "api.deepseek"
    ]
    decision = route_execution_request(request, providers, policy)

    assert decision.status == "ROUTED"
    assert decision.approval_mode == "auto_approved"
    scope = decision.approval_grant["scope"]["execution_request"]
    assert scope["summary"] == request.summary
    assert scope["task_type"] == request.task_type
    assert scope["requires_review"] is True
    assert scope["evidence_required"] == []


@pytest.mark.parametrize(
    ("estimated_cost", "expected_reason"),
    [
        (False, "invalid_cost"),
        ("", "missing_cost_estimate"),
        (None, "unknown_cost"),
    ],
)
def test_external_executor_rejects_invalid_or_missing_cost(estimated_cost, expected_reason):
    policy = load_executor_router_policy(Path("config/executor_router.yml"))
    policy.routing["allow_mock_executor"] = False
    policy.routing["allow_auto_execution"] = True
    policy.safety["forbid_network_execution"] = False
    policy.provider_priority["repo_patch"] = ["api.deepseek"]
    provider = next(item for item in policy.providers if item["provider_id"] == "api.deepseek")
    provider["enabled"] = True
    provider["execution_mode"] = "approved_auto"
    provider["supports_auto_execution"] = True
    request = _request()
    request.estimated_cost_usd = estimated_cost

    decision = route_execution_request(request, load_executor_providers(policy), policy)

    assert decision.status == "NEEDS_APPROVAL"
    assert decision.approval_grant is None
    assert decision.reason == [expected_reason]


def test_estimate_above_request_limit_requires_human_approval():
    policy = load_executor_router_policy(Path("config/executor_router.yml"))
    policy.routing["allow_mock_executor"] = False
    policy.routing["allow_auto_execution"] = True
    policy.safety["forbid_network_execution"] = False
    policy.provider_priority["repo_patch"] = ["api.deepseek"]
    provider = next(item for item in policy.providers if item["provider_id"] == "api.deepseek")
    provider["enabled"] = True
    provider["execution_mode"] = "approved_auto"
    provider["supports_auto_execution"] = True
    request = _request()
    request.estimated_cost_usd = 0.05
    request.max_cost_usd = 0.01

    decision = route_execution_request(request, load_executor_providers(policy), policy)

    assert decision.status == "NEEDS_APPROVAL"
    assert decision.reason == ["estimated_cost_exceeds_request_limit:0.05>0.01"]


def test_estimate_above_router_limit_requires_human_approval():
    policy = load_executor_router_policy(Path("config/executor_router.yml"))
    policy.routing["allow_mock_executor"] = False
    policy.routing["allow_auto_execution"] = True
    policy.safety["forbid_network_execution"] = False
    policy.budget["max_cost_usd_per_task"] = 0.03
    policy.provider_priority["repo_patch"] = ["api.deepseek"]
    provider = next(item for item in policy.providers if item["provider_id"] == "api.deepseek")
    provider["enabled"] = True
    provider["execution_mode"] = "approved_auto"
    provider["supports_auto_execution"] = True
    request = _request()
    request.estimated_cost_usd = 0.05

    decision = route_execution_request(request, load_executor_providers(policy), policy)

    assert decision.status == "NEEDS_APPROVAL"
    assert decision.reason == ["estimated_cost_exceeds_router_limit:0.05>0.03"]


def test_network_safety_flag_blocks_auto_external_executor():
    policy = load_executor_router_policy(Path("config/executor_router.yml"))
    policy.routing["allow_mock_executor"] = False
    policy.routing["allow_auto_execution"] = True
    policy.safety["forbid_network_execution"] = True
    policy.provider_priority["repo_patch"] = ["api.deepseek"]
    provider = next(item for item in policy.providers if item["provider_id"] == "api.deepseek")
    provider["enabled"] = True
    provider["execution_mode"] = "approved_auto"
    provider["supports_auto_execution"] = True
    request = _request()
    request.estimated_cost_usd = 0.05

    providers = [
        item
        for item in load_executor_providers(policy)
        if item.provider_id == "api.deepseek"
    ]
    decision = route_execution_request(request, providers, policy)

    assert decision.status == "BLOCKED_BY_POLICY"
    assert decision.approval_mode == "forbidden"
    assert decision.reason == ["forbidden: network execution disabled by executor safety policy"]


@pytest.mark.parametrize(
    ("case", "expected_reason"),
    [
        ("remote_clone", "forbidden: remote clone disabled by executor safety policy"),
        ("external_script", "forbidden: external script execution disabled by executor safety policy"),
        ("secret", "forbidden: secret exposure disabled by executor safety policy"),
        ("subscription", "forbidden: subscription-backed auto execution disabled by executor safety policy"),
        ("unreviewed_merge", "forbidden: unreviewed merge disabled by executor safety policy"),
    ],
)
def test_executor_safety_prohibitions_precede_auto_approval(case, expected_reason):
    policy = load_executor_router_policy(Path("config/executor_router.yml"))
    policy.routing["allow_auto_execution"] = True
    policy.safety["forbid_network_execution"] = False
    policy.provider_priority["repo_patch"] = ["api.deepseek"]
    raw_provider = next(item for item in policy.providers if item["provider_id"] == "api.deepseek")
    raw_provider["enabled"] = True
    raw_provider["execution_mode"] = "approved_auto"
    raw_provider["supports_auto_execution"] = True
    request = _request()
    request.estimated_cost_usd = 0.05
    if case == "remote_clone":
        request.required_capabilities.append("remote_clone")
        raw_provider["capabilities"].append("remote_clone")
    elif case == "external_script":
        request.required_capabilities.append("shell_execution")
        raw_provider["capabilities"].append("shell_execution")
    elif case == "secret":
        request.contains_secrets = True
    elif case == "subscription":
        raw_provider["cost_mode"] = "subscription_credit"
    else:
        request.approval_action = "merge"
        request.requires_review = False
    providers = [
        item
        for item in load_executor_providers(policy)
        if item.provider_id == "api.deepseek"
    ]

    decision = route_execution_request(request, providers, policy)

    assert decision.status == "BLOCKED_BY_POLICY"
    assert decision.approval_mode == "forbidden"
    assert decision.reason == [expected_reason]


def test_public_release_executor_request_still_requires_human():
    policy = load_executor_router_policy(Path("config/executor_router.yml"))
    request = _request()
    request.approval_action = "public_release"

    decision = route_execution_request(request, load_executor_providers(policy), policy)

    assert decision.status == "NEEDS_APPROVAL"
    assert decision.approval_mode == "human_required"


def test_irreversible_external_repo_patch_requires_human():
    policy = load_executor_router_policy(Path("config/executor_router.yml"))
    policy.routing["allow_mock_executor"] = False
    policy.routing["allow_auto_execution"] = True
    policy.safety["forbid_network_execution"] = False
    policy.provider_priority["repo_patch"] = ["api.deepseek"]
    provider = next(item for item in policy.providers if item["provider_id"] == "api.deepseek")
    provider["enabled"] = True
    provider["execution_mode"] = "approved_auto"
    provider["supports_auto_execution"] = True
    request = _request()
    request.estimated_cost_usd = 0.05
    request.reversible = False

    decision = route_execution_request(request, load_executor_providers(policy), policy)

    assert decision.status == "NEEDS_APPROVAL"
    assert decision.reason == ["irreversible_action"]


def test_external_repo_patch_without_reversibility_requires_human():
    policy = load_executor_router_policy(Path("config/executor_router.yml"))
    policy.routing["allow_mock_executor"] = False
    policy.routing["allow_auto_execution"] = True
    policy.safety["forbid_network_execution"] = False
    policy.provider_priority["repo_patch"] = ["api.deepseek"]
    provider = next(item for item in policy.providers if item["provider_id"] == "api.deepseek")
    provider["enabled"] = True
    provider["execution_mode"] = "approved_auto"
    provider["supports_auto_execution"] = True
    request = _request()
    request.estimated_cost_usd = 0.05
    request.reversible = None

    decision = route_execution_request(request, load_executor_providers(policy), policy)

    assert decision.status == "NEEDS_APPROVAL"
    assert decision.reason == ["unknown_action_reversibility"]


def test_unsafe_auto_provider_blocked_by_policy():
    policy = load_executor_router_policy(Path("tests/fixtures/p2_executor_router/unsafe_provider_policy.yml"))
    decision = route_execution_request(_request(), load_executor_providers(policy), policy)
    assert decision.status == "NO_PROVIDER"
    assert "auto execution disabled by policy" in decision.rejected_providers[0]["reasons"]
