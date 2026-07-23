"""Read route templates from the canonical routing configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from config_loader import load_yaml
except ImportError:  # pragma: no cover - package import path
    from agent_runtime.config_loader import load_yaml


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


def route_size_suffix(task_size: str) -> str:
    """Return the budget/profile suffix for a canonical route size."""
    return {"small": "L1", "medium": "L2", "large": "L3"}.get(str(task_size), "L2")


CANONICAL_ROUTING_CONFIG_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "routing_rules.yml"
)


@dataclass(frozen=True)
class RouteCatalog:
    """Route templates loaded from one routing-config authority."""

    routes: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_config(cls, routing_config: dict[str, Any] | None = None) -> "RouteCatalog":
        config = (
            load_yaml(CANONICAL_ROUTING_CONFIG_PATH)
            if routing_config is None or "routes" not in routing_config
            else routing_config
        )
        routes = config.get("routes", {})
        return cls(routes=routes if isinstance(routes, dict) else {})

    @classmethod
    def from_file(cls, path: Path) -> "RouteCatalog":
        if not path.exists():
            return cls()
        data = load_yaml(path)
        routes = data.get("routes", {})
        return cls(routes=routes if isinstance(routes, dict) else {})

    def agents_for(self, route_key: str) -> list[str]:
        route_entry = self.routes.get(route_key)
        configured_agents = route_entry.get("agents") if isinstance(route_entry, dict) else route_entry
        return list(configured_agents or [])

    def size_for(self, route_key: str) -> str:
        route_entry = self.routes.get(route_key)
        configured_size = route_entry.get("size") if isinstance(route_entry, dict) else None
        return ROUTE_SIZE_MAP.get(str(configured_size), "medium")

    def has_route(self, route_key: str) -> bool:
        return route_key in self.routes

    def has_configured_route(self, route_key: str) -> bool:
        return route_key in self.routes
