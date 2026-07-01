from typing import Dict, Any
from pathlib import Path
from dataclasses import dataclass

from agent_runtime.costs.model_cost_profile import load_model_cost_profiles
from agent_runtime.costs.executor_cost_profile import load_executor_cost_profiles
from agent_runtime.costs.worker_cost_profile import load_worker_cost_profiles

def estimate_cost(task_packet: Dict[str, Any], agentlab_root: Path) -> Dict[str, Any]:
    """
    Estimates cost for a task.
    """
    model_profiles = load_model_cost_profiles(agentlab_root)
    executor_profiles = load_executor_cost_profiles(agentlab_root)
    worker_profiles = load_worker_cost_profiles(agentlab_root)

    model = task_packet.get("model", "")
    executor = task_packet.get("executor", "")
    worker = task_packet.get("worker", "")

    expected_input_tokens = task_packet.get("expected_input_tokens", 0)
    expected_output_tokens = task_packet.get("expected_output_tokens", 0)
    cached_input_tokens = task_packet.get("cached_input_tokens", 0)

    # 1. Model cost
    input_cost = 0.0
    output_cost = 0.0
    discount = 0.0
    if model in model_profiles:
        profile = model_profiles[model]
        base_input_tokens = max(0, expected_input_tokens - cached_input_tokens)
        input_cost = (base_input_tokens / 1_000_000.0) * profile.input_usd_per_million_tokens

        discount_input_tokens = min(expected_input_tokens, cached_input_tokens)
        discount_rate = 1.0 - profile.cached_input_discount
        discount = (discount_input_tokens / 1_000_000.0) * profile.input_usd_per_million_tokens * profile.cached_input_discount

        output_cost = (expected_output_tokens / 1_000_000.0) * profile.output_usd_per_million_tokens

    # 2. Worker markup
    markup = 1.0
    if worker in worker_profiles:
        markup = worker_profiles[worker].role_markup

    total_model_cost = (input_cost + output_cost - discount) * markup

    # 3. Executor cost
    cost_visibility = "known_api_cost"
    approval_required = False
    if executor in executor_profiles:
        exec_profile = executor_profiles[executor]
        if exec_profile.direct_cost_visibility == "unknown":
            cost_visibility = "unknown_external_cli_cost"
            if exec_profile.requires_unknown_cost_approval:
                approval_required = True

    warnings = []
    if cost_visibility == "unknown_external_cli_cost":
        warnings.append("Unknown external CLI cost detected.")

    return {
        "estimated_cost_usd": total_model_cost,
        "currency": "USD",
        "cost_visibility": cost_visibility,
        "approval_required": approval_required,
        "breakdown": {
            "input_tokens_usd": input_cost,
            "output_tokens_usd": output_cost,
            "cached_input_discount_usd": discount,
            "executor_cost_usd": 0.0,
            "worker_markup": markup
        },
        "warnings": warnings
    }
