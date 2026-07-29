"""Governed rolling planning windows for long-running narrative projects."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
import hashlib

import yaml

from atomic_io import atomic_write_yaml

SCHEMA_VERSION = "narrative-planning-window/v1"
CURRENT_PATH = Path("production/narrative_planning_window.yml")
HISTORY_ROOT = Path("project_brain/planning_windows/history")


class PlanningWindowError(ValueError):
    """Raised when a planning-window contract or lifecycle transition is invalid."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_mapping(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise PlanningWindowError(f"cannot read {label}: {path}") from exc
    if not isinstance(value, dict):
        raise PlanningWindowError(f"{label} must be a mapping: {path}")
    return value


def _project_root(agentlab_root: Path, project: str) -> Path:
    root = Path(agentlab_root).resolve()
    project_root = (root / "projects" / project).resolve()
    try:
        project_root.relative_to(root / "projects")
    except ValueError as exc:
        raise PlanningWindowError("project path escapes projects/") from exc
    return project_root


def _project_file(project_root: Path, relative: object) -> Path:
    raw = Path(str(relative or ""))
    if raw.is_absolute():
        raise PlanningWindowError("artifact path escapes project root")
    path = (project_root / raw).resolve()
    try:
        path.relative_to(project_root)
    except ValueError as exc:
        raise PlanningWindowError("artifact path escapes project root") from exc
    return path


def _card_entry(project_root: Path, chapter: int) -> dict[str, Any]:
    relative = Path("production/chapter_cards") / f"ch{chapter:03d}.yml"
    path = project_root / relative
    value = _read_mapping(path, label=f"chapter card {chapter}")
    if value.get("chapter") != chapter:
        raise PlanningWindowError(f"chapter card identity mismatch: {relative}")
    return {
        "chapter": chapter,
        "contract_path": relative.as_posix(),
        "contract_sha256": _sha256(path),
    }


def _source_range(authority: Mapping[str, Any]) -> tuple[int, int]:
    scope = authority.get("scope")
    chapter_range = (
        scope.get("detailed_chapter_contract_range")
        if isinstance(scope, Mapping)
        else None
    )
    if (
        not isinstance(chapter_range, list)
        or len(chapter_range) != 2
        or any(
            isinstance(item, bool) or not isinstance(item, int) or item < 1
            for item in chapter_range
        )
        or chapter_range[0] > chapter_range[1]
    ):
        raise PlanningWindowError("blueprint has no valid detailed chapter range")
    return chapter_range[0], chapter_range[1]


def propose_planning_window(
    agentlab_root: Path,
    *,
    project: str,
    locked_size: int = 10,
) -> dict[str, Any]:
    """Build a hash-bound migration proposal without changing project state."""

    if not 8 <= locked_size <= 10:
        raise PlanningWindowError("locked_size must be between 8 and 10")
    project_root = _project_root(agentlab_root, project)
    authority_path = project_root / "production" / "blueprint_authority.yml"
    authority = _read_mapping(authority_path, label="blueprint authority")
    chapter_start, chapter_end = _source_range(authority)
    locked_end = min(chapter_start + locked_size - 1, chapter_end)
    locked = [
        _card_entry(project_root, chapter)
        for chapter in range(chapter_start, locked_end + 1)
    ]
    horizon = [
        _card_entry(project_root, chapter)
        for chapter in range(locked_end + 1, chapter_end + 1)
    ]
    source_hash = _sha256(authority_path)
    receipt_path = project_root / "project_brain" / "blueprint_validation_receipt.yml"
    superseded_seal = (
        {
            "path": receipt_path.relative_to(project_root).as_posix(),
            "sha256": _sha256(receipt_path),
            "disposition": "superseded_evidence",
        }
        if receipt_path.is_file()
        else None
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "project": project,
        "window_id": (
            f"window-{chapter_start:04d}-{chapter_end:04d}-{source_hash[:12]}"
        ),
        "revision": 1,
        "status": "proposed",
        "created_at": _utc_now(),
        "source_blueprint": {
            "path": authority_path.relative_to(project_root).as_posix(),
            "sha256": source_hash,
            "chapter_range": [chapter_start, chapter_end],
        },
        "superseded_blueprint_seal": superseded_seal,
        "locked_queue": locked,
        "adjustable_horizon": horizon,
        "completed_chapters": [],
        "horizon_replan_required": len(horizon) < 15,
    }


def _queue_chapters(value: object, *, label: str) -> list[int]:
    if not isinstance(value, list):
        raise PlanningWindowError(f"{label} must be a list")
    chapters: list[int] = []
    for item in value:
        chapter = item.get("chapter") if isinstance(item, Mapping) else None
        if isinstance(chapter, bool) or not isinstance(chapter, int) or chapter < 1:
            raise PlanningWindowError(f"{label} contains an invalid chapter")
        chapters.append(chapter)
    return chapters


def _validate_proposal(project_root: Path, proposal: Mapping[str, Any]) -> None:
    if proposal.get("schema_version") != SCHEMA_VERSION:
        raise PlanningWindowError("unsupported planning-window schema")
    if proposal.get("project") != project_root.name:
        raise PlanningWindowError("planning-window project mismatch")
    if proposal.get("status") != "proposed":
        raise PlanningWindowError("only proposed planning windows may be sealed")
    locked = _queue_chapters(proposal.get("locked_queue"), label="locked_queue")
    horizon = _queue_chapters(
        proposal.get("adjustable_horizon"),
        label="adjustable_horizon",
    )
    if not 8 <= len(locked) <= 10:
        raise PlanningWindowError("locked_queue must contain 8 to 10 chapters")
    combined = locked + horizon
    if combined != list(range(combined[0], combined[-1] + 1)):
        raise PlanningWindowError("planning-window chapters must be contiguous and unique")
    source = proposal.get("source_blueprint")
    if not isinstance(source, Mapping):
        raise PlanningWindowError("source_blueprint is required")
    source_path = _project_file(project_root, source.get("path"))
    if not source_path.is_file() or _sha256(source_path) != source.get("sha256"):
        raise PlanningWindowError("source_blueprint hash mismatch")
    for item in list(proposal.get("locked_queue") or []) + list(
        proposal.get("adjustable_horizon") or []
    ):
        relative = str(item.get("contract_path") or "")
        path = _project_file(project_root, relative)
        if (
            not path.is_file()
            or _sha256(path) != item.get("contract_sha256")
        ):
            raise PlanningWindowError(f"chapter contract hash mismatch: {relative}")


def _current(project_root: Path) -> dict[str, Any] | None:
    path = project_root / CURRENT_PATH
    return _read_mapping(path, label="current planning window") if path.is_file() else None


def _seal_payload(window: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: window.get(key)
        for key in (
            "schema_version",
            "project",
            "window_id",
            "source_blueprint",
            "superseded_blueprint_seal",
            "locked_queue",
            "adjustable_horizon",
        )
    }


def _mapping_sha256(value: Mapping[str, Any]) -> str:
    body = yaml.safe_dump(
        dict(value),
        sort_keys=True,
        allow_unicode=True,
    ).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def _archive_current(
    project_root: Path,
    current: Mapping[str, Any],
    *,
    superseded_by: str,
    reason: str,
) -> None:
    archived = {
        **dict(current),
        "status": "superseded",
        "superseded_at": _utc_now(),
        "superseded_by": superseded_by,
        "supersede_reason": reason,
    }
    history = (
        project_root
        / HISTORY_ROOT
        / (
            f"{current.get('window_id')}-r"
            f"{int(current.get('revision') or 0):04d}.yml"
        )
    )
    if history.exists():
        raise PlanningWindowError(f"history revision already exists: {history.name}")
    atomic_write_yaml(history, archived)


def _register_current_artifact(project_root: Path) -> None:
    index_path = project_root / "project_artifact_index.yml"
    if index_path.is_file():
        index = _read_mapping(index_path, label="project artifact index")
    else:
        index = {
            "schema_version": 1,
            "project": project_root.name,
            "artifacts": [],
            "current": {},
        }
    artifact_id = f"{project_root.name.lower()}_narrative_planning_window"
    entries = [
        item
        for item in index.get("artifacts") or []
        if isinstance(item, dict) and item.get("artifact_id") != artifact_id
    ]
    current_path = project_root / CURRENT_PATH
    entries.append(
        {
            "artifact_id": artifact_id,
            "status": "current",
            "production_path": CURRENT_PATH.as_posix(),
            "production_sha256": _sha256(current_path),
            "evidence_only": False,
            "schema_version": SCHEMA_VERSION,
        }
    )
    current = dict(index.get("current") or {})
    current[artifact_id] = CURRENT_PATH.as_posix()
    atomic_write_yaml(
        index_path,
        {
            **index,
            "schema_version": index.get("schema_version") or 1,
            "project": project_root.name,
            "artifacts": entries,
            "current": current,
        },
    )


def validate_current_planning_window(
    agentlab_root: Path,
    *,
    project: str,
) -> dict[str, Any]:
    """Deterministically verify the sole current window and seal lifecycle."""

    project_root = _project_root(agentlab_root, project)
    issues: list[str] = []
    try:
        current = _current(project_root)
    except (OSError, PlanningWindowError, ValueError, yaml.YAMLError):
        current = None
    if current is None:
        return {
            "schema_version": "narrative-planning-window-validation/v1",
            "status": "blocked",
            "project": project,
            "current_count": 0,
            "double_current_count": 0,
            "legacy_seal_status": None,
            "issues": ["current_planning_window_missing"],
        }
    try:
        proposal_view = dict(current)
        proposal_view["status"] = "proposed"
        _validate_proposal(project_root, proposal_view)
    except (OSError, PlanningWindowError, ValueError) as exc:
        issues.append(f"current_window_contract_invalid:{exc}")
    if current.get("status") not in {"sealed", "active"}:
        issues.append("current_window_status_invalid")
    seal = current.get("seal")
    if (
        not isinstance(seal, Mapping)
        or seal.get("algorithm") != "sha256"
        or seal.get("proposal_sha256")
        != _mapping_sha256(_seal_payload(current))
    ):
        issues.append("current_window_seal_invalid")
    history_files = sorted((project_root / HISTORY_ROOT).glob("*.yml"))
    non_superseded_history = 0
    for path in history_files:
        try:
            historical = _read_mapping(path, label="planning window history")
        except (OSError, PlanningWindowError, ValueError, yaml.YAMLError):
            issues.append(f"history_unreadable:{path.name}")
            continue
        if historical.get("status") != "superseded":
            non_superseded_history += 1
            issues.append(f"history_not_superseded:{path.name}")
    current_count = 1 + non_superseded_history
    legacy = current.get("superseded_blueprint_seal")
    legacy_status = (
        "superseded"
        if isinstance(legacy, Mapping)
        and legacy.get("disposition") == "superseded_evidence"
        else None
    )
    if legacy_status != "superseded":
        issues.append("legacy_blueprint_seal_not_superseded")
    try:
        locked_chapters = _queue_chapters(
            current.get("locked_queue"),
            label="locked_queue",
        )
        horizon_chapters = _queue_chapters(
            current.get("adjustable_horizon"),
            label="adjustable_horizon",
        )
    except (PlanningWindowError, TypeError, ValueError) as exc:
        issues.append(f"planning_window_queue_invalid:{exc}")
        locked_chapters = []
        horizon_chapters = []
    return {
        "schema_version": "narrative-planning-window-validation/v1",
        "status": "pass" if not issues else "blocked",
        "project": project,
        "current_count": current_count,
        "double_current_count": max(0, current_count - 1),
        "legacy_seal_status": legacy_status,
        "locked_chapters": locked_chapters,
        "horizon_chapters": horizon_chapters,
        "issues": issues,
    }


def seal_planning_window(
    agentlab_root: Path,
    *,
    proposal: Mapping[str, Any],
    supersede_reason: str | None = None,
) -> dict[str, Any]:
    """Seal one proposal as the sole current window, archiving any prior version."""

    project = str(proposal.get("project") or "")
    project_root = _project_root(agentlab_root, project)
    _validate_proposal(project_root, proposal)
    current = _current(project_root)
    if current is not None:
        if (
            current.get("window_id") == proposal.get("window_id")
            and current.get("locked_queue") == proposal.get("locked_queue")
            and current.get("adjustable_horizon")
            == proposal.get("adjustable_horizon")
            and current.get("status") == "sealed"
        ):
            return current
        if (
            _queue_chapters(current.get("locked_queue"), label="locked_queue")
            != _queue_chapters(proposal.get("locked_queue"), label="locked_queue")
            and not str(supersede_reason or "").strip()
        ):
            raise PlanningWindowError(
                "supersede_reason is required when replacing a locked queue"
            )
    sealed = {
        **dict(proposal),
        "revision": int(current.get("revision") or 0) + 1 if current else 1,
        "status": "sealed",
        "sealed_at": _utc_now(),
    }
    sealed["seal"] = {
        "algorithm": "sha256",
        "proposal_sha256": _mapping_sha256(_seal_payload(sealed)),
    }
    if current is not None:
        _archive_current(
            project_root,
            current,
            superseded_by=str(sealed["window_id"]),
            reason=str(supersede_reason or "planning_window_resealed"),
        )
    atomic_write_yaml(project_root / CURRENT_PATH, sealed)
    _register_current_artifact(project_root)
    return sealed


def activate_planning_window(
    agentlab_root: Path,
    *,
    project: str,
) -> dict[str, Any]:
    """Activate the sole sealed current planning window."""

    project_root = _project_root(agentlab_root, project)
    current = _current(project_root)
    if current is None or current.get("status") != "sealed":
        raise PlanningWindowError("current planning window is not sealed")
    seal = current.get("seal")
    if (
        not isinstance(seal, Mapping)
        or seal.get("proposal_sha256")
        != _mapping_sha256(_seal_payload(current))
    ):
        raise PlanningWindowError("planning-window seal mismatch")
    _archive_current(
        project_root,
        current,
        superseded_by=str(current["window_id"]),
        reason="planning_window_activated",
    )
    active = {
        **current,
        "revision": int(current.get("revision") or 0) + 1,
        "status": "active",
        "activated_at": _utc_now(),
    }
    atomic_write_yaml(project_root / CURRENT_PATH, active)
    _register_current_artifact(project_root)
    return active


def complete_planning_window_chapter(
    agentlab_root: Path,
    *,
    project: str,
    chapter: int,
    horizon_chapter: int,
) -> dict[str, Any]:
    """Accept one locked chapter and extend the far horizon atomically."""

    project_root = _project_root(agentlab_root, project)
    current = _current(project_root)
    if current is None or current.get("status") != "active":
        raise PlanningWindowError("current planning window is not active")
    locked = list(current.get("locked_queue") or [])
    horizon = list(current.get("adjustable_horizon") or [])
    if not locked or locked[0].get("chapter") != chapter:
        expected = locked[0].get("chapter") if locked else None
        raise PlanningWindowError(
            f"chapter completion must follow locked queue order; expected {expected}"
        )
    completed = list(current.get("completed_chapters") or [])
    if chapter in completed:
        return current
    visible_chapters = _queue_chapters(locked, label="locked_queue") + (
        _queue_chapters(horizon, label="adjustable_horizon")
    )
    expected_horizon = max(visible_chapters) + 1
    if horizon_chapter != expected_horizon:
        raise PlanningWindowError(
            f"horizon chapter must extend the visible range with {expected_horizon}"
        )
    try:
        horizon_replacement = _card_entry(project_root, horizon_chapter)
    except PlanningWindowError as exc:
        raise PlanningWindowError(
            f"new far-horizon contract is unavailable: chapter {horizon_chapter}"
        ) from exc
    locked.pop(0)
    if horizon:
        locked.append(horizon.pop(0))
    horizon.append(horizon_replacement)
    _archive_current(
        project_root,
        current,
        superseded_by=str(current["window_id"]),
        reason=f"chapter_{chapter}_accepted",
    )
    rolled = {
        **current,
        "revision": int(current.get("revision") or 0) + 1,
        "status": "active",
        "locked_queue": locked,
        "adjustable_horizon": horizon,
        "completed_chapters": [*completed, chapter],
        "last_completed_at": _utc_now(),
        "horizon_replan_required": len(horizon) < 15,
    }
    atomic_write_yaml(project_root / CURRENT_PATH, rolled)
    _register_current_artifact(project_root)
    return rolled
