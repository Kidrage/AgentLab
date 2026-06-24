"""Tests for role activation policies."""

from agent_runtime.execution_economy.role_activation_policy import RoleActivationPolicy

def test_role_activation_policy_defaults():
    policy = RoleActivationPolicy()

    assert policy.get_candidate_worker("Supervisor") == "claude_code"
    assert policy.get_candidate_worker("RepoScout") == "rg"
    assert policy.get_candidate_worker("Verifier") == "ruff"

    benefits = policy.get_expected_benefit("Coder", "medium")
    assert benefits["quality_gain"] == "high"

    benefits_small = policy.get_expected_benefit("Coder", "small")
    assert benefits_small["quality_gain"] == "medium" # downgraded for small task
