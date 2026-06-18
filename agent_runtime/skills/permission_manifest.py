"""S4 skill permission manifest validation.

This module validates declared permissions only. It never grants permissions,
executes skills, or modifies lifecycle state.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


DEFAULT_PERMISSION_POLICY_PATH = Path(__file__).resolve().parents[2] / "config" / "skill_permission_policy.yml"

DEFAULT_PERMISSION_POLICY: dict[str, Any] = {
    "schema_version": 1,
    "default_allow": False,
    "require_explicit_permissions": True,
    "blocked_permissions": ["shell", "network", "env", "secrets"],
    "approval_required_permissions": ["filesystem_write", "external_tools"],
}


def load_permission_policy(path: Path | str | None = None) -> dict[str, Any]:
    policy_path = Path(path) if path is not None else DEFAULT_PERMISSION_POLICY_PATH
    policy = dict(DEFAULT_PERMISSION_POLICY)
    if policy_path.exists():
        data = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            policy.update(data)
    return policy


def normalize_permissions(raw: dict[str, Any] | None) -> dict[str, Any]:
    permissions = raw if isinstance(raw, dict) else {}
    return {
        "filesystem_read": list(permissions.get("filesystem_read") or []),
        "filesystem_write": list(permissions.get("filesystem_write") or []),
        "shell": bool(permissions.get("shell", False)),
        "network": bool(permissions.get("network", False)),
        "env": bool(permissions.get("env", False)),
        "secrets": bool(permissions.get("secrets", False)),
        "external_tools": list(permissions.get("external_tools") or []),
    }


def validate_permission_manifest(parsed_skill: dict[str, Any], policy: dict[str, Any] | None = None) -> dict[str, Any]:
    """Validate permissions declared by a parsed skill package."""

    policy = policy or load_permission_policy()
    permissions = normalize_permissions(parsed_skill.get("permissions"))
    errors: list[str] = []
    warnings: list[str] = []
    approval_required: list[str] = []

    validation_errors = set(parsed_skill.get("validation_errors") or [])
    if policy.get("require_explicit_permissions", True) and "permissions must be declared" in validation_errors:
        errors.append("permissions must be declared explicitly")

    for key in policy.get("blocked_permissions") or []:
        value = permissions.get(key)
        if value is True or (isinstance(value, list) and value):
            errors.append(f"permission '{key}' is blocked by policy")

    for key in policy.get("approval_required_permissions") or []:
        value = permissions.get(key)
        if value is True or (isinstance(value, list) and value):
            approval_required.append(str(key))

    if permissions.get("filesystem_write"):
        warnings.append("filesystem_write requires path-scope review")

    return {
        "schema_version": 1,
        "skill_id": parsed_skill.get("skill_id"),
        "permissions": permissions,
        "policy": {
            "default_allow": bool(policy.get("default_allow", False)),
            "require_explicit_permissions": bool(policy.get("require_explicit_permissions", True)),
        },
        "approval_required": approval_required,
        "errors": errors,
        "warnings": warnings,
        "passed": not errors,
    }
