import yaml
from pathlib import Path

def load_approval_policy(agentlab_root: Path) -> dict:
    path = agentlab_root / "config" / "approval_policy.yml"
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text()) or {}
