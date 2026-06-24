"""Tests for the marginal utility gate decisions."""

from agent_runtime.execution_economy.activation_cost import ActivationCost
from agent_runtime.execution_economy.marginal_utility_gate import evaluate_marginal_utility

def test_marginal_utility_gate():
    # 1. Critical risk requires approval
    cost = ActivationCost.from_dict({
        "worker_id": "claude_code",
        "non_token_costs": {
            "permission_risk": "critical"
        }
    })
    dec, verd, reasons = evaluate_marginal_utility(cost, {})
    assert dec == "require_approval"
    assert verd == "unknown_requires_approval"

    # 2. Deterministic tools are cheap and low risk
    cost_rg = ActivationCost.from_dict({"worker_id": "rg"})
    dec, verd, reasons = evaluate_marginal_utility(cost_rg, {})
    assert dec == "satisfy_by_deterministic"
    assert verd == "justified"

    # 3. High risk low benefit skipping
    cost_high_risk = ActivationCost.from_dict({
        "worker_id": "claude_code",
        "non_token_costs": {
            "permission_risk": "high",
            "state_mutation_risk": "high"
        }
    })
    dec, verd, reasons = evaluate_marginal_utility(cost_high_risk, {"quality_gain": "low"})
    assert dec == "skip"
    assert verd == "not_justified"
