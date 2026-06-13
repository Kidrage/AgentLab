"""Lightweight search/repo-index plan artifact helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    from atomic_io import atomic_write_yaml
    from skills.usage_ledger import (
        load_skill_usage_ledger,
        record_skill_event,
        write_skill_usage_ledger,
    )
except ImportError:  # pragma: no cover
    from agent_runtime.atomic_io import atomic_write_yaml
    from agent_runtime.skills.usage_ledger import (
        load_skill_usage_ledger,
        record_skill_event,
        write_skill_usage_ledger,
    )


SEARCH_TASK_TYPES = {
    "web_research",
    "latest_info",
    "pricing_check",
    "open_source_tool_research",
    "docs_lookup",
}
SEARCH_TERMS = ["搜索", "调研", "latest", "recent", "pricing", "docs", "web", "url"]
REPO_INDEX_TASK_TYPES = {"repo_patch", "repo_build_test", "architecture_review"}


def maybe_write_intelligence_plans(
    run_dir: Path,
    *,
    task_id: str,
    task_text: str,
    route_key: str | None = None,
) -> list[Path]:
    """Write planned/skipped hint artifacts without calling external providers."""
    written: list[Path] = []
    lowered = task_text.lower()
    route = (route_key or "").lower()
    usage_path = run_dir / "skill_usage_ledger.yml"
    usage = load_skill_usage_ledger(usage_path)

    if route in SEARCH_TASK_TYPES or any(term in lowered for term in SEARCH_TERMS):
        search_plan = {
            "schema_version": 1,
            "task_id": task_id,
            "provider": "anysearch",
            "status": "planned_skipped",
            "reason": "search provider is disabled by default; no external call performed by pipeline hint",
            "actions": ["web_search", "batch_search", "url_extract"],
        }
        path = run_dir / "search_plan.yml"
        atomic_write_yaml(path, search_plan)
        written.append(path)
        record_skill_event(
            usage,
            task_id=task_id,
            skill_id="anysearch.web_research",
            source="anysearch",
            event="planned",
            reason="pipeline search hint generated",
            cost_mode="external_api_or_anonymous",
            success=None,
            evidence_artifacts=["search_plan.yml"],
        )

    if route in REPO_INDEX_TASK_TYPES or any(
        term in lowered
        for term in ["repo", "repository", "architecture", "build", "test", "patch"]
    ):
        repo_plan = {
            "schema_version": 1,
            "task_id": task_id,
            "indexer": "codegraph_cli",
            "status": "planned_skipped",
            "reason": "repo indexing is disabled by default and requires local checkout plus approval",
            "mode_policy": {
                "repo_profile": "deny",
                "repo_patch": "dry_run_plan",
                "repo_build_test": "pending_approval",
            },
        }
        path = run_dir / "repo_index_plan.yml"
        atomic_write_yaml(path, repo_plan)
        written.append(path)
        record_skill_event(
            usage,
            task_id=task_id,
            skill_id="codegraph.repo_index",
            source="codegraph",
            event="planned",
            reason="pipeline repo index hint generated",
            cost_mode="local_resource",
            success=None,
            evidence_artifacts=["repo_index_plan.yml"],
        )

    if written:
        write_skill_usage_ledger(usage_path, usage)
    return written
