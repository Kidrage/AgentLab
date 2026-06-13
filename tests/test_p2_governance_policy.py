from pathlib import Path

from agent_runtime.governance.policy import load_provider_governance_policy


def test_load_provider_governance_policy():
    policy = load_provider_governance_policy(Path("config/provider_governance.yml"))
    assert policy.enabled is True
    assert policy.minimum_data["min_attempts_for_scoring"] == 2


def test_governance_policy_defaults_safe(tmp_path: Path):
    path = tmp_path / "provider_governance.yml"
    path.write_text("provider_governance:\n  enabled: true\n", encoding="utf-8")
    policy = load_provider_governance_policy(path)
    assert policy.cost["unknown_cost_requires_manual_approval"] is True
    assert policy.routing_feedback["apply_as_recommendation_only"] is True


def test_governance_never_modifies_router_policy_directly():
    policy = load_provider_governance_policy(Path("config/provider_governance.yml"))
    assert policy.routing_feedback["never_modify_router_policy_directly"] is True
