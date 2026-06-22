"""Marginal utility gate for execution economy decisions."""

from typing import List, Dict, Any, Tuple
from agent_runtime.execution_economy.activation_cost import ActivationCost

# Benefit levels mapping to numeric scores for simple utility comparison
BENEFIT_SCORE = {
    "none": 0,
    "low": 1,
    "medium": 2,
    "high": 3
}

def evaluate_marginal_utility(
    cost: ActivationCost,
    expected_benefit: Dict[str, str], # keys: quality_gain, risk_reduction, speed_gain, recovery_value
    task_size: str = "medium", # "small" | "medium" | "large"
    escalation_level: int = 0
) -> Tuple[str, str, List[str]]:
    """
    Evaluate the marginal utility of activating a worker.
    Returns (decision, verdict, reasons) where:
      decision: spawn | skip | satisfy_by_deterministic | satisfy_by_cache | coalesce | defer | require_approval
      verdict: justified | not_justified | unknown_requires_approval
      reasons: list of strings explaining the decision
    """
    reasons = []
    
    # Extract non-token costs
    perm_risk = cost.non_token_costs.permission_risk
    mut_risk = cost.non_token_costs.state_mutation_risk
    coord_cost = cost.non_token_costs.coordination_cost
    
    # 1. Critical risk requires human approval
    if perm_risk == "critical" or mut_risk == "critical":
        reasons.append("Critical permission risk or state mutation risk requires explicit approval.")
        return "require_approval", "unknown_requires_approval", reasons
        
    # 2. Deterministic tools (e.g. rg, git, linter) are cheap and low risk
    if cost.worker_id in ("rg", "git", "ruff", "eslint", "linter", "formatter"):
        reasons.append("Deterministic tools are low risk and extremely cost-effective.")
        return "satisfy_by_deterministic", "justified", reasons

    # Calculate overall benefit score
    q_gain = BENEFIT_SCORE.get(expected_benefit.get("quality_gain", "none"), 0)
    r_red = BENEFIT_SCORE.get(expected_benefit.get("risk_reduction", "none"), 0)
    s_gain = BENEFIT_SCORE.get(expected_benefit.get("speed_gain", "none"), 0)
    total_benefit = q_gain + r_red + s_gain
    
    # Determine effective tokens & disk/cache discounts
    raw_tokens = cost.fixed_startup_cost.raw_prompt_tokens
    effective_tokens = cost.fixed_startup_cost.effective_prompt_tokens
    hit_rate = cost.fixed_startup_cost.expected_cache_hit_rate
    
    # 3. High risk/mutation worker without approval
    if (perm_risk == "high" or mut_risk == "high") and total_benefit < 4:
        reasons.append(f"High risk worker {cost.worker_id} is not justified by low expected benefit.")
        return "skip", "not_justified", reasons
        
    # 4. Under budget or cache-rich low-risk worker
    is_cache_warm = hit_rate >= 0.7 or cost.fixed_startup_cost.estimated_cached_input_discount in ("high", "medium")
    if is_cache_warm and perm_risk in ("low", "medium") and mut_risk in ("low", "medium"):
        if total_benefit >= 2:
            reasons.append("Cached startup context makes activation cheap, and expected benefit is meaningful.")
            return "spawn", "justified", reasons
            
    # 5. Small tasks should coalesce if possible
    if task_size == "small" and total_benefit < 3:
        reasons.append("Small task should coalesce or skip low-utility workers to reduce coordination overhead.")
        return "coalesce", "justified", reasons
        
    # 6. Default decisions based on benefit score
    if total_benefit >= 4:
        reasons.append("Expected quality/risk reduction benefits justify the activation cost.")
        return "spawn", "justified", reasons
    elif total_benefit >= 2:
        reasons.append("Marginal utility is borderline; spawning with approval gate.")
        return "spawn", "justified", reasons
    else:
        reasons.append("Low expected benefits do not justify activation cost.")
        return "skip", "not_justified", reasons
