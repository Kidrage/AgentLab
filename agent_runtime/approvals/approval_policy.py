import yaml
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, Any, List

@dataclass
class ApprovalPolicy:
    require_approval_for_unknown_cli_cost: bool = True
    require_approval_for_risky_capabilities: bool = True
    require_approval_above_usd: float = 0.50
    risky_capabilities: List[str] = None
    critical_capabilities: List[str] = None
    default_expiry_minutes: int = 1440

    def __post_init__(self):
        if self.risky_capabilities is None:
            self.risky_capabilities = ["shell_execution", "network_access", "filesystem_write", "external_execution", "browser_fetch"]
        if self.critical_capabilities is None:
            self.critical_capabilities = ["secrets_access", "private_path_access", "destructive_shell"]

def load_approval_policy(agentlab_root: Path) -> ApprovalPolicy:
    path = agentlab_root / "config" / "approval_policy.yml"
    if not path.exists():
        return ApprovalPolicy()
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        policy_data = data.get("approval_policy", {})
        return ApprovalPolicy(
            require_approval_for_unknown_cli_cost=policy_data.get("require_approval_for_unknown_cli_cost", True),
            require_approval_for_risky_capabilities=policy_data.get("require_approval_for_risky_capabilities", True),
            require_approval_above_usd=policy_data.get("require_approval_above_usd", 0.50),
            risky_capabilities=policy_data.get("risky_capabilities"),
            critical_capabilities=policy_data.get("critical_capabilities"),
            default_expiry_minutes=policy_data.get("default_expiry_minutes", 1440),
        )
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid approval policy YAML: {e}")
