from pathlib import Path

import pytest
import yaml

from agent_runtime.executors import ExecutionRequest, filter_providers_for_request
from agent_runtime.executors.policy import load_executor_router_policy
from agent_runtime.executors.provider_registry import get_enabled_providers, load_executor_providers


POLICY = Path("config/executor_router.yml")


def test_load_executor_router_policy():
    policy = load_executor_router_policy(POLICY)
    assert policy.enabled is True
    assert policy.default_mode == "policy_auto"
    assert policy.approval_policy.default_mode == "auto"
    assert policy.providers


def test_provider_ids_must_be_unique(tmp_path):
    data = yaml.safe_load(POLICY.read_text())
    data["executor_router"]["providers"].append(dict(data["executor_router"]["providers"][0]))
    path = tmp_path / "policy.yml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        load_executor_providers(load_executor_router_policy(path))


def test_disabled_provider_not_selectable():
    providers = load_executor_providers(load_executor_router_policy(POLICY))
    enabled = get_enabled_providers(providers)
    assert "api.deepseek" not in {provider.provider_id for provider in enabled}


def test_external_provider_requires_approval():
    providers = load_executor_providers(load_executor_router_policy(POLICY))
    codex = next(provider for provider in providers if provider.provider_id == "manual.codex")
    assert codex.requires_approval is True


def test_auto_execution_disabled_for_non_mock_provider():
    policy = load_executor_router_policy(Path("tests/fixtures/p2_executor_router/unsafe_provider_policy.yml"))
    providers = load_executor_providers(policy)
    request = ExecutionRequest(task_id="t", task_type="repo_patch", summary="x", required_capabilities=["repo_patch"])
    selected, rejected = filter_providers_for_request(request, providers)
    assert selected
    assert not rejected
