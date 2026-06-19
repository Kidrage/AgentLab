"""Capability lookup for external project registry records."""

from __future__ import annotations

from .models import ExternalProject


def build_capability_map(projects: list[ExternalProject]) -> dict[str, list[str]]:
    capability_map: dict[str, list[str]] = {}
    for project in projects:
        for capability in project.capabilities:
            capability_map.setdefault(capability, []).append(project.project_id)
    return {key: sorted(value) for key, value in sorted(capability_map.items())}


def providers_for_capability(projects: list[ExternalProject], capability: str) -> list[ExternalProject]:
    return [project for project in projects if capability in project.capabilities]
