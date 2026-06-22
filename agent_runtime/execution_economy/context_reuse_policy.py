"""Context reuse policy management and token budgeting."""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

@dataclass
class ContextBudget:
    max_raw_tokens: int = 16000
    max_effective_tokens: int = 8000
    required_assets: List[str] = field(default_factory=list)
    excluded_assets: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_raw_tokens": self.max_raw_tokens,
            "max_effective_tokens": self.max_effective_tokens,
            "required_assets": self.required_assets,
            "excluded_assets": self.excluded_assets
        }

class ContextReusePolicy:
    def __init__(self, config_path: Optional[Any] = None):
        self.policy: Dict[str, Any] = {}
        # Simple policy dict default structure
        self.policy["default"] = {
            "max_raw_tokens": 16000,
            "max_effective_tokens": 8000,
            "required_assets": [
                "task_contract",
                "changed_files_summary",
                "relevant_symbol_map",
                "acceptance_criteria"
            ],
            "excluded_assets": [
                "full_chat_history",
                "unrelated_phase_reports",
                "private_runtime_logs"
            ]
        }
        self.policy["claude_code"] = {
            "max_raw_tokens": 32000,
            "max_effective_tokens": 16000,
            "required_assets": [
                "task_contract",
                "repo_map",
                "interface_map",
                "stable_role_prefix",
                "approved_skill_context"
            ],
            "excluded_assets": [
                "full_chat_history"
            ]
        }

    def get_budget_for_worker(self, worker_id: str) -> ContextBudget:
        """Retrieve context budget configurations based on worker ID."""
        cfg = self.policy.get(worker_id, self.policy["default"])
        return ContextBudget(
            max_raw_tokens=cfg.get("max_raw_tokens", 16000),
            max_effective_tokens=cfg.get("max_effective_tokens", 8000),
            required_assets=cfg.get("required_assets", []),
            excluded_assets=cfg.get("excluded_assets", [])
        )
