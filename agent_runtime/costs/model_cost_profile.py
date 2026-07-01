import yaml
from pathlib import Path
from dataclasses import dataclass
from typing import Dict

@dataclass
class ModelCostProfile:
    input_usd_per_million_tokens: float = 0.0
    output_usd_per_million_tokens: float = 0.0
    cached_input_discount: float = 0.0

def load_model_cost_profiles(agentlab_root: Path) -> Dict[str, ModelCostProfile]:
    path = agentlab_root / "config" / "model_cost_profiles.yml"
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    models_data = data.get("models", {})
    profiles = {}
    for name, item in models_data.items():
        profiles[name] = ModelCostProfile(
            input_usd_per_million_tokens=item.get("input_usd_per_million_tokens", 0.0),
            output_usd_per_million_tokens=item.get("output_usd_per_million_tokens", 0.0),
            cached_input_discount=item.get("cached_input_discount", 0.0),
        )
    return profiles
