"""Config loading for M1 external project registry."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"expected mapping in {path}")
    return data


def default_config_path(agentlab_root: Path) -> Path:
    return agentlab_root / "config" / "external_project_registry.yml"


def default_capability_map_path(agentlab_root: Path) -> Path:
    return agentlab_root / "config" / "external_project_capability_map.yml"


def default_risk_policy_path(agentlab_root: Path) -> Path:
    return agentlab_root / "config" / "external_project_risk_policy.yml"
