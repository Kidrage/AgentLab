from agent_runtime.approvals.risk_gate import evaluate_risk

def test_evaluate_risk():
    cards = evaluate_risk(["shell_execution"], cli_cost_known=False)
    reasons = [c.reason for c in cards]
    assert "unknown external CLI cost" in reasons
    assert "risky capability: shell_execution" in reasons
