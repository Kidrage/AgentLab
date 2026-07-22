import yaml
from pathlib import Path
from dataclasses import dataclass
from typing import List

@dataclass
class ApprovalPolicy:
    policy_id: str = "default-auto"
    default_mode: str = "auto"
    require_approval_for_unknown_cli_cost: bool = True
    require_approval_for_risky_capabilities: bool = True
    require_approval_above_usd: float = 0.10
    risky_capabilities: List[str] = None
    critical_capabilities: List[str] = None
    forbidden_actions: List[str] = None
    human_required_actions: List[str] = None
    default_expiry_minutes: int = 1440

    def __post_init__(self):
        if self.risky_capabilities is None:
            self.risky_capabilities = ["shell_execution", "network_access", "filesystem_write", "external_execution", "browser_fetch"]
        if self.critical_capabilities is None:
            self.critical_capabilities = ["secrets_access", "private_path_access", "destructive_shell"]
        if self.forbidden_actions is None:
            self.forbidden_actions = [
                "approval_bypass",
                "evidence_tampering",
                "secret_exposure",
                "unbounded_destructive_operation",
            ]
        if self.human_required_actions is None:
            self.human_required_actions = [
                "public_release",
                "production_promotion",
                "git_push",
                "merge",
                "private_data_egress",
                "public_network_bind",
                "provider_route_change",
                "budget_override",
                "destructive_operation",
                "subjective_acceptance",
            ]

def load_approval_policy(agentlab_root: Path) -> ApprovalPolicy:
    path = agentlab_root / "config" / "approval_policy.yml"
    if not path.exists():
        return ApprovalPolicy()
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        policy_data = data.get("approval_policy", {})
        return ApprovalPolicy(
            policy_id=policy_data.get("policy_id", "default-auto"),
            default_mode=policy_data.get("default_mode", "auto"),
            require_approval_for_unknown_cli_cost=policy_data.get("require_approval_for_unknown_cli_cost", True),
            require_approval_for_risky_capabilities=policy_data.get("require_approval_for_risky_capabilities", True),
            require_approval_above_usd=policy_data.get("require_approval_above_usd", 0.10),
            risky_capabilities=policy_data.get("risky_capabilities"),
            critical_capabilities=policy_data.get("critical_capabilities"),
            forbidden_actions=policy_data.get("forbidden_actions"),
            human_required_actions=policy_data.get("human_required_actions"),
            default_expiry_minutes=policy_data.get("default_expiry_minutes", 1440),
        )
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid approval policy YAML: {e}")
