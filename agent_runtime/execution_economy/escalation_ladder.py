"""Escalation ladder logic and state transition triggers for execution economy."""

from typing import Dict, Any, Optional

class EscalationLadder:
    def __init__(self, config_path: Optional[Any] = None):
        self.rules: Dict[str, str] = {
            "initial": "deterministic_scan",
            "if_missing_context": "api_supervisor_compact",
            "if_patch_needed": "single_cli_coder",
            "if_tests_fail": "cached_failure_analyzer",
            "if_diff_high_risk": "cached_or_strong_llm_verifier",
            "if_repeated_failure": "multi_agent_redesign",
            "if_budget_exceeded": "stop_or_ask_user",
            "if_cache_miss_or_unknown_cost": "downgrade_or_require_approval"
        }

    def get_escalation_target(self, trigger: str) -> str:
        """Get the next escalation target based on trigger."""
        return self.rules.get(trigger, "stop_or_ask_user")

    def to_dict(self) -> Dict[str, str]:
        return self.rules
