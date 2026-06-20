from pathlib import Path
from typing import Any
import yaml

def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return data or {}
    except Exception:
        return {}

def load_workflow_templates(agentlab_root: Path) -> dict[str, Any]:
    path = agentlab_root / "config" / "project_workflow_templates.yml"
    return load_yaml(path)

def load_phase_artifact_templates(agentlab_root: Path) -> dict[str, Any]:
    path = agentlab_root / "config" / "project_phase_artifact_templates.yml"
    return load_yaml(path)

def load_phase_acceptance_templates(agentlab_root: Path) -> dict[str, Any]:
    path = agentlab_root / "config" / "project_phase_acceptance_templates.yml"
    return load_yaml(path)
