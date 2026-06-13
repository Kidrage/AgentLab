"""Search ledger and artifact writing."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import uuid

import yaml

try:
    from atomic_io import atomic_write_json, atomic_write_text, atomic_write_yaml
    from state_store import utc_now
    from skills.usage_ledger import load_skill_usage_ledger, record_skill_event, write_skill_usage_ledger
except ImportError:  # pragma: no cover
    from agent_runtime.atomic_io import atomic_write_json, atomic_write_text, atomic_write_yaml
    from agent_runtime.state_store import utc_now
    from agent_runtime.skills.usage_ledger import load_skill_usage_ledger, record_skill_event, write_skill_usage_ledger


def default_search_ledger(task_id: str | None = None) -> dict[str, Any]:
    return {"schema_version": 1, "task_id": task_id, "entries": []}


def ledger_entry(*, provider: str, action: str, query: str | None = None, url: str | None = None, auth_mode: str = "unknown", request_count: int = 0, result_count: int = 0, warnings: list[str] | None = None, status: str = "ok") -> dict[str, Any]:
    return {
        "search_id": f"search_{uuid.uuid4().hex[:10]}",
        "provider": provider,
        "action": action,
        "query": query,
        "url": url,
        "auth_mode": auth_mode,
        "request_count": request_count,
        "result_count": result_count,
        "retrieved_at": utc_now(),
        "status": status,
        "cost": {
            "api_cost_visible": False,
            "token_visibility": "unknown",
            "estimated_cost_usd": None,
        },
        "warnings": list(warnings or []),
    }


def write_search_artifacts(output_dir: Path, *, task_id: str | None, action: str, response: Any) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    response_data = response.as_dict() if hasattr(response, "as_dict") else dict(response)
    entries = _entries_for_response(action, response_data, task_id)
    ledger = default_search_ledger(task_id)
    ledger["entries"].extend(entries)
    atomic_write_yaml(output_dir / "search_ledger.yml", ledger)
    atomic_write_json(output_dir / "search_results.json", response_data)
    atomic_write_text(output_dir / "search_summary.md", _summary(action, response_data, entries), encoding="utf-8")
    _record_skill_usage(output_dir, task_id or output_dir.name, entries, response_data)
    return {
        "ledger": output_dir / "search_ledger.yml",
        "results": output_dir / "search_results.json",
        "summary": output_dir / "search_summary.md",
    }


def _entries_for_response(action: str, data: dict[str, Any], task_id: str | None) -> list[dict[str, Any]]:
    _ = task_id
    if action == "batch_search":
        responses = data.get("responses") or []
        result_count = sum(len(r.get("results") or []) for r in responses if isinstance(r, dict))
        return [ledger_entry(
            provider=data.get("provider", "unknown"),
            action=action,
            auth_mode=data.get("auth_mode", "unknown"),
            request_count=(data.get("usage") or {}).get("request_count") or len(responses),
            result_count=result_count,
            warnings=data.get("warnings") or [],
            status=data.get("status", "ok"),
        )]
    if action == "url_extract":
        return [ledger_entry(
            provider=data.get("provider", "unknown"),
            action=action,
            url=data.get("url"),
            auth_mode=data.get("auth_mode", "unknown"),
            request_count=(data.get("usage") or {}).get("request_count") or 0,
            result_count=1 if data.get("text") else 0,
            warnings=data.get("warnings") or [],
            status=data.get("status", "ok"),
        )]
    return [ledger_entry(
        provider=data.get("provider", "unknown"),
        action=action,
        query=data.get("query"),
        auth_mode=data.get("auth_mode", "unknown"),
        request_count=(data.get("usage") or {}).get("request_count") or 0,
        result_count=len(data.get("results") or []),
        warnings=data.get("warnings") or [],
        status=data.get("status", "ok"),
    )]


def _summary(action: str, data: dict[str, Any], entries: list[dict[str, Any]]) -> str:
    lines = ["# Search Summary", "", f"- Action: {action}", f"- Provider: {data.get('provider')}", f"- Status: {data.get('status')}", ""]
    for entry in entries:
        lines.append(f"- Ledger entry: {entry['search_id']} ({entry['auth_mode']}, {entry['result_count']} results)")
    lines.append("")
    lines.append("Cost visibility: external cost unknown; estimated_cost_usd is null.")
    lines.append("")
    return "\n".join(lines)


def _record_skill_usage(output_dir: Path, task_id: str, entries: list[dict[str, Any]], data: dict[str, Any]) -> None:
    event = "used" if data.get("status") == "ok" else "skipped" if data.get("status") == "skipped" else "rejected"
    usage_path = output_dir / "skill_usage_ledger.yml"
    ledger = load_skill_usage_ledger(usage_path)
    for entry in entries:
        record_skill_event(
            ledger,
            task_id=task_id,
            skill_id="anysearch.web_research",
            source=entry.get("provider") or "anysearch",
            event=event,
            reason=f"search action {entry.get('action')} {data.get('status')}",
            cost_mode="external_api_or_anonymous",
            success=data.get("status") == "ok",
            evidence_artifacts=["search_ledger.yml", "search_results.json"],
        )
    successes = [e for e in ledger.get("entries", []) if e.get("skill_id") == "anysearch.web_research" and e.get("event") == "used" and e.get("success")]
    if len(successes) >= 2:
        ledger.setdefault("candidates", []).append({
            "skill_id": "internal.web_research_checklist_from_anysearch",
            "source_skill_id": "anysearch.web_research",
            "source_code_copied": False,
            "license_review_required": True,
            "status": "proposed",
        })
    write_skill_usage_ledger(usage_path, ledger)

