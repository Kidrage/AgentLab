"""Hash-gated, non-destructive import of legacy ``projects/*/runs`` state."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from .runtime import LedgerIntegrityError, TaskRuntime, TaskRuntimeError


PLAN_SCHEMA = "task-runtime-legacy-migration-plan/v2"


class MigrationPlanChanged(TaskRuntimeError):
    """The live legacy sources no longer match the approved preview."""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class LegacyRunMigrator:
    """Import legacy task identities once while leaving their files untouched."""

    def __init__(self, agentlab_root: Path, *, project: str) -> None:
        self.root = Path(agentlab_root).resolve(strict=False)
        self.runtime = TaskRuntime(self.root, project=project)
        self.project = self.runtime.project
        self.runs_root = self.root / "projects" / self.project / "runs"

    def plan(self) -> dict[str, Any]:
        """Return a deterministic preview; this method performs no writes."""

        sources: list[dict[str, Any]] = []
        if self.runs_root.is_dir():
            for run_dir in sorted(
                path
                for path in self.runs_root.iterdir()
                if path.is_dir() and not path.is_symlink()
            ):
                state_path = run_dir / "state.yml"
                if not state_path.is_file() or state_path.is_symlink():
                    continue
                raw = yaml.safe_load(state_path.read_text(encoding="utf-8")) or {}
                if not isinstance(raw, dict):
                    raise LedgerIntegrityError(f"legacy state is not a mapping: {state_path}")
                if raw.get("project") and str(raw["project"]) != self.project:
                    raise LedgerIntegrityError(
                        f"legacy state project mismatch: {state_path}"
                    )
                task_id = str(raw.get("task_id") or run_dir.name).strip()
                self.runtime._task_dir(task_id)
                request_path = run_dir / "user_request.md"
                if request_path.is_symlink():
                    raise LedgerIntegrityError(
                        f"legacy request must not be a symlink: {request_path}"
                    )
                user_goal = (
                    request_path.read_text(encoding="utf-8").strip()
                    if request_path.is_file() and not request_path.is_symlink()
                    else str(raw.get("last_event") or f"Imported legacy task {task_id}")
                )
                if not user_goal:
                    user_goal = str(
                        raw.get("last_event") or f"Imported legacy task {task_id}"
                    )
                source = {
                    "task_id": task_id,
                    "title": f"Imported legacy task {task_id}",
                    "user_goal": user_goal,
                    "legacy_status": str(raw.get("status") or "created").lower(),
                    "state_path": state_path.relative_to(self.root).as_posix(),
                    "state_sha256": _sha256(state_path),
                    "request_path": (
                        request_path.relative_to(self.root).as_posix()
                        if request_path.is_file()
                        else None
                    ),
                    "request_sha256": _sha256(request_path) if request_path.is_file() else None,
                    "target": (
                        Path("projects")
                        / self.project
                        / "runtime"
                        / "tasks"
                        / task_id
                    ).as_posix(),
                }
                sources.append(source)
        body = {
            "schema_version": PLAN_SCHEMA,
            "project": self.project,
            "mode": "legacy-dual-read-v2-single-write",
            "source_count": len(sources),
            "sources": sources,
        }
        return {
            **body,
            "plan_hash": hashlib.sha256(_canonical_json(body).encode("utf-8")).hexdigest(),
        }

    def apply(self, *, expected_plan_hash: str) -> dict[str, Any]:
        """Apply exactly the approved preview and never mutate legacy sources."""

        plan = self.plan()
        if plan["plan_hash"] != expected_plan_hash:
            raise MigrationPlanChanged(
                "legacy migration preview changed; generate and approve a new plan"
            )
        imported: list[str] = []
        already_imported: list[str] = []
        for source in plan["sources"]:
            task_id = source["task_id"]
            task_dir = self.runtime.tasks_root / task_id
            legacy_source = {
                "state_path": source["state_path"],
                "state_sha256": source["state_sha256"],
                "request_path": source["request_path"],
                "request_sha256": source["request_sha256"],
                "legacy_status": source["legacy_status"],
            }
            if task_dir.exists():
                projection = self.runtime.load_task(task_id)
                if projection["task"].get("legacy_source") != legacy_source:
                    raise MigrationPlanChanged(
                        f"v2 target {task_id!r} exists but does not match this legacy source"
                    )
                already_imported.append(task_id)
                continue
            self.runtime.create_task(
                task_id=task_id,
                title=source["title"],
                user_goal=source["user_goal"],
                legacy_source=legacy_source,
                allow_duplicate_goal=True,
                independent_boundary_reason=(
                    "legacy migration preserves an existing independent Task identity"
                ),
                idempotency_key=f"legacy-{source['state_sha256'][:24]}",
            )
            self._restore_terminal_status(task_id, source["legacy_status"])
            imported.append(task_id)
        self.runtime.rebuild_project()
        return {
            "project": self.project,
            "plan_hash": plan["plan_hash"],
            "imported": imported,
            "already_imported": already_imported,
            "legacy_sources_modified": False,
        }

    def _restore_terminal_status(self, task_id: str, legacy_status: str) -> None:
        mapping = {
            "completed": "completed",
            "failed": "failed",
            "cancelled": "cancelled",
            "paused": "paused",
            "blocked": "blocked",
            "running": "running",
            "active": "running",
            "in_progress": "running",
            "ready": "ready",
            "planned": "ready",
            "complete": "completed",
            "failed_recoverable": "failed",
            "failed_blocked": "blocked",
        }
        target = mapping.get(legacy_status, "created")
        if target == "created":
            return
        if target == "cancelled":
            self.runtime.transition_task(
                task_id, status="cancelled", idempotency_key="legacy-status-cancelled"
            )
            return
        self.runtime.transition_task(
            task_id, status="ready", idempotency_key="legacy-status-ready"
        )
        if target in {"ready", "paused", "blocked"}:
            if target != "ready":
                self.runtime.transition_task(
                    task_id, status=target, idempotency_key=f"legacy-status-{target}"
                )
            return
        self.runtime.transition_task(
            task_id, status="running", idempotency_key="legacy-status-running"
        )
        if target != "running":
            self.runtime.transition_task(
                task_id, status=target, idempotency_key=f"legacy-status-{target}"
            )
