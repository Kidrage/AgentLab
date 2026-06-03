"""Cost and activity ledger helpers for AgentLab."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from state_store import utc_now


def append_yaml_list(path: Path, key: str, entry: dict[str, Any]) -> Path:
    data = {}
    if path.exists():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    data.setdefault(key, [])
    data[key].append(entry)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def usage_entry(
    project: str,
    task_id: str,
    agent_name: str,
    provider: str,
    model: str,
    status: str,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    total_tokens: int | None = None,
    notes: str = "",
) -> dict[str, Any]:
    exact_cost_available = provider not in {"codex_plus_manual"} and total_tokens is not None
    return {
        "timestamp": utc_now(),
        "project": project,
        "task_id": task_id,
        "agent": agent_name,
        "provider": provider,
        "model": model,
        "status": status,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "exact_cost_available": exact_cost_available,
        "estimated_cost": None,
        "cost_currency": None,
        "notes": notes,
    }


def append_cost_ledgers(project_root: Path, run_dir: Path, entry: dict[str, Any]) -> None:
    docs = project_root / "agent_docs"
    if docs.is_symlink() and not docs.exists() and docs.with_name("agent_docs.local.bak").is_dir():
        docs = docs.with_name("agent_docs.local.bak")
    if not docs.exists() and docs.with_name("agent_docs.local.bak").is_dir():
        docs = docs.with_name("agent_docs.local.bak")
    append_yaml_list(run_dir / "cost_ledger.yml", "entries", entry)
    append_yaml_list(docs / "09_COST_LEDGER.yml", "entries", entry)
