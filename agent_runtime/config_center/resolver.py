"""Key-level config resolver for M2-5 Config Center.

Resolves config keys through all layers and returns ConfigValue
descriptors with full source-layer metadata.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_runtime.config_center.loader import load_layered_config
from agent_runtime.config_center.schema import ConfigLayer, ConfigValue


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


def resolve_key(
    agentlab_root: Path,
    key: str,
    *,
    project_name: str | None = None,
    runtime_overrides: dict[str, Any] | None = None,
) -> ConfigValue | None:
    """Resolve a single config key through all layers.

    Returns a ConfigValue with the final value, source layer,
    and list of lower-priority layers that were overridden.
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
) -> dict[str, ConfigValue]:
    """Resolve multiple config keys through all layers.

    Loads layers once, then resolves each key efficiently in a single pass.
    If ``keys`` is None, discovers all leaf keys from the merged config
    (up to 500 keys to avoid terminal flooding).
    """
    layers = load_layered_config(
        agentlab_root,
        project_name=project_name,
        runtime_overrides=runtime_overrides,
    )

    # Collect layers in order once
    ordered = [(layer, layers.get(layer, {})) for layer in ConfigLayer]

    if keys is None:
        # Discover all leaf keys from the merged (highest-layer) snapshot
        all_keys: set[str] = set()
        for _, data in ordered:
            all_keys.update(_collect_leaf_keys(data))
        target_keys = sorted(all_keys)[:500]  # cap for terminal display
    else:
        target_keys = list(keys)

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
            )

    return result
