"""Recovery verdict: structured decision output."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from pathlib import Path


class VerdictType(str, Enum):
    """Types of recovery verdicts."""

    RETRY = "retry"
    CONTINUE = "continue"
    ROLLBACK = "rollback"
    STOP = "stop"
    HUMAN_REVIEW = "human_review"


class RecoveryVerdict:
    """Complete recovery decision verdict.

    This is a standalone class that duplicates the dataclass from retry_policy
    to avoid circular import issues. Use the one from retry_policy for logic,
    this one is kept for backward compatibility and direct instantiation.
    """

    def __init__(
        self,
        task_id: str,
        verdict: VerdictType,
        reason: str,
        allowed_attempts_remaining: int = 0,
        safe_to_auto_retry: bool = False,
        safe_to_auto_rollback: bool = False,
        requires_human_review: bool = False,
        next_commands: list[str] | None = None,
        forbidden_without_approval: list[str] | None = None,
        created_at: str | None = None,
    ):
        """Initialize recovery verdict.

        Args:
            task_id: Task identifier
            verdict: The recovery decision (retry/continue/rollback/stop/human_review)
            reason: Human-readable explanation for the verdict
            allowed_attempts_remaining: Number of retry attempts still allowed
            safe_to_auto_retry: Whether retry can be auto-executed
            safe_to_auto_rollback: Whether rollback can be auto-executed
            requires_human_review: Whether human review is required
            next_commands: List of recommended next commands
            forbidden_without_approval: List of commands requiring approval
            created_at: ISO timestamp of verdict creation
        """
        self.task_id = task_id
        self.verdict = verdict
        self.reason = reason
        self.allowed_attempts_remaining = allowed_attempts_remaining
        self.safe_to_auto_retry = safe_to_auto_retry
        self.safe_to_auto_rollback = safe_to_auto_rollback
        self.requires_human_review = requires_human_review
        self.next_commands = next_commands or []
        self.forbidden_without_approval = forbidden_without_approval or []
        self.created_at = created_at or datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "task_id": self.task_id,
            "verdict": self.verdict.value if isinstance(self.verdict, VerdictType) else self.verdict,
            "reason": self.reason,
            "allowed_attempts_remaining": self.allowed_attempts_remaining,
            "safe_to_auto_retry": self.safe_to_auto_retry,
            "safe_to_auto_rollback": self.safe_to_auto_rollback,
            "requires_human_review": self.requires_human_review,
            "next_commands": self.next_commands,
            "forbidden_without_approval": self.forbidden_without_approval,
            "created_at": self.created_at,
        }

    def to_json_path(self, run_dir: Path) -> Path:
        """Return path for recovery_verdict.json within run directory."""
        recovery_dir = run_dir / "recovery"
        recovery_dir.mkdir(parents=True, exist_ok=True)
        return recovery_dir / "recovery_verdict.json"


def create_verdict_from_diagnosis(
    task_id: str,
    project: str,
    primary_category: str,
    requires_human_review: bool,
    max_attempts: int = 1,
    previous_attempts: int = 0,
) -> RecoveryVerdict:
    """Create a verdict from diagnosis parameters.

    This is a convenience function for creating verdicts without
    full diagnosis object when only basic info is available.

    Args:
        task_id: Task identifier
        project: Project name
        primary_category: Primary failure category string
        requires_human_review: Whether human review is required
        max_attempts: Maximum allowed retry attempts
        previous_attempts: Number of previous attempts

    Returns:
        RecoveryVerdict with appropriate decision
    """
    remaining = max(0, max_attempts - previous_attempts)

    # Determine verdict based on category and requirements
    if requires_human_review:
        verdict = VerdictType.HUMAN_REVIEW
        reason = f"Category '{primary_category}' requires human review"
        safe_retry = False
        safe_rollback = False
        next_commands = []
    elif remaining > 0:
        # Category-specific verdicts
        if primary_category in {
            "timeout",
            "resource_limit",
            "network_disabled_or_unavailable",
        }:
            verdict = VerdictType.RETRY
            reason = f"Category '{primary_category}' is retryable"
            safe_retry = True
            safe_rollback = False
            next_commands = []
        elif primary_category in {
            "missing_artifact",
            "context_missing",
        }:
            verdict = VerdictType.CONTINUE
            reason = f"Category '{primary_category}' allows continuation"
            safe_retry = False
            safe_rollback = False
            next_commands = []
        else:
            verdict = VerdictType.STOP
            reason = f"Category '{primary_category}' is not retryable"
            safe_retry = False
            safe_rollback = False
            next_commands = []
    else:
        verdict = VerdictType.STOP
        reason = f"Retry attempts exhausted for category '{primary_category}'"
        safe_retry = False
        safe_rollback = False
        next_commands = []

    return RecoveryVerdict(
        task_id=task_id,
        verdict=verdict,
        reason=reason,
        allowed_attempts_remaining=remaining,
        safe_to_auto_retry=safe_retry,
        safe_to_auto_rollback=safe_rollback,
        requires_human_review=requires_human_review,
        next_commands=next_commands,
        forbidden_without_approval=[
            "git reset --hard",
            "git clean -fdx",
            "rm -rf",
            "git push",
        ],
        created_at=datetime.now(timezone.utc).isoformat(),
    )
