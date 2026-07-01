import yaml
from pathlib import Path
from dataclasses import dataclass
from typing import Dict

@dataclass
class WorkerCostProfile:
    default_model: str = "unknown"
    role_markup: float = 1.0

def load_worker_cost_profiles(agentlab_root: Path) -> Dict[str, WorkerCostProfile]:
    path = agentlab_root / "config" / "worker_cost_profiles.yml"
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    workers_data = data.get("workers", {})
    profiles = {}
    for name, item in workers_data.items():
        profiles[name] = WorkerCostProfile(
            default_model=item.get("default_model", "unknown"),
            role_markup=item.get("role_markup", 1.0),
        )
    return profiles
