"""Layered config loader for M2-5 Config Center.

Loads configuration from all layers in priority order (lowest first),
deep-merging each successive layer so higher layers override lower ones.

Each config file's contents are namespaced under its config key name
(matching the CONFIG_FILES mapping in config_loader.py), so dotted-key
lookups like `routing_policy.default_mode` resolve correctly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from agent_runtime.config_center.schema import ConfigLayer


_YAML_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively deep-merge two dicts. Override values win."""
    result: dict[str, Any] = {}
    for key, value in base.items():
        if isinstance(value, dict):
            result[key] = _deep_merge(value, {})
        elif isinstance(value, list):
            result[key] = list(value)
        else:
            result[key] = value
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML file, returning empty dict if missing or empty."""
    if not path.exists():
        return {}
    data = yaml.load(path.read_text(encoding="utf-8"), Loader=_YAML_LOADER)
    return data if isinstance(data, dict) else {}


# ── Config file → namespace key mapping ──────────────────────────────────
# Reverse of config_loader.CONFIG_FILES: filename stem → config key.
# Files not listed here use their filename stem as the namespace key.
_CONFIG_FILE_NAMESPACE: dict[str, str] = {
    # Core policy files
    "routing_policy": "routing_policy",
    "routing_rules": "routing_rules",
    "execution_policy": "execution_policy",
    "execution_modes": "execution_modes",
    "budget_policy": "budget_policy",
    "budget_profiles": "budget_profiles",
    "harness_policy": "harness_policy",
    "brain_governance": "brain_governance",
    "context_governance": "context_governance",
    "context_budget_policy": "context_budget_policy",
    "compression_policy": "compression_policy",
    "validation_gates": "validation_gates",
    "version_policy": "version_policy",
    "migration_profile": "migration_profile",
    # Model & provider
    "model_catalog": "model_catalog",
    "model_providers": "model_providers",
    "agent_registry": "agent_registry",
    "agent_model_profiles": "agent_model_profiles",
    # Skills & workers
    "skill_evolution_policy": "skill_evolution_policy",
    "skill_injection_policy": "skill_injection_policy",
    "worker_capability_defaults": "worker_capability_defaults",
    "role_assignment_policy": "role_assignment_policy",
    "capability_routing_policy": "capability_routing_policy",
    # Ingestion & search
    "repo_ingestion_policy": "repo_ingestion_policy",
    "repo_indexing": "repo_indexing",
    "search_providers": "search_providers",
    # Sync & feedback
    "auto_sync_policy": "auto_sync_policy",
    "backup_policy": "backup_policy",
    "feedback_policy": "feedback_policy",
    "evaluation_policy": "evaluation_policy",
    "memory_policy": "memory_policy",
    # Project-level
    "self_check_policy": "self_check_policy",
    "task_index_policy": "task_index_policy",
    "github_policy": "github_policy",
    # M2-5 configs (skip — loaded separately)
    "config_center": None,
    "config_ui_schema": None,
    "config_profiles": None,
    # Protocol / directory (skip — loaded at runtime separately)
    "shared_agent_directory": None,
    "agent_collaboration": None,
    "repository_handoff_policy": None,
    "worker_invocation_contracts": None,
}


def _filename_to_namespace(filename: str) -> str | None:
    """Map a config filename stem to its namespace key.

    Returns None for files that should not be included in the global layer.
    """
    stem = Path(filename).stem
    if stem in _CONFIG_FILE_NAMESPACE:
        return _CONFIG_FILE_NAMESPACE[stem]
    # For unmapped files, use the stem as the namespace
    return stem


def _load_all_yamls(dir_path: Path) -> dict[str, Any]:
    """Load all .yml files from config/ into a namespace-keyed dict.

    Each file's contents are stored under its namespace key (filename stem),
    so ``routing_policy.yml`` → ``{"routing_policy": {contents}}``.
    This allows dotted-key lookups like ``routing_policy.default_budget``.

    **Double-wrap prevention:** If a config file already uses its own filename
    stem as its sole top-level key (e.g. ``budget_policy.yml`` containing
    ``budget_policy: { ... }``), the inner dict is unwrapped to avoid
    ``budget_policy.budget_policy.*`` double-namespacing.
    """
    merged: dict[str, Any] = {}
    if not dir_path.is_dir():
        return merged
    for fpath in sorted(dir_path.glob("*.yml")):
        ns = _filename_to_namespace(fpath.name)
        if ns is None:
            continue  # skip excluded files
        data = _load_yaml(fpath)
        if not data:
            continue
        # Unwrap if the file already uses its stem as its sole top-level key
        if isinstance(data, dict) and len(data) == 1 and ns in data:
            unwrapped = data[ns]
            if isinstance(unwrapped, dict):
                data = unwrapped
        if ns in merged and isinstance(merged[ns], dict):
            merged[ns] = _deep_merge(merged[ns], data)
        else:
            merged[ns] = data
    return merged


def load_layered_config(
    agentlab_root: Path,
    *,
    project_name: str | None = None,
    runtime_overrides: dict[str, Any] | None = None,
    profile_override: str | None = None,
) -> dict[ConfigLayer, dict[str, Any]]:
    """Load config snapshots at every layer, returning {layer: config_dict}.

    Layers are loaded from lowest to highest priority. Each successive
    layer is deep-merged on top of the previous one.
    """
    config_dir = agentlab_root / "config"
    layers: dict[ConfigLayer, dict[str, Any]] = {}

    # Layer 1: Global defaults — merge all config/*.yml files, namespaced
    layers[ConfigLayer.GLOBAL_DEFAULTS] = _load_all_yamls(config_dir)

    # Layer 2: Environment profile
    env_profile_name = profile_override or _load_yaml(config_dir / "config_center.yml").get("active_profile")
    if env_profile_name:
        profiles = _load_yaml(config_dir / "config_profiles.yml")
        env_data = profiles.get("profiles", {}).get(env_profile_name, {})
        layers[ConfigLayer.ENVIRONMENT_PROFILE] = env_data
    else:
        layers[ConfigLayer.ENVIRONMENT_PROFILE] = {}

    # Layer 3: Local worker registry
    layers[ConfigLayer.LOCAL_WORKER_REGISTRY] = _load_yaml(
        config_dir / "worker_capability_defaults.yml"
    )

    # Layer 4: Role assignment policy
    layers[ConfigLayer.ROLE_ASSIGNMENT_POLICY] = _load_yaml(
        config_dir / "role_assignment_policy.yml"
    )

    # Layer 5: Cost policy
    layers[ConfigLayer.COST_POLICY] = _load_yaml(config_dir / "budget_policy.yml")

    # Layer 6: Risk policy
    layers[ConfigLayer.RISK_POLICY] = _load_yaml(config_dir / "execution_policy.yml")

    # Layer 7: Project override
    if project_name:
        proj_config = _load_yaml(
            agentlab_root / "projects" / project_name / "project_config.yml"
        )
        layers[ConfigLayer.PROJECT_OVERRIDE] = proj_config
    else:
        layers[ConfigLayer.PROJECT_OVERRIDE] = {}

    # Layer 8: Executor override
    layers[ConfigLayer.EXECUTOR_OVERRIDE] = _load_yaml(
        config_dir / "execution_modes.yml"
    )

    # Layer 9: Skill override
    layers[ConfigLayer.SKILL_OVERRIDE] = _load_yaml(
        config_dir / "skill_injection_policy.yml"
    )

    # Layer 10: Capability override
    layers[ConfigLayer.CAPABILITY_OVERRIDE] = _load_yaml(
        config_dir / "capability_routing_policy.yml"
    )

    # Layer 11: User approval override
    layers[ConfigLayer.USER_APPROVAL_OVERRIDE] = _load_yaml(
        config_dir / "harness_policy.yml"
    )

    # Layer 12: Runtime temporary
    layers[ConfigLayer.RUNTIME_TEMPORARY] = runtime_overrides or {}

    return layers


def resolve_merged_config(
    agentlab_root: Path,
    *,
    project_name: str | None = None,
    runtime_overrides: dict[str, Any] | None = None,
    profile_override: str | None = None,
) -> dict[str, Any]:
    """Return the fully merged config with all layers applied.

    This is the primary entry point — returns a single dict with
    namespaced config keys, representing the final resolved configuration.
    """
    layers = load_layered_config(
        agentlab_root,
        project_name=project_name,
        runtime_overrides=runtime_overrides,
        profile_override=profile_override,
    )
    merged: dict[str, Any] = {}
    for layer in ConfigLayer:
        data = layers.get(layer, {})
        if data:
            merged = _deep_merge(merged, data)
    return merged
