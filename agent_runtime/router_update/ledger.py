from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import yaml

from agent_runtime.atomic_io import atomic_write_yaml
from agent_runtime.router_update.models import RouterUpdateLedgerEntry, to_plain_data
from agent_runtime.router_update.policy import normalize_output_path


def record_router_update_event(
    ledger_path: Path,
    event: str,
    patch_id: str,
    status: str,
    reason: list[str] | None = None,
    artifacts: list[str | Path] | None = None,
) -> RouterUpdateLedgerEntry:
    entries = load_router_update_ledger(ledger_path)
    entry = RouterUpdateLedgerEntry(
        event=event,
        patch_id=patch_id,
        status=status,
        reason=[_redact(str(item)) for item in reason or []],
        artifacts=[normalize_output_path(Path(str(item))) for item in artifacts or []],
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    entries.append(entry)
    write_router_update_ledger(ledger_path, entries)
    return entry


def write_router_update_ledger(ledger_path: Path, entries: list[RouterUpdateLedgerEntry]) -> None:
    atomic_write_yaml(ledger_path, {"events": to_plain_data(entries)})


def load_router_update_ledger(ledger_path: Path) -> list[RouterUpdateLedgerEntry]:
    if not ledger_path.exists():
        return []
    data = yaml.safe_load(ledger_path.read_text(encoding="utf-8")) or {}
    items = data.get("events", data if isinstance(data, list) else [])
    entries: list[RouterUpdateLedgerEntry] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        entries.append(
            RouterUpdateLedgerEntry(
                event=str(item.get("event") or ""),
                patch_id=str(item.get("patch_id") or ""),
                status=str(item.get("status") or ""),
                reason=[_redact(str(reason)) for reason in item.get("reason") or []],
                artifacts=[normalize_output_path(Path(str(artifact))) for artifact in item.get("artifacts") or []],
                created_at=item.get("created_at"),
            )
        )
    return entries


def _redact(value: str) -> str:
    lowered = value.lower()
    if any(token in lowered for token in ("secret", "token", "api_key", "apikey", "password")):
        return "[REDACTED]"
    return value
