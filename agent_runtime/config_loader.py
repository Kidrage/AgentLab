"""Configuration loading helpers for AgentLab."""

from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

try:
    from policies import assert_path_allowed
except ImportError:  # pragma: no cover - package import path
    from agent_runtime.policies import assert_path_allowed

try:
    from atomic_io import safe_read_yaml
except ImportError:  # pragma: no cover - package import path
    from agent_runtime.atomic_io import safe_read_yaml


CONFIG_FILES = {
    "agent_registry": "agent_registry.yml",
    "agent_model_profiles": "agent_model_profiles.yml",
    "auto_sync_policy": "auto_sync_policy.yml",
    "background_job_policy": "background_job_policy.yml",
    "backup_policy": "backup_policy.yml",
    "brain_governance": "brain_governance.yml",
    "evaluation_policy": "evaluation_policy.yml",
    "execution_policy": "execution_policy.yml",
    "execution_modes": "execution_modes.yml",
    "github_policy": "github_policy.yml",
    "harness_policy": "harness_policy.yml",
    "skill_evolution_policy": "skill_evolution_policy.yml",
    "feedback_policy": "feedback_policy.yml",
    "model_catalog": "model_catalog.yml",
    "model_capacity": "model_capacity.yml",
    "model_providers": "model_providers.yml",
    "routing_policy": "routing_policy.yml",
    "routing_rules": "routing_rules.yml",
    "budget_profiles": "budget_profiles.yml",
    "budget_policy": "budget_policy.yml",
    "context_governance": "context_governance.yml",
    "context_budget_policy": "context_budget_policy.yml",
    "hermes_brain_model_groups": "hermes_brain_model_groups.yml",
    "long_project_governance": "long_project_governance.yml",
    "compression_policy": "compression_policy.yml",
    "repo_ingestion_policy": "repo_ingestion_policy.yml",
    "repo_indexing": "repo_indexing.yml",
    "search_providers": "search_providers.yml",
    "self_check_policy": "self_check_policy.yml",
    "skill_injection_policy": "skill_injection_policy.yml",
    "task_index_policy": "task_index_policy.yml",
    "validation_gates": "validation_gates.yml",
    "version_policy": "version_policy.yml",
    "worker_invocation_contracts": "worker_invocation_contracts.yml",
    "memory_policy": "memory_policy.yml",
    "knowledge_system": "knowledge_system.yml",
    "migration_profile": "migration_profile.yml",
    "media_generation_backends": "media_generation_backends.yml",
    "production_packs": "production_packs.yml",
    "run_retention_policy": "run_retention_policy.yml",
}


@lru_cache(maxsize=256)
def _load_yaml_snapshot(
    path_text: str,
    modified_ns: int,
    size: int,
    inode: int,
) -> dict[str, Any]:
    del modified_ns, size, inode
    data = safe_read_yaml(Path(path_text), default={})
    return data if isinstance(data, dict) else {}


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        stat = path.stat()
    except OSError:
        return {}
    snapshot = _load_yaml_snapshot(
        str(path.resolve()),
        stat.st_mtime_ns,
        stat.st_size,
        getattr(stat, "st_ino", 0),
    )
    return deepcopy(snapshot)


def load_agentlab_configs(
    agentlab_root: Path,
    *,
    keys: Iterable[str] | None = None,
) -> dict[str, dict[str, Any]]:
    config_root = assert_path_allowed(agentlab_root / "config", agentlab_root)
    selected_keys = tuple(CONFIG_FILES) if keys is None else tuple(dict.fromkeys(keys))
    unknown_keys = sorted(set(selected_keys) - CONFIG_FILES.keys())
    if unknown_keys:
        raise KeyError(f"unknown AgentLab config keys: {', '.join(unknown_keys)}")
    configs: dict[str, dict[str, Any]] = {}
    for key in selected_keys:
        filename = CONFIG_FILES[key]
        configs[key] = load_yaml(assert_path_allowed(config_root / filename, agentlab_root))
    return configs


def load_project_config(agentlab_root: Path, project_name: str) -> dict[str, Any]:
    path = assert_path_allowed(agentlab_root / "projects" / project_name / "project_config.yml", agentlab_root)
    return load_yaml(path)
