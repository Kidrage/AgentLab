"""Retry policy: config-driven retry decision logic."""

from __future__ import annotations

import yaml
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

from agent_runtime.recovery.failure_classifier import FailureCategory


class VerdictType(str, Enum):
    """Types of recovery verdicts."""

    RETRY = "retry"
    CONTINUE = "continue"
    ROLLBACK = "rollback"
    STOP = "stop"
    HUMAN_REVIEW = "human_review"


@dataclass
class RetryPolicyConfig:
    """Configuration for retry policy."""

    enabled: bool = True
    stdout_tail_chars: int = 8000
    stderr_tail_chars: int = 8000
    redact_secrets: bool = True
    redact_absolute_paths: bool = True
    default_max_attempts: int = 1
    max_attempts_by_category: dict[str, int] = field(default_factory=dict)
    retryable_categories: list[str] = field(default_factory=list)
    non_retryable_categories: list[str] = field(default_factory=list)
    require_human_review_for: list[str] = field(default_factory=list)
    safe_commands: list[str] = field(default_factory=list)
    forbidden_auto_commands: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> RetryPolicyConfig:
        """Create config from dictionary."""
        return cls(
            enabled=data.get("enabled", True),
            stdout_tail_chars=data.get("capture", {}).get("stdout_tail_chars", 8000),
            stderr_tail_chars=data.get("capture", {}).get("stderr_tail_chars", 8000),
            redact_secrets=data.get("capture", {}).get("redact_secrets", True),
            redact_absolute_paths=data.get("capture", {}).get("redact_absolute_paths", True),
            default_max_attempts=data.get("retry", {}).get("default_max_attempts", 1),
            max_attempts_by_category=data.get("retry", {}).get("max_attempts_by_category", {}),
            retryable_categories=data.get("retry", {}).get("retryable_categories", []),
            non_retryable_categories=data.get("retry", {}).get("non_retryable_categories", []),
            require_human_review_for=data.get("verdict", {}).get("require_human_review_for", []),
            safe_commands=data.get("safe_commands", []),
            forbidden_auto_commands=data.get("forbidden_auto_commands", []),
        )

    @classmethod
    def load(cls, config_path: Path) -> RetryPolicyConfig:
        """Load config from YAML file."""
        if not config_path.exists():
            return cls()  # Return defaults if file doesn't exist

        try:
            data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            if not data:
                return cls()
            return cls.from_dict(data)
        except Exception:
            return cls()  # Return defaults on error


@dataclass
class RecoveryVerdict:
    """Result of recovery decision."""

    task_id: str
    verdict: VerdictType
    reason: str
    allowed_attempts_remaining: int
    safe_to_auto_retry: bool
    safe_to_auto_rollback: bool
    requires_human_review: bool
    next_commands: list[str]
    forbidden_without_approval: list[str]
    created_at: str

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "task_id": self.task_id,
            "verdict": self.verdict.value,
            "reason": self.reason,
            "allowed_attempts_remaining": self.allowed_attempts_remaining,
            "safe_to_auto_retry": self.safe_to_auto_retry,
            "safe_to_auto_rollback": self.safe_to_auto_rollback,
            "requires_human_review": self.requires_human_review,
            "next_commands": self.next_commands,
            "forbidden_without_approval": self.forbidden_without_approval,
            "created_at": self.created_at,
        }


def load_retry_policy(run_dir: Path) -> RetryPolicyConfig:
    """Load retry policy from config file or use defaults.

    Args:
        run_dir: Directory containing the run, used to find config.
                 Expected pattern: <agentlab_root>/projects/<Project>/runs/<task_id>

    Returns:
        RetryPolicyConfig with settings
    """
    # Walk up from run_dir to find agentlab_root.
    # run_dir is typically <root>/projects/<Project>/runs/<task_id>
    # so parent.parent.parent = <root>
    candidate = run_dir
    for _ in range(5):  # search up to 5 levels
        config_path = candidate / "config" / "failure_recovery.yml"
        if config_path.exists():
            return RetryPolicyConfig.load(config_path)
        candidate = candidate.parent

    # Fallback: return defaults
    return RetryPolicyConfig()


def decide_retry_action(
    diagnosis: FailureDiagnosis,
    policy: RetryPolicyConfig,
    previous_attempts: int = 0,
) -> RecoveryVerdict:
    """Decide on retry action based on diagnosis and policy.

    Args:
        diagnosis: The failure diagnosis
        policy: The retry policy configuration
        previous_attempts: Number of previous retry attempts

    Returns:
        RecoveryVerdict with decision and next steps
    """
    # Get max attempts for this category
    category_str = diagnosis.primary_category.value
    max_attempts = policy.max_attempts_by_category.get(
        category_str,
        policy.default_max_attempts
    )

    # Calculate remaining attempts
    remaining = max(0, max_attempts - previous_attempts)

    # Determine if retryable
    retryable = category_str in policy.retryable_categories
    non_retryable = category_str in policy.non_retryable_categories

    # Determine human review requirement
    requires_human = diagnosis.requires_human_review or category_str in policy.require_human_review_for

    # Generate reason and verdict
    if requires_human:
        verdict = VerdictType.HUMAN_REVIEW
        reason = f"{category_str} requires human review per policy"
        safe_retry = False
        safe_rollback = False
        next_commands = []
    elif non_retryable:
        verdict = VerdictType.STOP
        reason = f"{category_str} is non-retryable per policy"
        safe_retry = False
        safe_rollback = False
        next_commands = []
    elif retryable and remaining > 0:
        verdict = VerdictType.RETRY
        reason = f"{category_str} is retryable, {remaining} attempt(s) remaining"
        safe_retry = True
        safe_rollback = False
        next_commands = _generate_retry_commands(diagnosis.primary_category)
    elif retryable and remaining <= 0:
        verdict = VerdictType.CONTINUE
        reason = f"Retry attempts exhausted for {category_str}, consider manual intervention"
        safe_retry = False
        safe_rollback = False
        next_commands = []
    else:
        verdict = VerdictType.HUMAN_REVIEW
        reason = f"Cannot determine retry policy for {category_str}"
        safe_retry = False
        safe_rollback = False
        next_commands = []

    # Get forbidden commands
    forbidden = list(policy.forbidden_auto_commands)

    # Add category-specific forbidden commands
    if diagnosis.primary_category in {
        FailureCategory.SECRET_LEAK_RISK,
        FailureCategory.PERMISSION_ERROR,
    }:
        forbidden.extend([
            "DO NOT commit or log secrets",
            "DO NOT continue automatic recovery",
        ])

    return RecoveryVerdict(
        task_id=diagnosis.task_id,
        verdict=verdict,
        reason=reason,
        allowed_attempts_remaining=remaining,
        safe_to_auto_retry=safe_retry,
        safe_to_auto_rollback=safe_rollback,
        requires_human_review=requires_human,
        next_commands=next_commands,
        forbidden_without_approval=forbidden,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def _generate_retry_commands(category: FailureCategory) -> list[str]:
    """Generate retry commands based on failure category."""
    commands = []

    if category == FailureCategory.TIMEOUT:
        commands.extend([
            "python -m pytest tests/ -q",
            "./agentlab.sh check",
        ])
    elif category == FailureCategory.CONTEXT_MISSING:
        commands.extend([
            "./agentlab.sh context-build --project AgentLab",
            "./agentlab.sh context-status --project AgentLab",
        ])
    elif category == FailureCategory.MISSING_ARTIFACT:
        commands.extend([
            "./agentlab.sh check",
            "python -m compileall agent_runtime agentlab_app.py",
        ])
    elif category == FailureCategory.TEST_FAILURE:
        commands.extend([
            "python -m pytest tests/ -q",
            "./agentlab.sh check",
        ])

    return commands
