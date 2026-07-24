"""Hash-gated, non-destructive import of legacy ``projects/*/runs`` state."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

import yaml

from .runtime import LedgerIntegrityError, TaskRuntime, TaskRuntimeError


PLAN_SCHEMA = "task-runtime-legacy-migration-plan/v3"


class MigrationPlanChanged(TaskRuntimeError):
    """The live legacy sources no longer match the approved preview."""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _has_symlink_component(path: Path, root: Path) -> bool:
    """Return true when a lexical path escapes *root* or crosses a symlink."""

    lexical_root = Path(os.path.abspath(root))
    candidate = Path(os.path.abspath(path))
    try:
        relative = candidate.relative_to(lexical_root)
    except ValueError:
        return True
    current = lexical_root
    if current.is_symlink():
        return True
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            return True
    return False


class LegacyRunMigrator:
    """Import legacy task identities once while leaving their files untouched."""

    def __init__(self, agentlab_root: Path, *, project: str) -> None:
        self.root = Path(agentlab_root).resolve(strict=False)
        self.runtime = TaskRuntime(self.root, project=project)
        self.project = self.runtime.project
        self.runs_root = self.root / "projects" / self.project / "runs"
        self.provenance_root = (
            self.root
            / "projects"
            / self.project
            / "runtime"
            / "provenance"
            / "legacy"
        )

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
                    "snapshot_state_path": (
                        Path("projects")
                        / self.project
                        / "runtime"
                        / "provenance"
                        / "legacy"
                        / task_id
                        / "state.yml"
                    ).as_posix(),
                    "snapshot_request_path": (
                        (
                            Path("projects")
                            / self.project
                            / "runtime"
                            / "provenance"
                            / "legacy"
                            / task_id
                            / "user_request.md"
                        ).as_posix()
                        if request_path.is_file()
                        else None
                    ),
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
            self._materialize_provenance_snapshot(source)
            legacy_source = {
                "state_path": source["snapshot_state_path"],
                "state_sha256": source["state_sha256"],
                "request_path": source["snapshot_request_path"],
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

    def _materialize_provenance_snapshot(self, source: dict[str, Any]) -> None:
        """Copy immutable migration inputs into Runtime v2-owned provenance."""

        bindings = (
            (
                source["state_path"],
                source["snapshot_state_path"],
                source["state_sha256"],
            ),
            (
                source.get("request_path"),
                source.get("snapshot_request_path"),
                source.get("request_sha256"),
            ),
        )
        for source_value, snapshot_value, expected_sha256 in bindings:
            if not source_value or not snapshot_value:
                continue
            source_path = self.root / str(source_value)
            snapshot_path = self.root / str(snapshot_value)
            if _has_symlink_component(source_path, self.root):
                raise MigrationPlanChanged(
                    f"legacy migration source has a symlink component: {source_path}"
                )
            if not source_path.is_file() or source_path.is_symlink():
                raise MigrationPlanChanged(
                    f"legacy migration source is missing or unsafe: {source_path}"
                )
            if _sha256(source_path) != expected_sha256:
                raise MigrationPlanChanged(
                    f"legacy migration source hash changed: {source_path}"
                )
            try:
                snapshot_path.relative_to(self.provenance_root)
            except ValueError as exc:
                raise MigrationPlanChanged(
                    f"legacy provenance target is outside provenance root: {snapshot_path}"
                ) from exc
            if _has_symlink_component(snapshot_path, self.root):
                raise MigrationPlanChanged(
                    f"legacy provenance target has a symlink component: {snapshot_path}"
                )
            snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            if _has_symlink_component(snapshot_path, self.root):
                raise MigrationPlanChanged(
                    f"legacy provenance target has a symlink component: {snapshot_path}"
                )
            if snapshot_path.exists():
                if not snapshot_path.is_file() or snapshot_path.is_symlink():
                    raise MigrationPlanChanged(
                        f"legacy provenance target is unsafe: {snapshot_path}"
                    )
                if _sha256(snapshot_path) != expected_sha256:
                    raise MigrationPlanChanged(
                        f"legacy provenance snapshot hash mismatch: {snapshot_path}"
                    )
                continue
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            flags |= getattr(os, "O_NOFOLLOW", 0)
            try:
                descriptor = os.open(snapshot_path, flags, 0o600)
            except OSError as exc:
                raise MigrationPlanChanged(
                    f"legacy provenance target cannot be created safely: {snapshot_path}"
                ) from exc
            try:
                source_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                source_descriptor = os.open(source_path, source_flags)
                with os.fdopen(source_descriptor, "rb") as source_handle, os.fdopen(
                    descriptor, "wb"
                ) as snapshot_handle:
                    descriptor = -1
                    shutil.copyfileobj(source_handle, snapshot_handle)
            except BaseException:
                if descriptor >= 0:
                    os.close(descriptor)
                if snapshot_path.is_file() and not snapshot_path.is_symlink():
                    snapshot_path.unlink()
                raise
            if _sha256(snapshot_path) != expected_sha256:
                raise MigrationPlanChanged(
                    f"legacy provenance snapshot copy failed: {snapshot_path}"
                )

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
