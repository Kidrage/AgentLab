"""Tests for effective token and USD cost estimation."""

from agent_runtime.execution_economy.activation_cost import ActivationCost
from agent_runtime.execution_economy.effective_cost import (
    calculate_effective_tokens, estimate_cost_in_usd, get_cost_tier
)

def test_effective_cost_calculations():
    cost_dict = {
        "worker_id": "claude_code",
        "fixed_startup_cost": {
            "raw_prompt_tokens": 10000,
            "cacheable_prompt_tokens": 8000,
            "expected_cache_hit_rate": 0.85
        },
        "variable_cost": {
            "task_specific_context_tokens": 2000
        }
    }
    cost = ActivationCost.from_dict(cost_dict)
    
    # 10000 - 8000 * 0.85 + 2000 = 10000 - 6800 + 2000 = 3200 + 2000 = 5200
    eff_tokens = calculate_effective_tokens(cost)
    assert eff_tokens == 5200
    
    usd = estimate_cost_in_usd(eff_tokens, "claude_code")
    assert usd == (5200 / 1000.0) * 0.015
    
    assert get_cost_tier(0.0) == "none"
    assert get_cost_tier(0.005) == "low"
    assert get_cost_tier(0.05) == "medium"
    assert get_cost_tier(0.50) == "high"
