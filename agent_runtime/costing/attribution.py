"""M3-5 Cost System v2 — phase/task/retry cost attribution."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def attribute_cost_by_phase(
    calls: list[dict[str, Any]],
    task_phase_map: dict[str, str],
) -> dict[str, Any]:
    """Attribute costs to phases.

    Args:
        calls: list of cost call dicts (each must have 'stage' or 'phase' key)
        task_phase_map: {task_id: phase_id} mapping

    Returns:
        {phase_id: {total_cost, call_count, models_used: [...], tasks: [...]}}
    """
    phases: dict[str, dict[str, Any]] = {}
    for call in calls:
        if not isinstance(call, dict):
            continue
        phase = call.get("phase") or call.get("stage") or "unknown"
        cost = call.get("estimated_cost_usd")
        model = call.get("model_alias") or call.get("provider_model_id") or "unknown"

        if phase not in phases:
            phases[phase] = {"total_cost": 0.0, "call_count": 0, "models_used": [], "tasks": []}
        entry = phases[phase]
        entry["call_count"] += 1
        if cost is not None:
            entry["total_cost"] += float(cost)
        if model not in entry["models_used"]:
            entry["models_used"].append(model)

    for phase_id in phases:
        phases[phase_id]["total_cost"] = round(phases[phase_id]["total_cost"], 6)

    return {
        "phases": phases,
        "phase_count": len(phases),
        "total_phases_cost": round(sum(p["total_cost"] for p in phases.values()), 6),
    }


def attribute_cost_by_task(calls: list[dict[str, Any]]) -> dict[str, Any]:
    """Attribute costs per task.

    Args:
        calls: list of cost call dicts (each must have 'task_id' key)

    Returns:
        {task_id: {total_cost, call_count, models: [...]}}
    """
    tasks: dict[str, dict[str, Any]] = {}
    for call in calls:
        if not isinstance(call, dict):
            continue
        task_id = call.get("task_id") or "unknown"
        cost = call.get("estimated_cost_usd")
        model = call.get("model_alias") or call.get("provider_model_id") or "unknown"

        if task_id not in tasks:
            tasks[task_id] = {"total_cost": 0.0, "call_count": 0, "models": []}
        entry = tasks[task_id]
        entry["call_count"] += 1
        if cost is not None:
            entry["total_cost"] += float(cost)
        if model not in entry["models"]:
            entry["models"].append(model)

    for tid in tasks:
        tasks[tid]["total_cost"] = round(tasks[tid]["total_cost"], 6)

    return {
        "tasks": tasks,
        "task_count": len(tasks),
    }


def build_cost_efficiency_report(
    calls: list[dict[str, Any]],
    accepted_phase_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Build a cost efficiency report across dimensions.

    Returns:
        {
            by_model: {model: {total_cost, call_count}},
            by_executor: {executor: {total_cost, call_count}},
            cost_per_accepted_phase: float | None,
            highest_cost_model: str | None,
            highest_cost_executor: str | None,
        }
    """
    by_model: dict[str, dict[str, Any]] = {}
    by_executor: dict[str, dict[str, Any]] = {}
    total_cost = 0.0

    for call in calls:
        if not isinstance(call, dict):
            continue
        cost = call.get("estimated_cost_usd")
        cost_val = float(cost) if cost is not None else 0.0
        total_cost += cost_val

        model = call.get("model_alias") or call.get("provider_model_id") or "unknown"
        executor = call.get("agent") or call.get("executor_id") or "unknown"

        if model not in by_model:
            by_model[model] = {"total_cost": 0.0, "call_count": 0}
        by_model[model]["total_cost"] += cost_val
        by_model[model]["call_count"] += 1

        if executor not in by_executor:
            by_executor[executor] = {"total_cost": 0.0, "call_count": 0}
        by_executor[executor]["total_cost"] += cost_val
        by_executor[executor]["call_count"] += 1

    # find highest cost
    highest_cost_model = max(by_model, key=lambda m: by_model[m]["total_cost"]) if by_model else None
    highest_cost_executor = max(by_executor, key=lambda e: by_executor[e]["total_cost"]) if by_executor else None

    accepted_count = len(accepted_phase_ids) if accepted_phase_ids else 0
    cost_per_accepted = round(total_cost / accepted_count, 6) if accepted_count > 0 else None

    return {
        "by_model": {m: {"total_cost": round(d["total_cost"], 6), "call_count": d["call_count"]} for m, d in by_model.items()},
        "by_executor": {e: {"total_cost": round(d["total_cost"], 6), "call_count": d["call_count"]} for e, d in by_executor.items()},
        "cost_per_accepted_phase": cost_per_accepted,
        "total_cost": round(total_cost, 6),
        "highest_cost_model": highest_cost_model,
        "highest_cost_executor": highest_cost_executor,
    }


def calculate_retry_cost_impact(
    calls: list[dict[str, Any]],
    retry_ledger_entries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Calculate the cost impact of retries.

    Args:
        calls: all cost calls
        retry_ledger_entries: optional retry ledger entries for identifying retried tasks

    Returns:
        {total_retry_cost, retry_count, retried_task_ids: [...], retry_cost_pct: float}
    """
    retry_task_ids: set[str] = set()
    if retry_ledger_entries:
        for entry in retry_ledger_entries:
            if isinstance(entry, dict) and entry.get("task_id"):
                retry_task_ids.add(str(entry["task_id"]))

    retry_cost = 0.0
    total_cost = 0.0
    for call in calls:
        if not isinstance(call, dict):
            continue
        cost = call.get("estimated_cost_usd")
        cost_val = float(cost) if cost is not None else 0.0
        total_cost += cost_val
        task_id = str(call.get("task_id") or "")
        if task_id in retry_task_ids:
            retry_cost += cost_val

    retry_pct = round(retry_cost / total_cost * 100, 2) if total_cost > 0 else 0.0

    return {
        "total_retry_cost": round(retry_cost, 6),
        "total_cost": round(total_cost, 6),
        "retry_count": len(retry_task_ids),
        "retried_task_ids": sorted(retry_task_ids),
        "retry_cost_pct": retry_pct,
    }
