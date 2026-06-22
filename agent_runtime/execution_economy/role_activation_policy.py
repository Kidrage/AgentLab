"""Role activation policy loader and evaluator for execution economy."""

from pathlib import Path
from typing import Dict, Any, Optional
import yaml

class RoleActivationPolicy:
    def __init__(self, config_path: Optional[Path] = None):
        self.policy: Dict[str, Any] = {}
        if config_path and config_path.exists():
            try:
                self.policy = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            except Exception:
                pass
        self._ensure_defaults()

    def _ensure_defaults(self):
        # Fallback in-memory defaults if config is missing/empty
        if "roles" not in self.policy:
            self.policy["roles"] = {
                "Supervisor": {
                    "candidate_worker": "claude_code",
                    "expected_benefit": {"quality_gain": "high", "risk_reduction": "medium", "speed_gain": "medium", "recovery_value": "medium"}
                },
                "PromptEngineer": {
                    "candidate_worker": "claude_code",
                    "expected_benefit": {"quality_gain": "medium", "risk_reduction": "low", "speed_gain": "low", "recovery_value": "none"}
                },
                "Coder": {
                    "candidate_worker": "claude_code",
                    "expected_benefit": {"quality_gain": "high", "risk_reduction": "high", "speed_gain": "high", "recovery_value": "high"}
                },
                "Researcher": {
                    "candidate_worker": "claude_code",
                    "expected_benefit": {"quality_gain": "medium", "risk_reduction": "low", "speed_gain": "medium", "recovery_value": "none"}
                },
                "RepoScout": {
                    "candidate_worker": "rg",
                    "expected_benefit": {"quality_gain": "low", "risk_reduction": "low", "speed_gain": "high", "recovery_value": "none"}
                },
                "InterfaceMapper": {
                    "candidate_worker": "ast_grep",
                    "expected_benefit": {"quality_gain": "low", "risk_reduction": "low", "speed_gain": "high", "recovery_value": "none"}
                },
                "TesterAuditor": {
                    "candidate_worker": "pytest",
                    "expected_benefit": {"quality_gain": "medium", "risk_reduction": "high", "speed_gain": "medium", "recovery_value": "medium"}
                },
                "Verifier": {
                    "candidate_worker": "ruff",
                    "expected_benefit": {"quality_gain": "low", "risk_reduction": "high", "speed_gain": "low", "recovery_value": "none"}
                },
                "Archivist": {
                    "candidate_worker": "git",
                    "expected_benefit": {"quality_gain": "low", "risk_reduction": "low", "speed_gain": "medium", "recovery_value": "none"}
                }
            }

    def get_role_policy(self, role: str) -> Dict[str, Any]:
        """Get the configuration dictionary for a given role."""
        roles_config = self.policy.get("roles", {})
        return roles_config.get(role, {
            "candidate_worker": "claude_code",
            "expected_benefit": {"quality_gain": "low", "risk_reduction": "low", "speed_gain": "low", "recovery_value": "none"}
        })

    def get_candidate_worker(self, role: str) -> str:
        """Get the default candidate worker ID for a role."""
        return self.get_role_policy(role).get("candidate_worker", "claude_code")

    def get_expected_benefit(self, role: str, task_size: str = "medium") -> Dict[str, str]:
        """Get expected benefits dictionary for a role."""
        policy = self.get_role_policy(role)
        # Benefit might depend on task size
        benefit = policy.get("expected_benefit", {}).copy()
        if task_size == "small":
            # For small tasks, lower benefits to encourage skipping/coalescing
            for k in benefit:
                if benefit[k] == "high":
                    benefit[k] = "medium"
                elif benefit[k] == "medium":
                    benefit[k] = "low"
        return benefit
