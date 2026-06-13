from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from agent_runtime.atomic_io import atomic_write_yaml
from agent_runtime.retry.models import RetryAttempt, to_plain_data


SECRET_MARKERS = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY", "GITHUB_TOKEN", "sk-")


def load_retry_attempt_ledger(path: Path, task_id: str | None = None) -> dict[str, Any]:
    if path.exists():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if isinstance(data, dict):
            data.setdefault("task_id", task_id or data.get("task_id", ""))
            data.setdefault("attempts", [])
            return data
    return {"task_id": task_id or "", "attempts": []}


def write_retry_attempt_ledger(path: Path, ledger: dict[str, Any]) -> None:
    atomic_write_yaml(path, _redact(ledger))


def record_retry_attempt(path: Path, task_id: str, attempt: RetryAttempt) -> None:
    ledger = load_retry_attempt_ledger(path, task_id)
    attempts = [item for item in ledger["attempts"] if item.get("attempt_id") != attempt.attempt_id]
    attempts.append(to_plain_data(attempt))
    ledger["attempts"] = attempts
    write_retry_attempt_ledger(path, ledger)


def redact_for_ledger(value: Any) -> Any:
    return _redact(value)


def _redact(value: Any) -> Any:
    if isinstance(value, str):
        redacted = value
        for marker in SECRET_MARKERS:
            redacted = redacted.replace(marker, "[REDACTED_SECRET]")
        home = str(Path.home())
        if home in redacted:
            redacted = redacted.replace(home, "[REDACTED_HOME]")
        return redacted
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item) for key, item in value.items()}
    return value
