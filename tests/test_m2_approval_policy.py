from agent_runtime.approvals.approval_policy import load_approval_policy

def test_load_approval_policy(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "approval_policy.yml").write_text("approval_policy:\n  require_approval_above_usd: 100.0")
    policy = load_approval_policy(tmp_path)
    assert policy.require_approval_above_usd == 100.0

def test_load_approval_policy_defaults(tmp_path):
    policy = load_approval_policy(tmp_path)
    assert policy.require_approval_above_usd == 0.50
    assert "shell_execution" in policy.risky_capabilities
