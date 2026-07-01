import yaml
from pathlib import Path
from dataclasses import dataclass
from typing import Dict

@dataclass
class ExecutorCostProfile:
    billing_mode: str = "unknown"
    direct_cost_visibility: str = "unknown"
    requires_unknown_cost_approval: bool = True

def load_executor_cost_profiles(agentlab_root: Path) -> Dict[str, ExecutorCostProfile]:
    path = agentlab_root / "config" / "executor_cost_profiles.yml"
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    executors_data = data.get("executors", {})
    profiles = {}
    for name, item in executors_data.items():
        profiles[name] = ExecutorCostProfile(
            billing_mode=item.get("billing_mode", "unknown"),
            direct_cost_visibility=item.get("direct_cost_visibility", "unknown"),
            requires_unknown_cost_approval=item.get("requires_unknown_cost_approval", True),
        )
    return profiles
