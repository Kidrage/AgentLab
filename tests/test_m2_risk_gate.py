from agent_runtime.approvals.approval_policy import ApprovalPolicy
from agent_runtime.approvals.risk_gate import evaluate_risk

def test_risk_gate_cost():
    policy = ApprovalPolicy(require_approval_for_unknown_cli_cost=True)
    packet = {"cost_visibility": "unknown_external_cli_cost"}
    cards = evaluate_risk(packet, policy)
    assert len(cards) == 1
    assert cards[0].decision_type == "cost"

def test_risk_gate_capabilities():
    policy = ApprovalPolicy(require_approval_for_risky_capabilities=True, risky_capabilities=["shell_execution"], critical_capabilities=["secrets"])
    packet = {"required_capabilities": ["shell_execution"]}
    cards = evaluate_risk(packet, policy)
    assert len(cards) == 1
    assert cards[0].decision_type == "capability"
    assert cards[0].risk_level == "high"
