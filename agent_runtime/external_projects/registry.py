"""Deterministic external project registry for M1."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .adapter_contract import validate_adapter_contract
from .capability_mapper import build_capability_map, providers_for_capability
from .loader import default_config_path, load_yaml
from .models import ExternalProject
from .risk_profile import validate_project_safety


class ExternalProjectRegistry:
    def __init__(self, projects: list[ExternalProject]) -> None:
        self._projects: dict[str, ExternalProject] = {}
        for project in projects:
            if project.project_id in self._projects:
                raise ValueError(f"duplicate project_id: {project.project_id}")
            self._projects[project.project_id] = project
        issues = self.validate()
        if issues:
            raise ValueError("; ".join(issues))

    def validate(self) -> list[str]:
        issues: list[str] = []
        for project in self.to_sorted_projects():
            issues.extend(validate_project_safety(project))
            issues.extend(validate_adapter_contract(project))
        return issues

    def get(self, project_id: str) -> ExternalProject:
        try:
            return self._projects[project_id]
        except KeyError as exc:
            raise KeyError(f"unknown project_id: {project_id}") from exc

    def to_sorted_projects(self) -> list[ExternalProject]:
        return [self._projects[key] for key in sorted(self._projects)]

    def to_sorted_dicts(self) -> list[dict[str, Any]]:
        return [project.to_dict() for project in self.to_sorted_projects()]

    def capability_map(self) -> dict[str, list[str]]:
        return build_capability_map(self.to_sorted_projects())

    def providers_for_capability(self, capability: str) -> list[ExternalProject]:
        return providers_for_capability(self.to_sorted_projects(), capability)

    def risk_report(self) -> dict[str, Any]:
        projects = self.to_sorted_projects()
        return {
            "schema_version": 1,
            "project_count": len(projects),
            "default_enabled_count": sum(1 for item in projects if item.default_enabled),
            "high_risk_projects": [
                item.project_id for item in projects if item.risk.level == "high"
            ],
            "approval_required_projects": [
                item.project_id for item in projects if item.risk.requires_approval
            ],
            "safety_invariants": {
                "no_external_code_execution": True,
                "no_clone": True,
                "no_install": True,
                "all_default_disabled": all(not item.default_enabled for item in projects),
                "all_registry_only": all(item.integration_stage == "registry_only" for item in projects),
            },
        }


def load_external_project_registry(
    agentlab_root: Path | None = None,
    config_path: Path | None = None,
) -> ExternalProjectRegistry:
    root = agentlab_root or Path(__file__).resolve().parents[2]
    path = config_path or default_config_path(root)
    data = load_yaml(path)
    raw_projects = data.get("external_projects", [])
    if not isinstance(raw_projects, list):
        raise ValueError("external_projects must be a list")
    return ExternalProjectRegistry([ExternalProject.from_dict(item) for item in raw_projects])
