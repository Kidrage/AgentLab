"""M3-4 Config Center — config source tracing.

Answers: "where did this value come from?"
"""

from __future__ import annotations

from typing import Any


def trace_config_source(
    key: str,
    merged_config: dict[str, Any],
    layers: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Trace a config key back through layered config to find its origin.

    Args:
        key: dot-separated config key, e.g. "budget_policy.max_task_cost_usd"
        merged_config: the fully merged config dict (from resolve_merged_config)
        layers: dict of {layer_name: config_dict} (from load_layered_config)

    Returns:
        {key, value, source_layer, overridden_by: [...], all_layer_values: {...}}
    """
    parts = key.split(".")
    all_layer_values: dict[str, Any] = {}
    source_layer = "unknown"
    overridden_by: list[str] = []
    found_first = False
    resolved_value = _deep_get(merged_config, parts)

    layer_order = list(layers.keys())
    # iterate FORWARD (lowest priority first) to find original source layer
    for layer_name in layer_order:
        layer_config = layers.get(layer_name, {})
        layer_value = _deep_get(layer_config, parts)
        if layer_value is not _MISSING:
            all_layer_values[layer_name] = layer_value
            if not found_first:
                source_layer = layer_name
                found_first = True
    # then collect higher-priority layers that override it
    source_idx = layer_order.index(source_layer) if source_layer in layer_order else -1
    for i in range(source_idx + 1, len(layer_order)):
        layer_name = layer_order[i]
        layer_config = layers.get(layer_name, {})
        if _deep_get(layer_config, parts) is not _MISSING:
            overridden_by.append(layer_name)

    return {
        "key": key,
        "value": resolved_value if resolved_value is not _MISSING else None,
        "source_layer": source_layer,
        "overridden_by": overridden_by,
        "all_layer_values": all_layer_values,
    }


def trace_all_config_sources(
    merged_config: dict[str, Any],
    layers: dict[str, dict[str, Any]],
    prefix: str = "",
) -> list[dict[str, Any]]:
    """Recursively trace all keys under a given prefix."""
    results: list[dict[str, Any]] = []
    target = _deep_get(merged_config, prefix.split(".")) if prefix else merged_config
    if not isinstance(target, dict):
        return results

    for key, value in target.items():
        full_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            results.extend(trace_all_config_sources(merged_config, layers, full_key))
        else:
            results.append(trace_config_source(full_key, merged_config, layers))
    return results


class _Missing:
    """Sentinel for missing values (None is a valid config value)."""
    def __repr__(self) -> str:
        return "<MISSING>"


_MISSING = _Missing()


def _deep_get(data: Any, parts: list[str]) -> Any:
    """Walk nested dict by key path; return _MISSING if absent."""
    current = data
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part, _MISSING)
        else:
            return _MISSING
    return current
