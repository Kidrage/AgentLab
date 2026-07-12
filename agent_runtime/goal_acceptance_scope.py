"""Load the explicit acceptance scope for the current AgentLab goal."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


DEFAULT_ACCEPTANCE_MODES = {
    "code_project": "full_acceptance",
    "longform_narrative": "full_live_acceptance",
    "production_pack_synthesis": "full_role_session",
    "media_generation": "full_live_acceptance",
}

ALLOWED_ACCEPTANCE_MODES = {
    "code_project": {"full_acceptance"},
    "longform_narrative": {"full_live_acceptance"},
    "production_pack_synthesis": {"full_role_session", "deterministic_scaffold_only"},
    "media_generation": {"full_live_acceptance", "readiness_only"},
}


def load_goal_acceptance_scope(root: Path) -> dict[str, Any]:
    """Return a validated scope, preserving the historical full-scope default."""
    path = root / "acceptance_runs" / "agentlab_capability_acceptance" / "goal_acceptance_scope.yml"
    if not path.exists():
        return {
            "schema_version": 1,
            "scope_id": "legacy_full_acceptance",
            "status": "legacy_default",
            "valid": True,
            "source_path": None,
            "acceptance_modes": dict(DEFAULT_ACCEPTANCE_MODES),
            "deferred_items": [],
            "validation_errors": [],
        }

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raw = {}
    configured_modes = raw.get("acceptance_modes")
    if not isinstance(configured_modes, dict):
        configured_modes = {}
    modes = {**DEFAULT_ACCEPTANCE_MODES, **configured_modes}
    errors = [
        f"unsupported acceptance mode: {key}={modes.get(key)}"
        for key, allowed in ALLOWED_ACCEPTANCE_MODES.items()
        if modes.get(key) not in allowed
    ]
    deferred_items = raw.get("deferred_items")
    if not isinstance(deferred_items, list):
        deferred_items = []
    return {
        "schema_version": raw.get("schema_version", 1),
        "scope_id": raw.get("scope_id") or "unnamed_scope",
        "status": raw.get("status") or "active",
        "valid": not errors,
        "source_path": str(path),
        "acceptance_modes": modes,
        "deferred_items": [item for item in deferred_items if isinstance(item, dict)],
        "validation_errors": errors,
    }


def acceptance_mode(scope: dict[str, Any], key: str) -> str:
    modes = scope.get("acceptance_modes")
    if not isinstance(modes, dict):
        return DEFAULT_ACCEPTANCE_MODES[key]
    return str(modes.get(key) or DEFAULT_ACCEPTANCE_MODES[key])
