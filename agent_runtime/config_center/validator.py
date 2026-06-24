"""Config validation for M2-5 Config Center."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_runtime.config_center.loader import resolve_merged_config
from agent_runtime.config_center.schema import ConfigKeySchema, ConfigSchema


def load_schema(schema_path: Path) -> ConfigSchema:
    """Load a ConfigSchema from a YAML file.

    Expected YAML structure:
        keys:
          routing_policy.default_mode:
            type: str
            required: true
            ui_group: routing
            description: Default routing mode for task dispatch
    """
    import yaml

    schema = ConfigSchema()
    if not schema_path.exists():
        return schema
    data = yaml.safe_load(schema_path.read_text(encoding="utf-8")) or {}
    keys_section = data.get("keys", {}) if isinstance(data, dict) else {}
    for key, spec in (keys_section if isinstance(keys_section, dict) else {}).items():
        if isinstance(spec, dict):
            schema.keys[key] = ConfigKeySchema(
                key=key,
                type_=spec.get("type", "str"),
                required=spec.get("required", False),
                default=spec.get("default"),
                description=spec.get("description", ""),
                ui_group=spec.get("ui_group", "general"),
                ui_label=spec.get("ui_label", ""),
                secret=spec.get("secret", False),
                allowed_values=spec.get("allowed_values"),
            )
    return schema


def validate_profile_keys(
    profile_data: dict[str, Any],
    schema_keys: dict[str, Any],
    prefix: str = "",
) -> list[str]:
    """Recursively identify all keys present in profile_data but not defined in schema_keys."""
    errors: list[str] = []
    for k, v in profile_data.items():
        if k.startswith("_"):
            continue
        key_path = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            if key_path in schema_keys:
                continue
            errors.extend(validate_profile_keys(v, schema_keys, key_path))
        else:
            if key_path not in schema_keys:
                errors.append(f"error: unknown key '{key_path}'")
    return errors


def validate_config(
    config: dict[str, Any],
    schema: ConfigSchema,
) -> list[str]:
    """Validate a resolved config dict against a schema.

    Returns a list of error messages (empty = valid). Errors are prefixed
    with 'error:' for CLI rendering.
    """
    errors: list[str] = []

    for key, key_schema in schema.keys.items():
        # Navigate nested keys (e.g. "routing_policy.default_mode")
        parts = key.split(".")
        value: Any = config
        found = True
        for part in parts:
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                found = False
                value = None
                break

        if not found:
            if key_schema.required:
                errors.append(f"error: required key '{key}' is missing")
            continue

        errors.extend(key_schema.validate_value(value))

    return errors


def validate_config_dry(
    agentlab_root: Path,
    *,
    project_name: str | None = None,
    profile_override: str | None = None,
) -> list[str]:
    """Validate the fully resolved config for a project.

    Convenience wrapper: loads merged config + schema, then validates.
    """
    schema_path = agentlab_root / "config" / "config_center.yml"
    schema = load_schema(schema_path)
    config = resolve_merged_config(
        agentlab_root,
        project_name=project_name,
        profile_override=profile_override,
    )
    errors = validate_config(config, schema)

    # Load layered config to check the specific active environment profile layer for unknown keys
    from agent_runtime.config_center.loader import load_layered_config, ConfigLayer
    layers = load_layered_config(
        agentlab_root,
        project_name=project_name,
        profile_override=profile_override,
    )
    env_profile = layers.get(ConfigLayer.ENVIRONMENT_PROFILE, {})
    if env_profile:
        profile_errors = validate_profile_keys(env_profile, schema.keys)
        errors.extend(profile_errors)

    return errors
