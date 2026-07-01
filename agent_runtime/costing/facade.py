"""Canonical Cost System v2 facade for operator surfaces."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from agent_runtime.costing.attribution import (
    attribute_cost_by_phase,
    attribute_cost_by_task,
    build_cost_efficiency_report,
    calculate_retry_cost_impact,
)


def build_cost_state(project_root: Path, accepted_phase_ids: list[str] | None = None) -> dict[str, Any]:
    """Build the canonical operator cost state for a project."""
    runs_dir = project_root / "runs"
    calls, per_task_ledgers = collect_project_cost_calls(project_root)
    total_cost = 0.0
    has_known_cost = False
    total_tokens = 0

    for call in calls:
        cost = call.get("estimated_cost_usd")
        if cost is not None:
            total_cost += float(cost)
            has_known_cost = True
        total_tokens += int(call.get("input_tokens") or 0)
        total_tokens += int(call.get("output_tokens") or 0)
        total_tokens += int(call.get("cache_read_tokens") or 0)
        total_tokens += int(call.get("cache_write_tokens") or 0)
        total_tokens += int(call.get("reasoning_tokens") or 0)

    global_ledger_path = project_root.parent.parent / "costs" / "cost_ledger.jsonl"
    retry_entries = _read_retry_entries(runs_dir)

    return {
        "schema_version": 2,
        "source": "agent_runtime.costing.facade",
        "total_estimated_cost_usd": round(total_cost, 6) if has_known_cost else None,
        "has_cost_data": bool(calls) or global_ledger_path.exists(),
        "global_cost_ledger_present": global_ledger_path.exists(),
        "per_task_ledgers": per_task_ledgers,
        "total_tokens": total_tokens,
        "call_count": len(calls),
        "attribution": {
            "by_phase": attribute_cost_by_phase(calls, {})["phases"],
            "by_task": attribute_cost_by_task(calls)["tasks"],
            "efficiency": build_cost_efficiency_report(calls, accepted_phase_ids=accepted_phase_ids),
            "retry_impact": calculate_retry_cost_impact(calls, retry_entries),
        },
        "legacy_sources": {
            "costs_package_compatibility": True,
            "cost_tracker_compatibility": True,
        },
    }


def collect_project_cost_calls(project_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Collect normalized cost calls and per-task ledger summaries."""
    runs_dir = project_root / "runs"
    calls: list[dict[str, Any]] = []
    per_task_ledgers: list[dict[str, Any]] = []
    if not runs_dir.exists():
        return calls, per_task_ledgers

    for task_dir in sorted(runs_dir.iterdir()):
        if not task_dir.is_dir():
            continue
        ledger_path = task_dir / "cost_ledger.yml"
        if not ledger_path.exists():
            continue
        ledger = _load_yaml(ledger_path, {})
        if not isinstance(ledger, dict):
            continue
        raw_calls = ledger.get("calls") or ledger.get("entries") or []
        normalized_calls = [
            call
            for call in (_normalize_call(item, task_dir.name) for item in raw_calls)
            if call is not None
        ]
        task_total = sum(float(call["estimated_cost_usd"]) for call in normalized_calls if call.get("estimated_cost_usd") is not None)
        calls.extend(normalized_calls)
        per_task_ledgers.append({
            "task_id": task_dir.name,
            "source": str(ledger_path.relative_to(project_root)),
            "call_count": len(normalized_calls),
            "estimated_cost_usd": round(task_total, 6),
        })

    return calls, per_task_ledgers


def _normalize_call(item: Any, task_id: str) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    call = dict(item)
    call.setdefault("task_id", task_id)
    call.setdefault("stage", call.get("phase") or call.get("phase_id") or "unknown")
    call.setdefault("agent", call.get("executor_id") or call.get("worker") or "unknown")
    if "estimated_cost_usd" not in call and "estimated_cost" in call:
        call["estimated_cost_usd"] = call.get("estimated_cost")
    if "model_alias" not in call and call.get("model"):
        call["model_alias"] = call.get("model")
    return call


def _read_retry_entries(runs_dir: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    if not runs_dir.exists():
        return entries
    for task_dir in sorted(runs_dir.iterdir()):
        if not task_dir.is_dir():
            continue
        for name in ("retry_attempt_ledger.yml", "retry_ledger.yml"):
            path = task_dir / name
            if not path.exists():
                continue
            data = _load_yaml(path, {})
            if isinstance(data, dict):
                raw_entries = data.get("entries") or data.get("attempts") or []
                if isinstance(raw_entries, list):
                    for entry in raw_entries:
                        if isinstance(entry, dict):
                            item = dict(entry)
                            item.setdefault("task_id", task_dir.name)
                            entries.append(item)
            elif isinstance(data, list):
                for entry in data:
                    if isinstance(entry, dict):
                        item = dict(entry)
                        item.setdefault("task_id", task_dir.name)
                        entries.append(item)
    return entries


def _load_yaml(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return default
    return data if data is not None else default


def read_global_cost_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read global cost JSONL records for future M4 attribution links."""
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            records.append(item)
    return records
