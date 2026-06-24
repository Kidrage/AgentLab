from agent_runtime.costs.budget_policy import load_budget_policy
from pathlib import Path

def test_load_budget_policy(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "cost_policy_v2.yml").write_text("cost_policy:\n  hard_limit_usd: 100.0")
    policy = load_budget_policy(tmp_path)
    assert policy["cost_policy"]["hard_limit_usd"] == 100.0
