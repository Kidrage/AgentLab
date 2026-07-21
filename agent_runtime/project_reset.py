"""Hash-bound, fail-closed project reset planning and execution."""

from __future__ import annotations

from pathlib import Path
from pathlib import PurePosixPath
from datetime import datetime, timezone
import hashlib
import json
import os
import re
from typing import Iterable, Mapping, Any

import yaml

from agent_runtime.atomic_io import atomic_write_text, atomic_write_yaml


class ProjectResetError(RuntimeError):
    """Base error for a reset that cannot proceed safely."""


class ActiveProjectResetError(ProjectResetError):
    """Raised when an active lock or background job protects the project."""


class ProjectResetApplyError(ProjectResetError):
    """Raised with the metadata-only receipt for a partially applied reset."""

    def __init__(self, message: str, result: dict[str, Any]) -> None:
        self.result = result
        super().__init__(message)


_TERMINAL_JOB_STATES = {"blocked", "cancelled", "completed", "failed", "stopped"}
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_GLOB_OR_SHELL_CHARS = frozenset("*?[]{};|&")
_EMPTY_RUNTIME_ROOTS = frozenset({"archive", "background_jobs", "candidates", "runs"})
_STATE_FILES = (
    "PROJECT_HANDOFF.md",
    "project_artifact_index.yml",
    "project_brain/project_fact_snapshot.yml",
    "project_brain/project_state_contract.yml",
    "project_brain/revision_log.jsonl",
    "task_index.yml",
)

CROWN_RESET_TARGETS = (
    ".agentlab",
    "PROJECT_HANDOFF.md",
    "agent_docs/00_CONTEXT_PACK.md",
    "agent_docs/01_REPO_MAP.md",
    "agent_docs/02_TASK_LEDGER.yml",
    "agent_docs/04_INTERFACE_REGISTRY.md",
    "agent_docs/07_DEVELOPMENT_LOG.md",
    "agent_docs/08_CODEX_DIALOGUE_LOG.md",
    "agent_docs/09_COST_LEDGER.yml",
    "agent_docs/HandOff.md",
    "archive",
    "background_jobs",
    "candidates",
    "production",
    "project_artifact_index.yml",
    "project_brain",
    "prompt_templates",
    "runs",
    "skill_requests",
    "skills",
    "task_index.yml",
)


def _validated_targets(project_root: Path, targets: Iterable[str]) -> tuple[str, ...]:
    ordered: list[str] = []
    for raw in targets:
        target = str(raw).strip()
        pure = PurePosixPath(target)
        if (
            not target
            or target in {".", ".."}
            or pure.is_absolute()
            or any(part in {"", ".", ".."} for part in pure.parts)
            or any(char in target for char in _GLOB_OR_SHELL_CHARS)
        ):
            raise ProjectResetError(f"unsafe reset target: {raw!r}")
        candidate = (project_root / Path(*pure.parts)).resolve(strict=False)
        if candidate == project_root or project_root not in candidate.parents:
            raise ProjectResetError(f"unsafe reset target: {raw!r}")
        normalized = pure.as_posix()
        if normalized in ordered:
            raise ProjectResetError(f"unsafe reset target: duplicate {normalized!r}")
        if any(
            normalized.startswith(f"{existing}/")
            or existing.startswith(f"{normalized}/")
            for existing in ordered
        ):
            raise ProjectResetError(f"unsafe reset target overlap: {normalized!r}")
        ordered.append(normalized)
    if not ordered:
        raise ProjectResetError("unsafe reset target: no targets supplied")
    return tuple(sorted(ordered))


def _active_collaboration_locks(root: Path, project: str) -> tuple[Path, ...]:
    locks_dir = root / ".agents" / "locks"
    if not locks_dir.is_dir():
        return ()
    project_marker = f"projects/{project}/"
    active: list[Path] = []
    for path in sorted(locks_dir.glob("*.lock")):
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            active.append(path)
            continue
        if not isinstance(raw, dict) or str(raw.get("status") or "in_progress") == "in_progress":
            text = path.read_text(encoding="utf-8", errors="replace")
            if project_marker in text:
                active.append(path)
    return tuple(active)


def _active_background_jobs(project_root: Path) -> tuple[Path, ...]:
    jobs_dir = project_root / "background_jobs"
    if not jobs_dir.is_dir():
        return ()
    active: list[Path] = []
    for state_path in sorted(jobs_dir.glob("*/job_state.yml")):
        try:
            state = yaml.safe_load(state_path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            active.append(state_path.parent)
            continue
        status = str(state.get("status") or "unknown").strip().lower()
        if status not in _TERMINAL_JOB_STATES or state.get("active_attempt"):
            active.append(state_path.parent)
    return tuple(active)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inventory_entry(project_root: Path, path: Path) -> dict:
    relative = path.relative_to(project_root).as_posix()
    if path.is_symlink():
        kind = "symlink"
        sha256 = hashlib.sha256(os.readlink(path).encode("utf-8")).hexdigest()
    elif path.is_file():
        kind = "file"
        sha256 = _sha256_file(path)
    elif path.is_dir():
        kind = "directory"
        sha256 = None
    elif not path.exists():
        return {
            "path": relative,
            "kind": "missing",
            "sha256": None,
            "status": "absent",
            "deletion_result": "not_applicable",
        }
    else:
        raise ProjectResetError(f"unsupported reset target kind: {relative}")
    return {
        "path": relative,
        "kind": kind,
        "sha256": sha256,
        "status": "present",
        "deletion_result": "pending",
    }


def _inventory(project_root: Path, targets: tuple[str, ...]) -> list[dict]:
    entries: dict[str, dict] = {}
    pending = [project_root / Path(*PurePosixPath(target).parts) for target in targets]
    while pending:
        path = pending.pop()
        entry = _inventory_entry(project_root, path)
        entries[entry["path"]] = entry
        if entry["kind"] == "directory":
            try:
                children = sorted(path.iterdir(), key=lambda item: item.name, reverse=True)
            except OSError as exc:
                raise ProjectResetError(f"cannot inventory reset target {entry['path']}: {exc}") from exc
            pending.extend(children)
    return [entries[path] for path in sorted(entries)]


def _target_covers(target: str, relative: str) -> bool:
    return relative == target or relative.startswith(f"{target}/")


def _reinitialize_declared_state(
    project_root: Path,
    *,
    project: str,
    plan_id: str,
    targets: tuple[str, ...],
) -> None:
    selected = {
        relative
        for relative in _STATE_FILES
        if any(_target_covers(target, relative) for target in targets)
    }
    yaml_documents = {
        "task_index.yml": {"schema_version": 1, "project": project, "tasks": []},
        "project_artifact_index.yml": {
            "schema_version": 1,
            "project": project,
            "artifacts": [],
            "current": {},
        },
        "project_brain/project_fact_snapshot.yml": {
            "schema_version": 1,
            "project": project,
            "reset_plan_id": plan_id,
            "facts": [],
            "source_hashes": {},
            "conflicts": [],
        },
        "project_brain/project_state_contract.yml": {
            "schema_version": 1,
            "project": project,
            "reset_plan_id": plan_id,
            "candidate_only": True,
            "production_promotion_allowed": False,
            "formal_fact_roots": ["production", "project_brain"],
            "writer_forbidden_roots": [
                "acceptance_runs",
                "agent_docs",
                "archive",
                "background_jobs",
                "candidates",
                "runs",
            ],
        },
    }
    for relative, document in yaml_documents.items():
        if relative in selected:
            atomic_write_yaml(project_root / relative, document)
    if "project_brain/revision_log.jsonl" in selected:
        atomic_write_text(project_root / "project_brain/revision_log.jsonl", "")
    if "PROJECT_HANDOFF.md" in selected:
        atomic_write_text(
            project_root / "PROJECT_HANDOFF.md",
            (
                "# Crown of Ash Project Handoff\n\n"
                f"- Project: {project}\n"
                f"- Reset plan: {plan_id}\n"
                "- Status: reset applied; canonical blueprint rebuild pending\n"
                "- Candidate prose promotion: prohibited pending user review\n"
            ),
        )


def plan_project_reset(
    agentlab_root: Path,
    *,
    project: str,
    targets: Iterable[str],
    plan_id: str | None = None,
    now: str | None = None,
) -> dict:
    """Plan an exact project reset without mutating project state."""
    root = Path(agentlab_root).resolve()
    if not _SAFE_ID.fullmatch(project):
        raise ProjectResetError(f"unsafe project id: {project!r}")
    project_root = root / "projects" / project
    if not project_root.is_dir():
        raise ProjectResetError(f"project root does not exist: {project_root}")
    active = _active_collaboration_locks(root, project)
    if active:
        names = ", ".join(path.name for path in active)
        raise ActiveProjectResetError(f"active project reset lock(s): {names}")
    active_jobs = _active_background_jobs(project_root)
    if active_jobs:
        names = ", ".join(path.name for path in active_jobs)
        raise ActiveProjectResetError(f"active project background job(s): {names}")
    validated_targets = _validated_targets(project_root, targets)
    resolved_plan_id = plan_id or f"reset-{project}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    if not _SAFE_ID.fullmatch(resolved_plan_id):
        raise ProjectResetError(f"unsafe reset plan id: {resolved_plan_id!r}")
    entries = _inventory(project_root, validated_targets)
    canonical = json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "schema_version": 1,
        "plan_id": resolved_plan_id,
        "project": project,
        "created_at": now or datetime.now(timezone.utc).isoformat(),
        "status": "preview",
        "targets": list(validated_targets),
        "entry_count": len(entries),
        "inventory_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "entries": entries,
    }


def _inventory_digest(entries: list[dict]) -> str:
    canonical = json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def apply_project_reset(
    agentlab_root: Path,
    *,
    plan: Mapping[str, Any],
    confirm_project: str,
    now: str | None = None,
) -> dict:
    """Apply a previously previewed reset only when every byte is unchanged."""
    root = Path(agentlab_root).resolve()
    project = str(plan.get("project") or "")
    if confirm_project != project or not _SAFE_ID.fullmatch(project):
        raise ProjectResetError("explicit project confirmation does not match reset plan")
    if int(plan.get("schema_version") or 0) != 1 or plan.get("status") != "preview":
        raise ProjectResetError("invalid reset plan schema or status")
    project_root = root / "projects" / project
    targets = _validated_targets(project_root, plan.get("targets") or ())
    expected_entries = plan.get("entries")
    if not isinstance(expected_entries, list) or any(
        not isinstance(item, dict) for item in expected_entries
    ):
        raise ProjectResetError("invalid reset plan entries")
    if _inventory_digest(expected_entries) != str(plan.get("inventory_sha256") or ""):
        raise ProjectResetError("reset plan inventory digest mismatch")
    active = _active_collaboration_locks(root, project)
    active_jobs = _active_background_jobs(project_root)
    if active or active_jobs:
        names = ", ".join(path.name for path in (*active, *active_jobs))
        raise ActiveProjectResetError(f"active project reset protection: {names}")
    current_entries = _inventory(project_root, targets)
    if current_entries != expected_entries:
        raise ProjectResetError("reset inventory changed after preview")
    result = json.loads(json.dumps(dict(plan), ensure_ascii=False))
    result_entries = {item["path"]: item for item in result["entries"]}
    ordered = sorted(
        expected_entries,
        key=lambda item: (len(PurePosixPath(item["path"]).parts), item["path"]),
        reverse=True,
    )
    for item in ordered:
        relative = str(item["path"])
        output = result_entries[relative]
        if item["kind"] == "missing":
            continue
        path = project_root / Path(*PurePosixPath(relative).parts)
        try:
            if item["kind"] == "directory":
                path.rmdir()
            else:
                path.unlink()
        except OSError as exc:
            output["deletion_result"] = f"failed:{type(exc).__name__}"
            result["status"] = "failed_partial"
            result["applied_at"] = now or datetime.now(timezone.utc).isoformat()
            raise ProjectResetApplyError(
                f"reset deletion failed at {relative}: {exc}", result
            ) from exc
        output["status"] = "deleted"
        output["deletion_result"] = "deleted"
    for target in targets:
        if target in _EMPTY_RUNTIME_ROOTS:
            (project_root / target).mkdir(parents=True, exist_ok=False)
    _reinitialize_declared_state(
        project_root,
        project=project,
        plan_id=str(plan.get("plan_id") or ""),
        targets=targets,
    )
    result["status"] = "applied"
    result["applied_at"] = now or datetime.now(timezone.utc).isoformat()
    return result
