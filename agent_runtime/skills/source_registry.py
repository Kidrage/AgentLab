"""S3 Skill OS source registry.

The registry is metadata-only. It describes where skill candidates may be
searched later, but this module never downloads, installs, imports, or executes
skills.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


DEFAULT_REGISTRY_PATH = Path(__file__).resolve().parents[2] / "config" / "skill_source_registry.yml"

DEFAULT_REGISTRY: dict[str, Any] = {
    "schema_version": 1,
    "network_enabled": False,
    "auto_install": False,
    "require_human_review": True,
    "sources": [
        {
            "source_id": "builtin",
            "source_type": "builtin",
            "enabled": True,
            "requires_network": False,
            "description": "AgentLab built-in skill metadata.",
        },
        {
            "source_id": "local_folder",
            "source_type": "local_folder",
            "enabled": True,
            "requires_network": False,
            "description": "Reviewed local skill folders.",
        },
        {
            "source_id": "github_raw_allowlisted",
            "source_type": "github_raw_allowlisted",
            "enabled": False,
            "requires_network": True,
            "description": "Allowlisted GitHub raw SKILL.md URLs.",
        },
        {
            "source_id": "github_repo_allowlisted",
            "source_type": "github_repo_allowlisted",
            "enabled": False,
            "requires_network": True,
            "description": "Allowlisted GitHub repositories.",
        },
        {
            "source_id": "external_agent_pack",
            "source_type": "external_agent_pack",
            "enabled": False,
            "requires_network": False,
            "description": "Static external agent inventories.",
        },
        {
            "source_id": "user_uploaded",
            "source_type": "user_uploaded",
            "enabled": False,
            "requires_network": False,
            "description": "User-provided skill packages pending review.",
        },
        {
            "source_id": "self_learned_candidate",
            "source_type": "self_learned_candidate",
            "enabled": True,
            "requires_network": False,
            "description": "AgentLab self-learned draft candidates.",
        },
    ],
}

KNOWN_SOURCE_TYPES = {
    "builtin",
    "local_folder",
    "github_raw_allowlisted",
    "github_repo_allowlisted",
    "external_agent_pack",
    "user_uploaded",
    "self_learned_candidate",
}


def _merge_registry(raw: dict[str, Any] | None) -> dict[str, Any]:
    registry = {
        "schema_version": int((raw or {}).get("schema_version") or DEFAULT_REGISTRY["schema_version"]),
        "network_enabled": bool((raw or {}).get("network_enabled", DEFAULT_REGISTRY["network_enabled"])),
        "auto_install": bool((raw or {}).get("auto_install", DEFAULT_REGISTRY["auto_install"])),
        "require_human_review": bool((raw or {}).get("require_human_review", DEFAULT_REGISTRY["require_human_review"])),
        "sources": list((raw or {}).get("sources") or DEFAULT_REGISTRY["sources"]),
    }
    return registry


def load_skill_source_registry(path: Path | str | None = None) -> dict[str, Any]:
    """Load source registry YAML or return safe defaults."""

    registry_path = Path(path) if path is not None else DEFAULT_REGISTRY_PATH
    raw: dict[str, Any] | None = None
    if registry_path.exists():
        loaded = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            raw = loaded
    return _merge_registry(raw)


def validate_skill_source_registry(registry: dict[str, Any]) -> list[str]:
    """Return validation errors for source registry metadata."""

    errors: list[str] = []
    if registry.get("auto_install") is True:
        errors.append("auto_install must remain false for S3 discovery")
    sources = registry.get("sources")
    if not isinstance(sources, list):
        return ["sources must be a list"]
    seen: set[str] = set()
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            errors.append(f"sources[{index}] must be a mapping")
            continue
        source_id = str(source.get("source_id") or "").strip()
        source_type = str(source.get("source_type") or "").strip()
        if not source_id:
            errors.append(f"sources[{index}].source_id is required")
        if source_id in seen:
            errors.append(f"duplicate source_id: {source_id}")
        seen.add(source_id)
        if source_type not in KNOWN_SOURCE_TYPES:
            errors.append(f"{source_id or index}: unknown source_type '{source_type}'")
        if source.get("requires_network") and source.get("enabled") and not registry.get("network_enabled"):
            errors.append(f"{source_id}: network source enabled while network_enabled is false")
    return errors


def candidate_sources_for_plan(registry: dict[str, Any]) -> list[dict[str, Any]]:
    """Return safe source descriptors for skill_search_plan.yml."""

    network_enabled = bool(registry.get("network_enabled", False))
    candidates: list[dict[str, Any]] = []
    for source in registry.get("sources") or []:
        if not isinstance(source, dict):
            continue
        requires_network = bool(source.get("requires_network", False))
        enabled = bool(source.get("enabled", False))
        candidates.append(
            {
                "source_id": str(source.get("source_id") or ""),
                "source_type": str(source.get("source_type") or "unknown"),
                "enabled": enabled and (network_enabled or not requires_network),
                "requires_network": requires_network,
                "approval_required": True,
                "reason": "network disabled" if requires_network and not network_enabled else "metadata-only candidate source",
            }
        )
    return candidates
