"""Task compaction, contribution, and project-status primitives."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml


RAW_SKIP_DIRS = {"task_compact", "__pycache__"}


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _iter_task_files(run_dir: Path) -> list[Path]:
    files: list[Path] = []
    if not run_dir.exists():
        return files
    for path in sorted(run_dir.rglob("*")):
        if not path.is_file():
            continue
        if any(part in RAW_SKIP_DIRS for part in path.relative_to(run_dir).parts):
            continue
        files.append(path)
    return files


def compact_task(agentlab_root: Path, project: str, task_id: str) -> dict[str, Any]:
    run_dir = agentlab_root / "projects" / project / "runs" / task_id
    if not run_dir.exists():
        raise FileNotFoundError(f"task run does not exist: {run_dir}")
    compact_dir = run_dir / "task_compact"
    compact_dir.mkdir(parents=True, exist_ok=True)

    files = _iter_task_files(run_dir)
    artifact_entries = []
    for path in files:
        rel = path.relative_to(run_dir).as_posix()
        artifact_entries.append(
            {
                "path": rel,
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
                "default_read": rel in {"user_request.md", "workflow_plan.yml", "state.yml", "task_card.yml"},
            }
        )

    state = _load_yaml(run_dir / "state.yml") or _load_yaml(run_dir / "state.json")
    cost = _load_yaml(run_dir / "cost_ledger.yml")
    contributions = build_agent_contribution_summary(run_dir)

    summary = [
        "# Task Compact Summary",
        "",
        f"- project: {project}",
        f"- task_id: {task_id}",
        f"- status: {state.get('status', 'unknown')}",
        f"- artifacts_indexed: {len(artifact_entries)}",
        "",
        "## Default Read Rule",
        "",
        "Read this compact folder first. Do not reread raw logs or long reports unless an unresolved item requires trace evidence.",
        "",
    ]
    (compact_dir / "task_summary.md").write_text("\n".join(summary), encoding="utf-8")
    _write_yaml(compact_dir / "final_verdict.yml", {"project": project, "task_id": task_id, "status": state.get("status", "unknown"), "source": "state.yml"})
    _write_yaml(compact_dir / "artifact_index.yml", {"artifacts": artifact_entries})
    _write_yaml(compact_dir / "decision_delta.yml", {"decisions": []})
    _write_yaml(compact_dir / "memory_promotions.yml", {"promotions": []})
    _write_yaml(compact_dir / "unresolved_items.yml", {"items": []})
    _write_yaml(compact_dir / "reusable_patterns.yml", {"patterns": []})
    _write_yaml(compact_dir / "cost_summary.yml", {"entries": cost.get("entries", []), "source": "cost_ledger.yml"})
    _write_yaml(compact_dir / "agent_contribution_summary.yml", contributions)
    return {"compact_dir": str(compact_dir), "artifacts_indexed": len(artifact_entries)}


def append_agent_contribution(
    agentlab_root: Path,
    project: str,
    task_id: str,
    contribution: dict[str, Any],
) -> dict[str, Any]:
    run_dir = agentlab_root / "projects" / project / "runs" / task_id
    run_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = run_dir / "agent_contributions.yml"
    ledger = _load_yaml(ledger_path)
    agents = list(ledger.get("agents", []))
    agents.append(contribution)
    payload = {"project_id": project, "task_id": task_id, "agents": agents}
    _write_yaml(ledger_path, payload)
    return {"ledger": str(ledger_path), "agent_count": len(agents)}


def build_agent_contribution_summary(run_dir: Path) -> dict[str, Any]:
    ledger = _load_yaml(run_dir / "agent_contributions.yml")
    agents = list(ledger.get("agents", []))
    by_role: dict[str, int] = {}
    accepted = 0
    rejected = 0
    for item in agents:
        role = str(item.get("role") or "unknown")
        by_role[role] = by_role.get(role, 0) + 1
        if item.get("accepted_by_supervisor") is True:
            accepted += 1
        if item.get("accepted_by_supervisor") is False:
            rejected += 1
    return {
        "project_id": ledger.get("project_id"),
        "task_id": ledger.get("task_id"),
        "agent_count": len(agents),
        "accepted_count": accepted,
        "rejected_count": rejected,
        "by_role": by_role,
        "agents": agents,
    }


def project_status(agentlab_root: Path, project: str) -> dict[str, Any]:
    project_root = agentlab_root / "projects" / project
    manifest = _load_yaml(project_root / "project_manifest.yml")
    runs_root = project_root / "runs"
    tasks = []
    active = closed = compacted = archived = 0
    if runs_root.exists():
        for run_dir in sorted(item for item in runs_root.iterdir() if item.is_dir()):
            state = _load_yaml(run_dir / "state.yml") or _load_yaml(run_dir / "state.json")
            compact_exists = (run_dir / "task_compact" / "task_summary.md").exists()
            status = str(state.get("status") or "unknown")
            if status in {"completed", "failed", "blocked"}:
                closed += 1
            else:
                active += 1
            if compact_exists:
                compacted += 1
            if status == "archived":
                archived += 1
            tasks.append({"task_id": run_dir.name, "status": status, "compacted": compact_exists})
    return {
        "project_id": project,
        "project_root": str(project_root),
        "manifest": manifest,
        "counts": {
            "active_tasks": active,
            "closed_tasks": closed,
            "compacted_tasks": compacted,
            "archived_tasks": archived,
        },
        "tasks": tasks,
        "unresolved_questions": [],
        "known_risks": [],
        "next_actions": ["compact closed tasks before future agents read raw run folders"],
    }
