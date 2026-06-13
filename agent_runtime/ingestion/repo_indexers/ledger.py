"""Repo index ledger and artifact writing."""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    from atomic_io import atomic_write_json, atomic_write_yaml
    from skills.usage_ledger import (
        load_skill_usage_ledger,
        record_skill_event,
        write_skill_usage_ledger,
    )
except ImportError:  # pragma: no cover
    from agent_runtime.atomic_io import atomic_write_json, atomic_write_yaml
    from agent_runtime.skills.usage_ledger import (
        load_skill_usage_ledger,
        record_skill_event,
        write_skill_usage_ledger,
    )

from .semantic_library import semantic_library


def default_repo_index_ledger(task_id: str | None = None, repo_path: str | None = None) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "task_id": task_id,
        "repo_path": repo_path,
        "indexer": "codegraph_cli",
        "enabled": False,
        "dry_run": True,
        "decision": {"action": "setup_required", "reasons": []},
        "index": {
            "performed": False,
            "command": None,
            "exit_code": None,
            "index_size_mb": None,
            "indexed_files": None,
            "duration_sec": None,
        },
        "queries": [],
        "cost": {"local_resource_cost_visible": "partial", "api_cost_usd": None, "token_visibility": "unknown"},
        "warnings": [],
    }


def write_repo_index_artifacts(
    output_dir: Path,
    *,
    task_id: str | None,
    repo_path: Path,
    result: Any | None = None,
    status: Any | None = None,
    query_result: Any | None = None,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    ledger = default_repo_index_ledger(task_id, repo_path.resolve().name if repo_path.exists() else str(repo_path))
    warnings: list[str] = []
    index_status = "not_indexed"

    if status is not None:
        sdata = status.as_dict() if hasattr(status, "as_dict") else dict(status)
        ledger["indexer"] = sdata.get("indexer", "codegraph_cli")
        ledger["enabled"] = bool(sdata.get("enabled"))
        ledger["decision"] = {"action": sdata.get("status"), "reasons": sdata.get("warnings") or []}
        warnings.extend(sdata.get("warnings") or [])
        index_status = sdata.get("status") or "not_indexed"

    if result is not None:
        rdata = result.as_dict() if hasattr(result, "as_dict") else dict(result)
        ledger["indexer"] = rdata.get("indexer", "codegraph_cli")
        ledger["dry_run"] = bool(rdata.get("dry_run"))
        ledger["decision"] = rdata.get("decision") or ledger["decision"]
        ledger["index"] = {
            "performed": bool(rdata.get("performed")),
            "command": rdata.get("command"),
            "exit_code": rdata.get("exit_code"),
            "index_size_mb": rdata.get("index_size_mb"),
            "indexed_files": rdata.get("indexed_files"),
            "duration_sec": rdata.get("duration_sec"),
        }
        warnings.extend(rdata.get("warnings") or [])
        index_status = (
            "indexed"
            if rdata.get("performed")
            else "dry_run"
            if rdata.get("dry_run")
            else rdata.get("decision", {}).get("action", "not_indexed")
        )

    queries: list[dict[str, Any]] = []
    if query_result is not None:
        qdata = query_result.as_dict() if hasattr(query_result, "as_dict") else dict(query_result)
        queries.append({
            "query": qdata.get("query"),
            "tool": qdata.get("tool"),
            "result_count": len(qdata.get("results") or []),
            "warnings": qdata.get("warnings") or [],
        })
        ledger["queries"] = queries
        warnings.extend(qdata.get("warnings") or [])

    ledger["warnings"] = warnings
    status_data = status.as_dict() if hasattr(status, "as_dict") else (status or {})
    atomic_write_yaml(output_dir / "repo_index_ledger.yml", ledger)
    atomic_write_json(output_dir / "codegraph_status.json", status_data or {"status": index_status, "warnings": warnings})
    atomic_write_json(
        output_dir / "repo_semantic_library.json",
        semantic_library(
            repo_path,
            indexer=ledger["indexer"],
            index_status=index_status,
            queries=queries,
            warnings=warnings,
        ),
    )
    _record_skill_usage(output_dir, task_id or output_dir.name, ledger)
    return {
        "ledger": output_dir / "repo_index_ledger.yml",
        "status": output_dir / "codegraph_status.json",
        "semantic_library": output_dir / "repo_semantic_library.json",
    }


def _record_skill_usage(output_dir: Path, task_id: str, ledger: dict[str, Any]) -> None:
    action = (ledger.get("decision") or {}).get("action")
    event = (
        "used"
        if ledger.get("index", {}).get("performed")
        else "planned"
        if ledger.get("dry_run")
        else "skipped"
        if action in {"disabled", "setup_required"}
        else "rejected"
    )
    usage_path = output_dir / "skill_usage_ledger.yml"
    usage = load_skill_usage_ledger(usage_path)
    record_skill_event(
        usage,
        task_id=task_id,
        skill_id="codegraph.repo_index",
        source=ledger.get("indexer") or "codegraph",
        event=event,
        reason=f"repo index decision {action}",
        cost_mode="local_resource",
        success=ledger.get("index", {}).get("performed") or event == "planned",
        evidence_artifacts=["repo_index_ledger.yml", "repo_semantic_library.json"],
    )
    successes = [
        e
        for e in usage.get("entries", [])
        if e.get("skill_id") == "codegraph.repo_index"
        and e.get("event") == "used"
        and e.get("success")
    ]
    if len(successes) >= 2:
        usage.setdefault("candidates", []).append({
            "skill_id": "internal.repo_indexing_strategy_from_codegraph",
            "source_skill_id": "codegraph.repo_index",
            "source_code_copied": False,
            "license_review_required": True,
            "status": "proposed",
        })
    write_skill_usage_ledger(usage_path, usage)
