"""Configuration loading helpers for AgentLab."""

from pathlib import Path
from typing import Any

import yaml

from policies import assert_path_allowed


CONFIG_FILES = {
    "agent_registry": "agent_registry.yml",
    "agent_model_profiles": "agent_model_profiles.yml",
    "auto_sync_policy": "auto_sync_policy.yml",
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
    "model_providers": "model_providers.yml",
    "model_profiles": "model_profiles.yml",
    "routing_policy": "routing_policy.yml",
    "routing_rules": "routing_rules.yml",
    "budget_profiles": "budget_profiles.yml",
    "budget_policy": "budget_policy.yml",
    "repo_ingestion_policy": "repo_ingestion_policy.yml",
    "repo_indexing": "repo_indexing.yml",
    "search_providers": "search_providers.yml",
    "self_check_policy": "self_check_policy.yml",
    "skill_injection_policy": "skill_injection_policy.yml",
    "task_index_policy": "task_index_policy.yml",
    "validation_gates": "validation_gates.yml",
    "version_policy": "version_policy.yml",
    "memory_policy": "memory_policy.yml",
    "migration_profile": "migration_profile.yml",
}


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data or {}


def load_agentlab_configs(agentlab_root: Path) -> dict[str, dict[str, Any]]:
    config_root = assert_path_allowed(agentlab_root / "config", agentlab_root)
    configs: dict[str, dict[str, Any]] = {}
    for key, filename in CONFIG_FILES.items():
        configs[key] = load_yaml(assert_path_allowed(config_root / filename, agentlab_root))
    return configs


def load_project_config(agentlab_root: Path, project_name: str) -> dict[str, Any]:
    path = assert_path_allowed(agentlab_root / "projects" / project_name / "project_config.yml", agentlab_root)
    return load_yaml(path)
