import yaml
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, Any

@dataclass
class BudgetPolicy:
    """
    Budget policy defines soft and hard cost limits for the agent.
    """
    version: int = 2
    currency: str = "USD"
    project_soft_limit_usd: float = 5.00
    project_hard_limit_usd: float = 10.00
    phase_soft_limit_usd: float = 1.00
    phase_hard_limit_usd: float = 2.00
    task_soft_limit_usd: float = 0.50
    task_hard_limit_usd: float = 1.00
    require_approval_above_usd: float = 0.50
    cheap_model_first: bool = True
    escalate_model_on_failure: bool = True
    max_retries_before_escalation: int = 1
    stop_on_unbounded_loop: bool = True
    unknown_cli_cost_requires_approval: bool = True

    @classmethod
    def from_dict(cls, data: dict) -> 'BudgetPolicy':
        if not isinstance(data, dict):
            raise ValueError("Budget policy data must be a dictionary")
        kwargs = {}
        for k, v in data.items():
            if hasattr(cls, k):
                kwargs[k] = v
        obj = cls(**kwargs)
        if obj.project_hard_limit_usd < obj.project_soft_limit_usd:
            raise ValueError("project hard limit cannot be less than soft limit")
        if obj.phase_hard_limit_usd < obj.phase_soft_limit_usd:
            raise ValueError("phase hard limit cannot be less than soft limit")
        if obj.task_hard_limit_usd < obj.task_soft_limit_usd:
            raise ValueError("task hard limit cannot be less than soft limit")
        return obj

def load_budget_policy(agentlab_root: Path) -> BudgetPolicy:
    """
    Load the budget policy from the config file.
    If the file is missing, returns safe defaults.
    """
    path = agentlab_root / "config" / "cost_policy_v2.yml"
    if not path.exists():
        return BudgetPolicy()
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if "cost_policy" in data:
            return BudgetPolicy.from_dict(data["cost_policy"])
        return BudgetPolicy.from_dict(data)
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid cost policy YAML: {e}")
