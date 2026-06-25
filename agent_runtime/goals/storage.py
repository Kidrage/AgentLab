import os
import yaml
from pathlib import Path
from typing import Dict, Any

def get_project_brain_dir(agentlab_root: Path, project: str) -> Path:
    brain_dir = agentlab_root / "projects" / project / "project_brain"
    brain_dir.mkdir(parents=True, exist_ok=True)
    return brain_dir

def read_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
        return data if isinstance(data, dict) else {}

def write_yaml(path: Path, data: Any):
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)

def append_to_yaml_list(path: Path, item: Any):
    data = read_yaml(path)
    if not data:
        data = {"items": []}
    elif "items" not in data:
        data["items"] = []
    
    data["items"].append(item)
    write_yaml(path, data)
