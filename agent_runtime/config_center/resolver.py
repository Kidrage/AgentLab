"""Key-level config resolver for M2-5 Config Center.

Resolves config keys through all layers and returns ConfigValue
descriptors with full source-layer metadata.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_runtime.config_center.loader import load_layered_config
from agent_runtime.config_center.schema import ConfigLayer, ConfigKeySchema, ConfigValue


def _get_nested(data: dict[str, Any], key_path: str) -> Any | None:
    """Navigate nested dicts by dotted key path. Returns None if any segment missing."""
    parts = key_path.split(".")
    current: Any = data
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def _is_secret_from_schema(key: str, schema_keys: dict[str, ConfigKeySchema] | None) -> bool:
    """Check whether a key is marked secret in the schema."""
    if schema_keys is None:
        return False
    key_schema = schema_keys.get(key)
    return key_schema.secret if key_schema else False


def resolve_key(
    agentlab_root: Path,
    key: str,
    *,
    project_name: str | None = None,
    runtime_overrides: dict[str, Any] | None = None,
    schema_keys: dict[str, ConfigKeySchema] | None = None,
) -> ConfigValue | None:
    """Resolve a single config key through all layers.

    Returns a ConfigValue with the final value, source layer,
    list of lower-priority layers that were overridden, and
    secret metadata propagated from the schema.
    """
    layers = load_layered_config(
        agentlab_root,
        project_name=project_name,
        runtime_overrides=runtime_overrides,
    )

    found_value: Any = None
    found_layer: ConfigLayer | None = None
    overridden: list[ConfigLayer] = []

    for layer in ConfigLayer:
        data = layers.get(layer, {})
        value = _get_nested(data, key)
        if value is not None:
            if found_layer is not None:
                overridden.append(found_layer)
            found_value = value
            found_layer = layer

    if found_layer is None:
        return None

    return ConfigValue(
        key=key,
        value=found_value,
        layer=found_layer,
        overridden_from=overridden,
        is_secret=_is_secret_from_schema(key, schema_keys),
    )


def _collect_leaf_keys(data: dict[str, Any], prefix: str = "") -> set[str]:
    """Recursively collect dotted paths to all leaf (non-dict) values."""
    keys: set[str] = set()
    for k, v in data.items():
        full = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict) and v:
            keys.update(_collect_leaf_keys(v, full))
        else:
            keys.add(full)
    return keys


def resolve_all_keys(
    agentlab_root: Path,
    *,
    project_name: str | None = None,
    runtime_overrides: dict[str, Any] | None = None,
    keys: list[str] | None = None,
    limit: int | None = None,
    schema_keys: dict[str, ConfigKeySchema] | None = None,
) -> tuple[dict[str, ConfigValue], bool, int]:
    """Resolve multiple config keys through all layers.

    Loads layers once, then resolves each key efficiently in a single pass.

    Args:
        agentlab_root: Path to the AgentLab root directory.
        project_name: Optional project name for project-level overrides.
        runtime_overrides: Optional runtime overrides dict.
        keys: Specific keys to resolve. If None, discovers all leaf keys.
        limit: Max keys to return. If None and keys is None, returns ALL keys
               (no silent truncation). If set, result is truncated and
               ``truncated`` is set to True.
        schema_keys: Optional schema dict for propagating secret metadata.

    Returns:
        Tuple of (resolved_dict, truncated, total_available).
        ``truncated`` is True when the result was capped by ``limit``.
        ``total_available`` is the count of unique keys before any limit.
    """
    layers = load_layered_config(
        agentlab_root,
        project_name=project_name,
        runtime_overrides=runtime_overrides,
    )

    # Collect layers in order once
    ordered = [(layer, layers.get(layer, {})) for layer in ConfigLayer]

    if keys is None:
        # Discover all leaf keys from all layers
        all_keys: set[str] = set()
        for _, data in ordered:
            all_keys.update(_collect_leaf_keys(data))
        sorted_keys = sorted(all_keys)
        total = len(sorted_keys)
        if limit is not None and limit > 0:
            target_keys = sorted_keys[:limit]
            truncated = len(target_keys) < total
        else:
            target_keys = sorted_keys
            truncated = False
    else:
        target_keys = list(keys)
        total = len(target_keys)
        truncated = False

    result: dict[str, ConfigValue] = {}
    for key in target_keys:
        found_value: Any = None
        found_layer: ConfigLayer | None = None
        overridden: list[ConfigLayer] = []

        for layer, data in ordered:
            value = _get_nested(data, key)
            if value is not None:
                if found_layer is not None:
                    overridden.append(found_layer)
                found_value = value
                found_layer = layer

        if found_layer is not None:
            result[key] = ConfigValue(
                key=key,
                value=found_value,
                layer=found_layer,
                overridden_from=overridden,
                is_secret=_is_secret_from_schema(key, schema_keys),
            )

    return result, truncated, total
