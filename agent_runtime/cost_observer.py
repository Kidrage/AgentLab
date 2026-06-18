"""Lightweight local cost observability for AgentLab.

This module never calls model APIs, billing APIs, or web pricing pages. It only
summarizes local ledger data already produced by AgentLab runtime calls.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int:
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError):
        return 0


def _entry_cost_accuracy(entry: dict[str, Any]) -> str:
    explicit = str(entry.get("cost_accuracy") or "").strip()
    if explicit:
        return explicit
    if entry.get("estimated_cost") is not None or entry.get("estimated_cost_usd") is not None:
        source = str(entry.get("pricing_source") or entry.get("price_source") or "")
        return "measured" if source == "provider_bill" else "estimated"
    return "unknown"


def _entry_usage_source(entry: dict[str, Any]) -> str:
    source = str(entry.get("usage_source") or "").strip()
    if source:
        return source
    if entry.get("input_tokens") is not None or entry.get("output_tokens") is not None:
        return "provider_response"
    return "unavailable"


def _normalize_event(entry: dict[str, Any]) -> dict[str, Any]:
    input_tokens = _int(entry.get("input_tokens"))
    output_tokens = _int(entry.get("output_tokens"))
    total_tokens = _int(entry.get("total_tokens")) or input_tokens + output_tokens
    cost = _number(entry.get("estimated_cost"))
    if cost is None:
        cost = _number(entry.get("estimated_cost_usd"))
    return {
        "timestamp": entry.get("timestamp") or entry.get("started_at") or entry.get("finished_at"),
        "stage": entry.get("stage") or entry.get("node") or entry.get("agent") or "unknown",
        "agent": entry.get("agent") or "unknown",
        "provider": entry.get("provider") or "unknown",
        "model": entry.get("model") or entry.get("model_alias") or entry.get("provider_model_id") or "unknown",
        "status": entry.get("status") or "unknown",
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "estimated_cost_usd": cost,
        "usage_source": _entry_usage_source(entry),
        "price_source": entry.get("pricing_source") or entry.get("price_source") or "unknown",
        "pricing_confidence": entry.get("pricing_confidence") or "none",
        "cost_accuracy": _entry_cost_accuracy(entry),
    }


def _events_from_ledger(data: dict[str, Any]) -> list[dict[str, Any]]:
    raw_entries = data.get("entries") or data.get("calls") or []
    return [_normalize_event(item) for item in raw_entries if isinstance(item, dict)]


def _add_breakdown(target: dict[str, dict[str, Any]], key: str, event: dict[str, Any]) -> None:
    bucket = target.setdefault(
        key,
        {
            "calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "known_cost_usd": 0.0,
            "unknown_cost_events": 0,
        },
    )
    bucket["calls"] += 1
    bucket["input_tokens"] += event["input_tokens"]
    bucket["output_tokens"] += event["output_tokens"]
    bucket["total_tokens"] += event["total_tokens"]
    if event["estimated_cost_usd"] is None:
        bucket["unknown_cost_events"] += 1
    else:
        bucket["known_cost_usd"] += float(event["estimated_cost_usd"])


def cost_status(agentlab_root: Path, project: str, task_id: str) -> dict[str, Any]:
    run_dir = agentlab_root / "projects" / project / "runs" / task_id
    ledger_path = run_dir / "cost_ledger.yml"
    events = _events_from_ledger(_load_yaml(ledger_path))
    totals = {
        "calls": len(events),
        "input_tokens": sum(item["input_tokens"] for item in events),
        "output_tokens": sum(item["output_tokens"] for item in events),
        "total_tokens": sum(item["total_tokens"] for item in events),
        "known_cost_usd": round(sum(float(item["estimated_cost_usd"] or 0.0) for item in events), 8),
        "unknown_cost_events": sum(1 for item in events if item["estimated_cost_usd"] is None),
    }
    if not events:
        pricing_status = "unknown"
    elif totals["unknown_cost_events"] == 0:
        pricing_status = "complete"
    elif totals["unknown_cost_events"] < len(events):
        pricing_status = "partial"
    else:
        pricing_status = "unknown"

    by_agent: dict[str, dict[str, Any]] = {}
    by_provider: dict[str, dict[str, Any]] = {}
    for event in events:
        _add_breakdown(by_agent, str(event["agent"]), event)
        _add_breakdown(by_provider, str(event["provider"]), event)
    for group in (by_agent, by_provider):
        for bucket in group.values():
            bucket["known_cost_usd"] = round(float(bucket["known_cost_usd"]), 8)

    return {
        "project": project,
        "task_id": task_id,
        "run_dir": str(run_dir),
        "ledger_path": str(ledger_path),
        "ledger_exists": ledger_path.exists(),
        "pricing_status": pricing_status,
        "totals": totals,
        "by_agent": by_agent,
        "by_provider": by_provider,
        "events": events,
    }


def cost_doctor(agentlab_root: Path, project: str, task_id: str) -> dict[str, Any]:
    status = cost_status(agentlab_root, project, task_id)
    warnings: list[dict[str, str]] = []
    if not status["ledger_exists"]:
        warnings.append({"code": "missing_cost_ledger", "message": "cost_ledger.yml is missing."})
    if status["totals"]["calls"] == 0:
        warnings.append({"code": "no_cost_events", "message": "No cost events were recorded."})

    for event in status["events"]:
        label = f"{event['agent']}:{event['provider']}:{event['model']}"
        if event["usage_source"] in {"unknown", "unavailable"}:
            warnings.append({"code": "usage_unavailable", "message": f"{label} has no provider usage telemetry."})
        if event["estimated_cost_usd"] is None:
            warnings.append({"code": "unknown_cost", "message": f"{label} has usage/call data but no local price."})
        if event["estimated_cost_usd"] == 0 and event["cost_accuracy"] != "measured":
            warnings.append({"code": "suspicious_zero_cost", "message": f"{label} is zero-cost without measured provider bill source."})
        if event["pricing_confidence"] in {"none", "low"} and event["estimated_cost_usd"] is not None:
            warnings.append({"code": "low_pricing_confidence", "message": f"{label} cost uses {event['pricing_confidence']} confidence pricing."})
    return {
        "status": "pass" if not warnings else "warning",
        "project": project,
        "task_id": task_id,
        "warnings": warnings,
        "summary": {
            "pricing_status": status["pricing_status"],
            "known_cost_usd": status["totals"]["known_cost_usd"],
            "unknown_cost_events": status["totals"]["unknown_cost_events"],
            "total_tokens": status["totals"]["total_tokens"],
        },
    }


def render_cost_status(report: dict[str, Any]) -> str:
    totals = report["totals"]
    lines = [
        "# Cost Status",
        "",
        f"- project: {report['project']}",
        f"- task_id: {report['task_id']}",
        f"- pricing_status: {report['pricing_status']}",
        f"- known_cost_usd: {totals['known_cost_usd']:.8f}",
        f"- unknown_cost_events: {totals['unknown_cost_events']}",
        f"- total_tokens: {totals['total_tokens']}",
        "",
        "## By Agent",
    ]
    for agent, data in sorted(report["by_agent"].items()):
        lines.append(f"- {agent}: calls={data['calls']} tokens={data['total_tokens']} known_cost_usd={data['known_cost_usd']:.8f} unknown={data['unknown_cost_events']}")
    lines.append("")
    lines.append("## By Provider")
    for provider, data in sorted(report["by_provider"].items()):
        lines.append(f"- {provider}: calls={data['calls']} tokens={data['total_tokens']} known_cost_usd={data['known_cost_usd']:.8f} unknown={data['unknown_cost_events']}")
    return "\n".join(lines)


def render_cost_doctor(report: dict[str, Any]) -> str:
    lines = [
        "# Cost Doctor",
        "",
        f"- status: {report['status']}",
        f"- project: {report['project']}",
        f"- task_id: {report['task_id']}",
        f"- known_cost_usd: {report['summary']['known_cost_usd']:.8f}",
        f"- unknown_cost_events: {report['summary']['unknown_cost_events']}",
        "",
    ]
    if not report["warnings"]:
        lines.append("No cost observability issues found.")
        return "\n".join(lines)
    lines.append("## Warnings")
    for warning in report["warnings"]:
        lines.append(f"- {warning['code']}: {warning['message']}")
    return "\n".join(lines)
