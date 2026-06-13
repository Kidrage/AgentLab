from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from agent_runtime.atomic_io import atomic_write_yaml
from agent_runtime.executors.models import ExecutionLedgerEntry, to_plain_data

SECRET_MARKERS = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GITHUB_TOKEN", "sk_")


def load_execution_ledger(path: Path, task_id: str | None = None) -> dict[str, Any]:
    if path.exists():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if isinstance(data, dict):
            data.setdefault("task_id", task_id or data.get("task_id", ""))
            data.setdefault("entries", [])
            return data
    return {"task_id": task_id or "", "entries": []}


def write_execution_ledger(path: Path, ledger: dict[str, Any]) -> None:
    atomic_write_yaml(path, _redact(ledger))


def record_execution_event(
    ledger_path: Path,
    task_id: str,
    event: str,
    provider_id: str,
    provider_type: str,
    execution_mode: str,
    status: str,
    reason: list[str] | None = None,
    artifacts: list[str] | None = None,
    created_at: str | None = None,
) -> ExecutionLedgerEntry:
    ledger = load_execution_ledger(ledger_path, task_id=task_id)
    entry = ExecutionLedgerEntry(
        event=event,
        provider_id=provider_id,
        provider_type=provider_type,
        execution_mode=execution_mode,
        status=status,
        reason=reason or [],
        artifacts=artifacts or [],
        created_at=created_at or datetime.now(timezone.utc).isoformat(),
    )
    ledger["entries"].append(to_plain_data(entry))
    write_execution_ledger(ledger_path, ledger)
    return entry


def _redact(value: Any) -> Any:
    if isinstance(value, str):
        redacted = value
        for marker in SECRET_MARKERS:
            if marker in redacted:
                redacted = redacted.replace(marker, "[REDACTED_SECRET]")
        return redacted
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item) for key, item in value.items()}
    return value
