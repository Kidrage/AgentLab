"""Token budget planning helpers."""

from schemas import AgentRoute, TokenBudget


def build_token_budgets(route: AgentRoute, budget_config: dict) -> list[TokenBudget]:
    """Build token budget rows for the selected route."""
    defaults = budget_config.get("defaults", {})
    warning_ratio = float(defaults.get("warning_ratio", 0.9))
    stop_ratio = float(defaults.get("stop_ratio", 1.15))
    profiles = budget_config.get("profiles", {})
    profile = profiles.get(route.task_size, {})

    budgets: list[TokenBudget] = []
    for phase in profile.get("phases", []):
        agent = phase.get("agent")
        if agent and agent not in route.agents:
            continue

        estimated_input = int(phase.get("estimated_input_tokens", 0))
        estimated_output = int(phase.get("estimated_output_tokens", 0))
        estimated_total = int(phase.get("estimated_total_tokens") or estimated_input + estimated_output)
        budgets.append(
            TokenBudget(
                phase=phase.get("phase", agent or "Unspecified phase"),
                estimated_input_tokens=estimated_input,
                estimated_output_tokens=estimated_output,
                estimated_total_tokens=estimated_total,
                warning_threshold_tokens=int(estimated_total * warning_ratio),
                stop_threshold_tokens=int(estimated_total * stop_ratio),
                notes=phase.get("notes", ""),
            )
        )

    return budgets
