"""M3-4 Config Center — grouped config views for the operator console."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def build_config_views(agentlab_root: Path) -> dict[str, Any]:
    """Build operator-facing config views from the merged configuration.

    Returns a dict keyed by view name, each containing relevant config keys
    with source traces.
    """
    try:
        from agent_runtime.config_center.loader import resolve_merged_config, load_layered_config
    except ImportError:
        return {
            "error": "config_center.loader not available",
            "views": {},
        }

    merged = resolve_merged_config(agentlab_root)
    layers = load_layered_config(agentlab_root)

    try:
        from agent_runtime.config_center.source_trace import trace_config_source
    except ImportError:
        def trace_config_source(k, m, l):
            return {"key": k, "value": _safe_get(merged, k)}

    views = {
        "global_defaults": _build_view("global_defaults", merged, layers, trace_config_source, [
            "agent_registry",
            "model_catalog",
            "model_profiles",
            "routing_policy.default_mode",
            "execution_policy",
        ]),
        "project_overrides": _build_view("project_overrides", merged, layers, trace_config_source, [
            "budget_policy",
            "cost_policy_v2",
            "content_project_governance",
        ]),
        "executor_enablement": _build_view("executor_enablement", merged, layers, trace_config_source, [
            "execution_policy.external_executor_enablement",
            "execution_policy.default_execution_mode",
            "executor_cost_profiles",
        ]),
        "skill_enablement": _build_view("skill_enablement", merged, layers, trace_config_source, [
            "skill_vault",
            "external_skill_registry",
        ]),
        "approval_thresholds": _build_view("approval_thresholds", merged, layers, trace_config_source, [
            "budget_policy.approval_threshold_usd",
            "budget_policy.max_task_cost_usd",
            "budget_policy.max_task_tokens",
            "validation_gates",
        ]),
        "budget_policy_view": _build_view("budget_policy_view", merged, layers, trace_config_source, [
            "budget_policy",
            "cost_policy_v2",
            "budget_profiles",
            "model_pricing",
        ]),
        "recovery_policy": _build_view("recovery_policy", merged, layers, trace_config_source, [
            "execution_policy.retry_enabled",
            "execution_policy.max_retries",
            "evidence_integrity_policy",
            "ops_console_policy",
        ]),
    }

    return {
        "schema_version": 1,
        "source": "agent_runtime.config_center.views",
        "views": views,
        "layer_count": len(layers),
        "layer_names": list(layers.keys()),
    }


def _build_view(
    name: str,
    merged: dict[str, Any],
    layers: dict[str, dict[str, Any]],
    trace_fn,
    keys: list[str],
) -> dict[str, Any]:
    """Build a single view with traced entries for each key."""
    entries: dict[str, Any] = {}
    for key in keys:
        entries[key] = trace_fn(key, merged, layers)
    return {
        "name": name,
        "entry_count": len(entries),
        "entries": entries,
    }


def _safe_get(data: dict[str, Any], dotted_key: str) -> Any:
    parts = dotted_key.split(".")
    current: Any = data
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current
