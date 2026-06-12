from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


@dataclass
class ExternalAgent:
    agent_id: str
    display_name: str
    type: str
    enabled: bool
    integration_mode: str
    capabilities: list[str] = field(default_factory=list)
    billing: dict[str, Any] = field(default_factory=dict)
    risk: dict[str, Any] = field(default_factory=dict)
    allowed_task_types: list[str] = field(default_factory=list)

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "ExternalAgent":
        return ExternalAgent(
            agent_id=data.get("agent_id", ""),
            display_name=data.get("display_name", ""),
            type=data.get("type", ""),
            enabled=data.get("enabled", False),
            integration_mode=data.get("integration_mode", ""),
            capabilities=list(data.get("capabilities") or []),
            billing=dict(data.get("billing") or {}),
            risk=dict(data.get("risk") or {}),
            allowed_task_types=list(data.get("allowed_task_types") or []),
        )


def load_external_agents_config(path: Path) -> dict[str, Any]:
    """Load raw external agents config from a YAML file."""
    if not path.exists():
        return {}
    with open(path, "r") as f:
        raw = yaml.safe_load(f)
    if not raw or not isinstance(raw, dict):
        return {}
    return raw


def validate_external_agents_config(data: dict[str, Any]) -> list[str]:
    """Validate external agents config, return list of error messages."""
    errors: list[str] = []
    agents_list = data.get("external_agents")
    if not isinstance(agents_list, list):
        errors.append("'external_agents' must be a list")
        return errors

    seen_ids: set[str] = set()
    for agent_raw in agents_list:
        if not isinstance(agent_raw, dict):
            errors.append("Each external agent must be a dict")
            continue
        agent_id = agent_raw.get("agent_id", "")
        if not agent_id:
            errors.append("Each external agent must have an 'agent_id'")
            continue
        if agent_id in seen_ids:
            errors.append(f"Duplicate agent_id: {agent_id}")
        seen_ids.add(agent_id)

        integration_mode = agent_raw.get("integration_mode", "")
        if integration_mode != "handoff_only":
            errors.append(
                f"Agent '{agent_id}': only 'handoff_only' integration_mode is supported, got '{integration_mode}'"
            )

        billing = agent_raw.get("billing", {})
        if isinstance(billing, dict):
            token_vis = billing.get("token_visibility", "unknown")
            if token_vis != "unknown":
                errors.append(
                    f"Agent '{agent_id}': billing.token_visibility must be 'unknown', got '{token_vis}'"
                )
            api_cost_vis = billing.get("api_cost_visible", False)
            billing_mode = billing.get("mode", "")
            if billing_mode in ("subscription_quota", "external_harness"):
                if api_cost_vis is not False:
                    errors.append(
                        f"Agent '{agent_id}': billing.api_cost_visible must be false for '{billing_mode}'"
                    )

    return errors


def load_external_agents(path: Path) -> list[ExternalAgent]:
    """Load and validate external agents from config file, returning ExternalAgent dataclass instances."""
    raw = load_external_agents_config(path)
    errors = validate_external_agents_config(raw)
    for err in errors:
        print(f"WARNING: {err}")
    agents_list = raw.get("external_agents", [])
    result: list[ExternalAgent] = []
    for agent_raw in agents_list:
        if isinstance(agent_raw, dict):
            result.append(ExternalAgent.from_dict(agent_raw))
    return result


def get_external_agent(path: Path, agent_id: str) -> ExternalAgent:
    """Get a single external agent by ID. Raises ValueError if not found."""
    agents = load_external_agents(path)
    for agent in agents:
        if agent.agent_id == agent_id:
            return agent
    raise ValueError(f"Unknown external agent: {agent_id}")


# ---- singleton-style registry for backward compatibility ----
DEFAULT_CONFIG_PATH = Path("config/external_agents.yml")


class ExternalAgentRegistry:
    """Backward-compatible registry that wraps the new dataclass functions."""

    def __init__(self, config_path: str = "config/external_agents.yml"):
        self.config_path = config_path
        self._agents: list[ExternalAgent] = []
        self._agent_map: dict[str, ExternalAgent] = {}
        self._load_and_validate()

    def _load_and_validate(self) -> None:
        p = Path(self.config_path)
        if not p.exists():
            return
        self._agents = load_external_agents(p)
        self._agent_map = {a.agent_id: a for a in self._agents if a.agent_id}

    def get_agent(self, agent_id: str) -> Optional[dict[str, Any]]:
        """Get agent config as dict by ID, returns None if not found. (backward compat)"""
        agent = self._agent_map.get(agent_id)
        if agent is None:
            return None
        return {
            "agent_id": agent.agent_id,
            "display_name": agent.display_name,
            "type": agent.type,
            "enabled": agent.enabled,
            "integration_mode": agent.integration_mode,
            "capabilities": list(agent.capabilities),
            "billing": dict(agent.billing),
            "risk": dict(agent.risk),
            "allowed_task_types": list(agent.allowed_task_types),
        }

    def get_agent_object(self, agent_id: str) -> Optional[ExternalAgent]:
        """Get agent as ExternalAgent dataclass, returns None if not found."""
        return self._agent_map.get(agent_id)

    def list_agents(self) -> list[dict[str, Any]]:
        """List all agents as dicts (backward compat)."""
        result: list[dict[str, Any]] = []
        for a in self._agents:
            if a.agent_id:
                result.append({
                    "agent_id": a.agent_id,
                    "display_name": a.display_name,
                    "type": a.type,
                    "enabled": a.enabled,
                    "integration_mode": a.integration_mode,
                    "capabilities": list(a.capabilities),
                    "billing": dict(a.billing),
                    "risk": dict(a.risk),
                    "allowed_task_types": list(a.allowed_task_types),
                })
        return result

    def list_agent_objects(self) -> list[ExternalAgent]:
        """List all agents as ExternalAgent dataclass instances."""
        return list(self._agents)

    def is_agent_enabled(self, agent_id: str) -> bool:
        """Check if an agent is enabled."""
        agent = self._agent_map.get(agent_id)
        return agent.enabled if agent else False


# singleton instance
registry = ExternalAgentRegistry()