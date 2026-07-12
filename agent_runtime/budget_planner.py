"""Token budget planning helpers."""

try:
    from agent_runtime.schemas import AgentRoute, TokenBudget
    from agent_runtime.routing.route_catalog import route_size_suffix as _route_size_suffix
except ModuleNotFoundError:  # pragma: no cover - direct runtime import path
    from schemas import AgentRoute, TokenBudget
    from routing.route_catalog import route_size_suffix as _route_size_suffix


BUDGET_ALIASES = {
    "": "balanced",
    "brain_allocated": "balanced",
    "balanced": "balanced",
    "max-quality": "max_quality",
    "max_quality": "max_quality",
    "maxquality": "max_quality",
    "frugal": "frugal",
}


def normalize_budget_mode(value: str | None) -> str:
    """Normalize user/config budget mode names to runtime mode keys."""
    key = str(value or "").strip().lower().replace("-", "_")
    return BUDGET_ALIASES.get(key, key or "balanced")


def route_size_suffix(route: AgentRoute) -> str:
    return _route_size_suffix(route.task_size)


def select_budget_profile_key(route: AgentRoute, budget_config: dict, budget_mode: str | None = None) -> str:
    """Return the best matching budget profile key for a route and mode."""
    defaults = budget_config.get("defaults", {})
    profiles = budget_config.get("profiles", {})
    mode = normalize_budget_mode(budget_mode or defaults.get("budget_mode", "balanced"))
    size_suffix = route_size_suffix(route)
    mode_prefix = "brain_allocated" if mode == "balanced" else mode
    candidates = [
        f"{mode}_{size_suffix}",
        f"{mode_prefix}_{size_suffix}",
        f"brain_allocated_{size_suffix}",
        route.task_size,
    ]
    for key in candidates:
        if profiles.get(key):
            return key
    return ""


def build_token_budgets(route: AgentRoute, budget_config: dict, budget_mode: str | None = None) -> list[TokenBudget]:
    """Build token budget rows for the selected route."""
    defaults = budget_config.get("defaults", {})
    warning_ratio = float(defaults.get("warning_ratio", 0.9))
    stop_ratio = float(defaults.get("stop_ratio", 1.15))
    profiles = budget_config.get("profiles", {})
    profile_key = select_budget_profile_key(route, budget_config, budget_mode)
    profile = profiles.get(profile_key, {})

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
