"""Route catalog helpers.

The catalog is the read-only authority for route templates. It keeps the
historical fallback routes in one place so routing code does not duplicate
agent lists while config migration is still in progress.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from atomic_io import safe_read_yaml
except ImportError:  # pragma: no cover - package import path
    from agent_runtime.atomic_io import safe_read_yaml


DEFAULT_ROUTE_AGENTS: dict[str, list[str]] = {
    "small_task": ["Supervisor", "Coder", "TesterAuditor", "Verifier"],
    "medium_task": ["Supervisor", "RepoScout", "Coder", "TesterAuditor", "Verifier", "Archivist"],
    "interface_sensitive_task": [
        "Supervisor",
        "RepoScout",
        "InterfaceMapper",
        "Coder",
        "TesterAuditor",
        "Verifier",
        "Archivist",
    ],
    "research_sensitive_task": ["Supervisor", "Researcher", "Coder", "TesterAuditor", "Verifier"],
    "artifact_production_task": ["Supervisor", "ArtifactProducer", "TesterAuditor", "Verifier", "Archivist"],
    "media_generation_task": ["Supervisor", "ArtifactProducer", "TesterAuditor", "Verifier", "Archivist"],
    "fiction_chapter_pipeline": ["Supervisor", "Writer", "Reviewer", "Scribe", "Verifier", "Archivist"],
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


ROUTE_SIZE_MAP: dict[str, str] = {
    "L1": "small",
    "L2": "medium",
    "L3": "large",
    "S0": "small",
    "S1": "small",
    "S2": "medium",
    "S3": "large",
    "S4": "large",
}


DEFAULT_ROUTE_SIZE: dict[str, str] = {
    "small_task": "small",
    "medium_task": "medium",
    "interface_sensitive_task": "medium",
    "research_sensitive_task": "medium",
    "artifact_production_task": "medium",
    "media_generation_task": "medium",
    "fiction_chapter_pipeline": "medium",
    "evaluation_task": "large",
    "large_or_risky_task": "large",
}


@dataclass(frozen=True)
class RouteCatalog:
    """Route templates merged from defaults and optional routing config."""

    routes: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_config(cls, routing_config: dict[str, Any] | None = None) -> "RouteCatalog":
        routes = (routing_config or {}).get("routes", {})
        return cls(routes=routes if isinstance(routes, dict) else {})

    @classmethod
    def from_file(cls, path: Path) -> "RouteCatalog":
        if not path.exists():
            return cls()
        data = safe_read_yaml(path, default={})
        return cls.from_config(data if isinstance(data, dict) else {})

    def agents_for(self, route_key: str) -> list[str]:
        route_entry = self.routes.get(route_key)
        configured_agents = route_entry.get("agents") if isinstance(route_entry, dict) else route_entry
        agents = list(configured_agents or DEFAULT_ROUTE_AGENTS.get(route_key, []))
        if "Coder" in agents and "TesterAuditor" not in agents:
            insert_at = agents.index("Coder") + 1
            agents.insert(insert_at, "TesterAuditor")
        return agents

    def size_for(self, route_key: str) -> str:
        route_entry = self.routes.get(route_key)
        configured_size = route_entry.get("size") if isinstance(route_entry, dict) else None
        fallback = DEFAULT_ROUTE_SIZE.get(route_key, "medium")
        return ROUTE_SIZE_MAP.get(str(configured_size), fallback)

    def has_route(self, route_key: str) -> bool:
        return route_key in self.routes or route_key in DEFAULT_ROUTE_AGENTS

    def has_configured_route(self, route_key: str) -> bool:
        return route_key in self.routes
