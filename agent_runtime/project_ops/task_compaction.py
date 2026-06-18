"""Task compaction and memory-promotion candidate extraction."""

from __future__ import annotations

import hashlib
from dataclasses import asdict
from pathlib import Path
from typing import Any

import yaml

from .models import TaskCompactionResult


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _safe_read(path: Path, limit: int = 4000) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return ""
    return text[:limit]


def _artifact_index(task_dir: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for path in sorted(task_dir.rglob("*")):
        if path.is_file() and "task_compact" not in path.parts:
            rel = path.relative_to(task_dir).as_posix()
            entries.append(
                {
                    "path": rel,
                    "size_bytes": path.stat().st_size,
                    "sha256": _file_hash(path),
                }
            )
    return entries


def _find_memory_promotions(task_dir: Path) -> dict[str, list[dict[str, Any]]]:
    promotions: dict[str, list[dict[str, Any]]] = {
        "decisions": [],
        "unresolved_items": [],
        "reusable_patterns": [],
        "failure_patterns": [],
        "skill_candidates": [],
    }
    keywords = {
        "decisions": ["decision", "decided", "verdict", "accepted", "rejected"],
        "unresolved_items": ["unresolved", "todo", "blocked", "needs follow-up"],
        "reusable_patterns": ["pattern", "reusable", "repeat", "checklist"],
        "failure_patterns": ["failure", "failed", "regression", "error"],
        "skill_candidates": ["skill", "candidate", "incubation"],
    }
    for path in sorted(task_dir.rglob("*")):
        if not path.is_file() or "task_compact" in path.parts:
            continue
        text = _safe_read(path).lower()
        rel = path.relative_to(task_dir).as_posix()
        for category, words in keywords.items():
            if any(word in text for word in words):
                promotions[category].append({"source": rel, "reason": f"Matched {category} keyword."})
    return promotions


def compact_task(
    project_id: str,
    task_id: str,
    task_dir: Path,
    policy: dict[str, Any] | None = None,
    execute_prune: bool = False,
) -> TaskCompactionResult:
    """Create compact task summaries without deleting raw artifacts by default."""

    if not task_dir.exists():
        raise FileNotFoundError(f"Task directory not found: {task_dir}")
    compact_dir = task_dir / "task_compact"
    compact_dir.mkdir(parents=True, exist_ok=True)

    artifact_entries = _artifact_index(task_dir)
    promotions = _find_memory_promotions(task_dir)

    summary_lines = [
        "# Task Compact Summary",
        "",
        f"- Project: `{project_id}`",
        f"- Task: `{task_id}`",
        f"- Raw artifact count: {len(artifact_entries)}",
        f"- Prune executed: {execute_prune}",
        "",
        "## Purpose",
        "",
        "This compact summary allows future agents to inspect the task outcome without rereading all raw logs.",
        "",
    ]
    (compact_dir / "task_summary.md").write_text("\n".join(summary_lines), encoding="utf-8")

    final_verdict = {
        "project_id": project_id,
        "task_id": task_id,
        "verdict": "compacted",
        "raw_artifacts_preserved": not execute_prune,
        "notes": "S2.5 compaction does not judge business quality; it creates an audit index.",
    }
    (compact_dir / "final_verdict.yml").write_text(yaml.safe_dump(final_verdict, sort_keys=False), encoding="utf-8")
    (compact_dir / "artifact_index.yml").write_text(
        yaml.safe_dump({"artifacts": artifact_entries}, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    (compact_dir / "decision_delta.yml").write_text(
        yaml.safe_dump({"decisions": promotions["decisions"]}, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    (compact_dir / "memory_promotions.yml").write_text(
        yaml.safe_dump(promotions, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    (compact_dir / "unresolved_items.yml").write_text(
        yaml.safe_dump({"items": promotions["unresolved_items"]}, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    (compact_dir / "reusable_patterns.yml").write_text(
        yaml.safe_dump({"patterns": promotions["reusable_patterns"]}, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    (compact_dir / "cost_summary.yml").write_text(
        yaml.safe_dump({"project_id": project_id, "task_id": task_id, "estimated_cost_usd": None}, sort_keys=False),
        encoding="utf-8",
    )
    (compact_dir / "agent_contribution_summary.yml").write_text(
        yaml.safe_dump({"agents": []}, sort_keys=False),
        encoding="utf-8",
    )

    created = [str(path) for path in sorted(compact_dir.iterdir()) if path.is_file()]
    raw_preserved = [entry["path"] for entry in artifact_entries]
    return TaskCompactionResult(
        project_id=project_id,
        task_id=task_id,
        compact_dir=str(compact_dir),
        created_files=created,
        raw_files_preserved=raw_preserved,
        memory_promotion_count=sum(len(items) for items in promotions.values()),
        prune_executed=execute_prune,
    )


def task_compaction_result_to_dict(result: TaskCompactionResult) -> dict[str, Any]:
    return asdict(result)
