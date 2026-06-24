import yaml
from pathlib import Path

def load_budget_policy(agentlab_root: Path) -> dict:
    path = agentlab_root / "config" / "cost_policy_v2.yml"
    if not path.exists():
        return {"cost_policy": {"hard_limit_usd": 10.0, "soft_limit_usd": 5.0}}
    return yaml.safe_load(path.read_text()) or {}
