"""Capability requirement builder — determines required and optional capabilities."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def build_capability_requirements(
    project_type: str,
    project_types: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build required and optional capability lists for a project type.

    Returns dict with:
      - required: list of capability IDs that must be available
      - optional: list of capability IDs that could enhance the project
      - gaps: list of required capabilities that need backend checks
    """
    if project_types is None:
        from agent_runtime.brain.project_type_classifier import load_project_types
        project_types = load_project_types()
    typedef = project_types.get(project_type, project_types.get("unknown_project", {}))
    required = list(typedef.get("required_capabilities", []))
    optional = list(typedef.get("optional_capabilities", []))
    return {
        "required": required,
        "optional": optional,
        "gaps": [],  # filled later if capability registry has missing backends
        "total_required": len(required),
    }


def detect_capability_gaps(
    required_capabilities: list[str],
    available_capabilities: list[str] | None = None,
) -> list[str]:
    """Return required capabilities that are not available.

    If available_capabilities is None (not yet connected to registry), returns [].
    """
    if available_capabilities is None:
        return []
    available_set = set(available_capabilities)
    return [cap for cap in required_capabilities if cap not in available_set]
