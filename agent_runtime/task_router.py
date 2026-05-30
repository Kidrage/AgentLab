
"""Lightweight task routing for AgentLab Phase 2A.

This module only recommends which agent roles should participate. It does not
execute agents or modify source files.
"""

from schemas import AgentRoute


RESEARCH_HINTS = (
    "latest",
    "current",
    "docs",
    "api",
    "pricing",
    "regulation",
    "standard",
    "external",
    "research",
    # competitive intelligence / 竞品研究
    "competitor",
    "competitor analysis",
    "competitive",
    "comparison",
    "survey",
    "benchmark",
    "竞品",
    "同类产品",
    "对比",
    "调研",
    "竞争对手",
    "行业分析",
    "替代品",
    "alternative",
)

INTERFACE_HINTS = (
    "api",
    "schema",
    "protocol",
    "contract",
    "integration",
    "io",
    "metadata",
    "database",
    "migration",
    "ui",
)

LARGE_HINTS = (
    "architecture",
    "refactor",
    "multi-module",
    "cross-module",
    "migration",
    "rewrite",
    "performance",
    "security",
    "release",
)


def _configured_hints(routing_config: dict | None, key: str, fallback: tuple[str, ...]) -> tuple[str, ...]:
    if not routing_config:
        return fallback
    hints = routing_config.get("keyword_hints", {}).get(key)
    return tuple(hints) if hints else fallback


def _configured_route(routing_config: dict | None, key: str, fallback: list[str]) -> list[str]:
    if not routing_config:
        return fallback
    routes = routing_config.get("routes", {})
    return list(routes.get(key) or fallback)


def recommend_route(
    task_text: str,
    routing_config: dict | None = None,
    known_agents: list[str] | None = None,
) -> AgentRoute:
    """Return a conservative route based on task wording."""
    text = task_text.lower()
    thresholds = (routing_config or {}).get("task_size_thresholds", {})
    medium_chars = int(thresholds.get("medium_characters", 800))
    large_chars = int(thresholds.get("large_characters", 2500))

    research_hints = _configured_hints(routing_config, "research", RESEARCH_HINTS)
    interface_hints = _configured_hints(routing_config, "interface", INTERFACE_HINTS)
    large_hints = _configured_hints(routing_config, "large_or_risky", LARGE_HINTS)

    wants_research = any(hint in text for hint in research_hints)
    touches_interfaces = any(hint in text for hint in interface_hints)
    looks_large = any(hint in text for hint in large_hints) or len(text) > large_chars
    looks_medium = len(text) > medium_chars

    fallback_small = ["Supervisor", "Coder", "TesterAuditor", "Verifier"]
    fallback_medium = ["Supervisor", "RepoScout", "Coder", "TesterAuditor", "Verifier", "Archivist"]
    fallback_interface = ["Supervisor", "RepoScout", "InterfaceMapper", "Coder", "TesterAuditor", "Verifier", "Archivist"]
    fallback_research = ["Supervisor", "Researcher", "Coder", "TesterAuditor", "Verifier"]
    fallback_large = [
        "Supervisor",
        "RepoScout",
        "Researcher",
        "InterfaceMapper",
        "Coder",
        "TesterAuditor",
        "Verifier",
        "Archivist",
    ]

    if looks_large:
        route_key = "large_or_risky_task"
        task_size = "large"
        agents = _configured_route(routing_config, route_key, fallback_large)
    elif touches_interfaces:
        route_key = "interface_sensitive_task"
        task_size = "medium"
        agents = _configured_route(routing_config, route_key, fallback_interface)
    elif wants_research:
        route_key = "research_sensitive_task"
        task_size = "medium"
        agents = _configured_route(routing_config, route_key, fallback_research)
    elif looks_medium:
        route_key = "medium_task"
        task_size = "medium"
        agents = _configured_route(routing_config, route_key, fallback_medium)
    else:
        route_key = "small_task"
        task_size = "small"
        agents = _configured_route(routing_config, route_key, fallback_small)

    rationale = [
        "Supervisor always defines scope, token budget, and stop rules.",
        f"Route selected by {route_key} using smallest_safe_route rules.",
        "Coder and Tester/Auditor are required for implementation and verification.",
    ]
    if wants_research:
        rationale.append("Research hints detected; include Researcher when route requires current or external facts.")
    if touches_interfaces:
        rationale.append("Interface hints detected; include InterfaceMapper for boundaries and contracts.")
    if looks_large:
        rationale.append("Large or risky hints detected; include the full route.")

    all_agents = set(known_agents or (routing_config or {}).get("agent_order") or [
        "Supervisor",
        "RepoScout",
        "Researcher",
        "InterfaceMapper",
        "Coder",
        "TesterAuditor",
        "Archivist",
    ])
    skipped = sorted(all_agents.difference(agents))

    return AgentRoute(
        task_size=task_size,
        agents=agents,
        rationale=rationale,
        skipped_agents=skipped,
        route_key=route_key,
    )
