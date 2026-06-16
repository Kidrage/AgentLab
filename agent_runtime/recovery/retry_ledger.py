"""Retry attempt ledger: durable tracking of retry attempts."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass
class RetryAttempt:
    """A single retry attempt record."""

    attempt: int
    created_at: str
    trigger: str  # auto_policy | human_approved | force
    verdict: str  # retry | continue | rollback | stop | human_review
    command: str
    result: str = "unknown"  # success | failed | blocked
    task_id: str = ""
    failure_category: str = ""

    def to_dict(self) -> dict:
        return {
            "attempt": self.attempt,
            "created_at": self.created_at,
            "trigger": self.trigger,
            "verdict": self.verdict,
            "command": self.command,
            "result": self.result,
            "task_id": self.task_id,
            "failure_category": self.failure_category,
        }


def load_retry_attempts(run_dir: Path) -> list[RetryAttempt]:
    """Load all retry attempts from the ledger."""
    ledger_path = run_dir / "recovery" / "retry_attempts.json"
    if not ledger_path.exists():
        return []
    try:
        data = json.loads(ledger_path.read_text(encoding="utf-8"))
        attempts = data.get("attempts", [])
        return [
            RetryAttempt(
                attempt=a.get("attempt", 0),
                created_at=a.get("created_at", ""),
                trigger=a.get("trigger", "auto_policy"),
                verdict=a.get("verdict", "retry"),
                command=a.get("command", ""),
                result=a.get("result", "unknown"),
                task_id=a.get("task_id", ""),
                failure_category=a.get("failure_category", ""),
            )
            for a in attempts
        ]
    except (json.JSONDecodeError, KeyError):
        return []


def record_retry_attempt(
    run_dir: Path,
    task_id: str,
    trigger: str,
    verdict: str,
    command: str,
    result: str = "unknown",
    failure_category: str = "",
) -> RetryAttempt:
    """Record a retry attempt in the ledger.

    Appends to the existing ledger. Creates it if it doesn't exist.
    """
    attempts = load_retry_attempts(run_dir)
    next_attempt = len(attempts) + 1

    attempt = RetryAttempt(
        attempt=next_attempt,
        created_at=datetime.now(timezone.utc).isoformat(),
        trigger=trigger,
        verdict=verdict,
        command=command,
        result=result,
        task_id=task_id,
        failure_category=failure_category,
    )
    attempts.append(attempt)

    recovery_dir = run_dir / "recovery"
    recovery_dir.mkdir(parents=True, exist_ok=True)

    ledger_path = recovery_dir / "retry_attempts.json"
    ledger_path.write_text(
        json.dumps(
            {"attempts": [a.to_dict() for a in attempts]},
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    return attempt


def retry_attempt_count(run_dir: Path) -> int:
    """Return the number of retry attempts recorded."""
    return len(load_retry_attempts(run_dir))