"""Role requirements loader and registry for AgentLab roles."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml


def normalize_role_name(name: str) -> str:
    """Normalize role name to lowercase without underscores or hyphens."""
    return name.lower().replace("_", "").replace("-", "")


@dataclass(frozen=True, slots=True)
class RoleRequirementDefinition:
    role_id: str
    required_capabilities: list[str] = field(default_factory=list)
    preferred_capabilities: list[str] = field(default_factory=list)
    forbidden_capabilities: list[str] = field(default_factory=list)
    default_risk_ceiling: str = "medium"
    human_approval_required_for: list[str] = field(default_factory=list)


class RoleRequirementsRegistry:
    def __init__(self, roles: dict[str, RoleRequirementDefinition]) -> None:
        # Store under normalized keys to support case-insensitive, space/underscore-flexible lookups
        self._roles = {normalize_role_name(r.role_id): r for r in roles.values()}

    @classmethod
    def load_from_file(cls, config_path: Path) -> "RoleRequirementsRegistry":
        if not config_path.exists():
            return cls({})
        try:
            content = config_path.read_text(encoding="utf-8")
            data = yaml.safe_load(content) or {}
            roles_data = data.get("roles", {})
            
            roles = {}
            for role_name, role_info in roles_data.items():
                roles[role_name] = RoleRequirementDefinition(
                    role_id=role_name,  # preserve original casing (e.g., repo_scout)
                    required_capabilities=role_info.get("required_capabilities") or [],
                    preferred_capabilities=role_info.get("preferred_capabilities") or [],
                    forbidden_capabilities=role_info.get("forbidden_capabilities") or [],
                    default_risk_ceiling=role_info.get("default_risk_ceiling", "medium"),
                    human_approval_required_for=role_info.get("human_approval_required_for") or [],
                )
            return cls(roles)
        except Exception as e:
            return cls({})

    def get_role_requirements(self, role_name: str) -> Optional[RoleRequirementDefinition]:
        return self._roles.get(normalize_role_name(role_name))

    def list_roles(self) -> list[RoleRequirementDefinition]:
        # Return sorted by the original role_id string
        return sorted(self._roles.values(), key=lambda r: r.role_id)

    def get_all(self) -> dict[str, RoleRequirementDefinition]:
        return self._roles
