
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

EVALUATION_HINTS = (
    "evaluate",
    "evaluation",
    "assessment",
    "assess",
    "benchmark",
    "performance evaluation",
    "performance benchmark",
    "comprehensive evaluation",
    "architecture review",
    "system review",
    "audit report",
    "compare",
    "comparison",
    "评估",
    "全面评估",
    "性能评估",
    "基准测试",
    "架构评估",
    "系统评估",
    "审计报告",
    "对比分析",
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

FALLBACK_ROUTES = {
    "small_task": ["Supervisor", "Coder", "TesterAuditor", "Verifier"],
    "medium_task": ["Supervisor", "RepoScout", "Coder", "TesterAuditor", "Verifier", "Archivist"],
    "interface_sensitive_task": ["Supervisor", "RepoScout", "InterfaceMapper", "Coder", "TesterAuditor", "Verifier", "Archivist"],
    "research_sensitive_task": ["Supervisor", "Researcher", "Coder", "TesterAuditor", "Verifier"],
    "evaluation_task": [
        "Supervisor",
        "RepoScout",
        "Researcher",
        "InterfaceMapper",
        "TesterAuditor",
        "Verifier",
        "Archivist",
    ],
    "large_or_risky_task": [
        "Supervisor",
        "RepoScout",
        "Researcher",
        "InterfaceMapper",
        "Coder",
        "TesterAuditor",
        "Verifier",
        "Archivist",
    ],
}


def _configured_hints(routing_config: dict | None, key: str, fallback: tuple[str, ...]) -> tuple[str, ...]:
    if not routing_config:
        return fallback
    hints = routing_config.get("keyword_hints", {}).get(key)
    return tuple(hints) if hints else fallback


def _configured_route(routing_config: dict | None, key: str, fallback: list[str]) -> list[str]:
    if not routing_config:
        return fallback
    routes = routing_config.get("routes", {})
    route_entry = routes.get(key)
    if isinstance(route_entry, dict):
        configured_agents = route_entry.get("agents")
    else:
        configured_agents = route_entry
    agents = list(configured_agents or fallback)
    if "Coder" in agents and "TesterAuditor" not in agents:
        insert_at = agents.index("Coder") + 1
        agents.insert(insert_at, "TesterAuditor")
    return agents


def _configured_route_size(routing_config: dict | None, key: str, fallback: str) -> str:
    if not routing_config:
        return fallback
    route_entry = routing_config.get("routes", {}).get(key)
    configured_size = route_entry.get("size") if isinstance(route_entry, dict) else None
    size_map = {
        "L1": "small",
        "L2": "medium",
        "L3": "large",
        "S0": "small",
        "S1": "small",
        "S2": "medium",
        "S3": "large",
        "S4": "large",
    }
    return size_map.get(str(configured_size), fallback)


def _known_agent_set(routing_config: dict | None, known_agents: list[str] | None) -> set[str]:
    return set(known_agents or (routing_config or {}).get("agent_order") or [
        "Supervisor",
        "RepoScout",
        "Researcher",
        "InterfaceMapper",
        "Coder",
        "TesterAuditor",
        "Verifier",
        "Archivist",
    ])


def _agent_route(
    *,
    task_size: str,
    agents: list[str],
    rationale: list[str],
    route_key: str,
    routing_config: dict | None,
    known_agents: list[str] | None,
) -> AgentRoute:
    all_agents = _known_agent_set(routing_config, known_agents)
    skipped = sorted(all_agents.difference(agents))
    return AgentRoute(
        task_size=task_size,
        agents=agents,
        rationale=rationale,
        skipped_agents=skipped,
        route_key=route_key,
    )


def _route_from_brain_profile(
    brain_profile: dict | None,
    routing_config: dict | None,
    known_agents: list[str] | None,
) -> AgentRoute | None:
    if not brain_profile:
        return None
    route_key = str(brain_profile.get("route_key_hint") or "").strip()
    if route_key not in FALLBACK_ROUTES:
        return None
    fallback_agents = FALLBACK_ROUTES[route_key]
    configured_size = str(brain_profile.get("task_size") or "").strip().lower()
    fallback_size = configured_size if configured_size in {"small", "medium", "large"} else {
        "small_task": "small",
        "medium_task": "medium",
        "interface_sensitive_task": "medium",
        "research_sensitive_task": "medium",
        "evaluation_task": "large",
        "large_or_risky_task": "large",
    }[route_key]
    task_size = _configured_route_size(routing_config, route_key, fallback_size)
    agents = _configured_route(routing_config, route_key, fallback_agents)
    rationale = [
        "Brain execution profile selected route before keyword fallback.",
        f"Profile route={route_key}, size={brain_profile.get('task_size', task_size)}, risk={brain_profile.get('risk_level', 'unknown')}.",
    ]
    rationale.extend(str(item) for item in brain_profile.get("rationale", [])[:4])
    for boundary in brain_profile.get("boundaries", [])[:4]:
        rationale.append(f"Boundary: {boundary}.")
    return _agent_route(
        task_size=task_size,
        agents=agents,
        rationale=rationale,
        route_key=route_key,
        routing_config=routing_config,
        known_agents=known_agents,
    )


def recommend_route(
    task_text: str,
    routing_config: dict | None = None,
    known_agents: list[str] | None = None,
    brain_profile: dict | None = None,
) -> AgentRoute:
    """Return a conservative route based on task wording."""
    brain_route = _route_from_brain_profile(brain_profile, routing_config, known_agents)
    if brain_route is not None:
        return brain_route

    text = task_text.lower()
    thresholds = (routing_config or {}).get("task_size_thresholds", {})
    medium_chars = int(thresholds.get("medium_characters", 800))
    large_chars = int(thresholds.get("large_characters", 2500))

    research_hints = _configured_hints(routing_config, "research", RESEARCH_HINTS)
    evaluation_hints = _configured_hints(routing_config, "evaluation", EVALUATION_HINTS)
    interface_hints = _configured_hints(routing_config, "interface", INTERFACE_HINTS)
    large_hints = _configured_hints(routing_config, "large_or_risky", LARGE_HINTS)

    wants_evaluation = any(hint in text for hint in evaluation_hints)
    wants_research = any(hint in text for hint in research_hints)
    touches_interfaces = any(hint in text for hint in interface_hints)
    looks_large = any(hint in text for hint in large_hints) or len(text) > large_chars
    looks_medium = len(text) > medium_chars

    if wants_evaluation:
        route_key = "evaluation_task"
        task_size = _configured_route_size(routing_config, route_key, "large")
        agents = _configured_route(routing_config, route_key, FALLBACK_ROUTES[route_key])
    elif looks_large:
        route_key = "large_or_risky_task"
        task_size = _configured_route_size(routing_config, route_key, "large")
        agents = _configured_route(routing_config, route_key, FALLBACK_ROUTES[route_key])
    elif touches_interfaces:
        route_key = "interface_sensitive_task"
        task_size = _configured_route_size(routing_config, route_key, "medium")
        agents = _configured_route(routing_config, route_key, FALLBACK_ROUTES[route_key])
    elif wants_research:
        route_key = "research_sensitive_task"
        task_size = _configured_route_size(routing_config, route_key, "medium")
        agents = _configured_route(routing_config, route_key, FALLBACK_ROUTES[route_key])
    elif looks_medium:
        route_key = "medium_task"
        task_size = _configured_route_size(routing_config, route_key, "medium")
        agents = _configured_route(routing_config, route_key, FALLBACK_ROUTES[route_key])
    else:
        route_key = "small_task"
        task_size = _configured_route_size(routing_config, route_key, "small")
        agents = _configured_route(routing_config, route_key, FALLBACK_ROUTES[route_key])

    rationale = [
        "Supervisor always defines scope, token budget, and stop rules.",
        f"Route selected by {route_key} using smallest_safe_route rules.",
    ]
    if "Coder" in agents:
        rationale.append("Coder and Tester/Auditor are required for implementation and verification.")
    else:
        rationale.append("Analysis-only route selected; Coder is skipped because no source implementation is requested.")
    if wants_research:
        rationale.append("Research hints detected; include Researcher when route requires current or external facts.")
    if wants_evaluation:
        rationale.append("Evaluation hints detected; use analysis-only L3 route and skip Coder by default.")
    if touches_interfaces:
        rationale.append("Interface hints detected; include InterfaceMapper for boundaries and contracts.")
    if looks_large:
        rationale.append("Large or risky hints detected; include the full route.")

    return _agent_route(
        task_size=task_size,
        agents=agents,
        rationale=rationale,
        route_key=route_key,
        routing_config=routing_config,
        known_agents=known_agents,
    )
