"""Effective cost calculator for execution economy."""

from agent_runtime.execution_economy.activation_cost import ActivationCost

def calculate_effective_tokens(cost: ActivationCost) -> int:
    """Calculate effective prompt tokens based on cache hit rate."""
    raw = cost.fixed_startup_cost.raw_prompt_tokens
    cacheable = cost.fixed_startup_cost.cacheable_prompt_tokens
    hit_rate = cost.fixed_startup_cost.expected_cache_hit_rate
    
    # Effective startup tokens
    effective_startup = int(raw - (cacheable * hit_rate))
    effective_startup = max(0, effective_startup)
    
    # Add variable task specific context tokens
    var_tokens = cost.variable_cost.task_specific_context_tokens
    return effective_startup + var_tokens

def estimate_cost_in_usd(tokens: int, worker_id: str) -> float:
    """Estimate cost in USD based on token counts and worker profile."""
    # Rough baseline rates per 1k tokens
    rate = 0.003 # default: $0.003 per 1k tokens
    if "claude" in worker_id:
        rate = 0.015
    elif "hermes" in worker_id:
        rate = 0.001
    elif worker_id in ("rg", "git"):
        return 0.0
        
    return (tokens / 1000.0) * rate

def get_cost_tier(usd: float) -> str:
    """Classify USD cost into a tier."""
    if usd == 0.0:
        return "none"
    elif usd < 0.01:
        return "low"
    elif usd < 0.10:
        return "medium"
    else:
        return "high"
