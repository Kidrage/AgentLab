"""Tests for ActivationCost serialization and structure."""

from agent_runtime.execution_economy.activation_cost import ActivationCost

def test_activation_cost_serialization():
    cost_dict = {
        "worker_id": "test_worker",
        "fixed_startup_cost": {
            "raw_prompt_tokens": 1000,
            "cacheable_prompt_tokens": 800,
            "expected_cache_hit_rate": 0.9,
            "effective_prompt_tokens": 280,
            "estimated_cached_input_discount": "high",
            "estimated_latency_s": 5.0,
            "operator_friction": "medium"
        },
        "cache_profile": {
            "stable_prefix_hash": "sha256:prefix",
            "skill_context_hash": "sha256:skills",
            "mcp_manifest_hash": "sha256:mcps",
            "last_cache_hit_observed": "true",
            "cache_confidence": "high"
        },
        "variable_cost": {
            "task_specific_context_tokens": 500,
            "context_tokens_per_kb": 10,
            "output_tokens_expected": 200,
            "dollars_per_call": "0.01"
        },
        "non_token_costs": {
            "coordination_cost": "medium",
            "permission_risk": "low",
            "state_mutation_risk": "low"
        },
        "hidden_costs": ["context_duplication"],
        "confidence": "high"
    }
    
    cost = ActivationCost.from_dict(cost_dict)
    assert cost.worker_id == "test_worker"
    assert cost.fixed_startup_cost.raw_prompt_tokens == 1000
    assert cost.cache_profile.last_cache_hit_observed == "true"
    assert cost.variable_cost.context_tokens_per_kb == 10
    assert cost.non_token_costs.coordination_cost == "medium"
    assert "context_duplication" in cost.hidden_costs
    
    serialized = cost.to_dict()
    assert serialized["worker_id"] == "test_worker"
    assert serialized["fixed_startup_cost"]["raw_prompt_tokens"] == 1000
    assert serialized["cache_profile"]["last_cache_hit_observed"] == "true"
