from agent_runtime.costs.budget_policy import load_budget_policy, BudgetPolicy
from pathlib import Path

def test_load_budget_policy_defaults(tmp_path):
    policy = load_budget_policy(tmp_path)
    assert policy.version == 2
    assert policy.project_hard_limit_usd == 10.0

def test_load_budget_policy_valid(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "cost_policy_v2.yml").write_text("cost_policy:\n  project_hard_limit_usd: 100.0\n  project_soft_limit_usd: 50.0")
    policy = load_budget_policy(tmp_path)
    assert policy.project_hard_limit_usd == 100.0

def test_invalid_yaml(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "cost_policy_v2.yml").write_text("cost_policy: [invalid")
    try:
        load_budget_policy(tmp_path)
        assert False, "Should raise exception"
    except ValueError:
        pass

def test_hard_limit_lower_than_soft_limit(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "cost_policy_v2.yml").write_text("cost_policy:\n  project_hard_limit_usd: 10.0\n  project_soft_limit_usd: 50.0")
    try:
        load_budget_policy(tmp_path)
        assert False, "Should raise exception"
    except ValueError:
        pass
