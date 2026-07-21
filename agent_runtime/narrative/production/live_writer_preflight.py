"""Provider-free replay for hash-bound live Writer sessions."""

from __future__ import annotations

import argparse
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
from statistics import median
from typing import Any

import yaml

from agent_runtime.atomic_io import atomic_write_text
from agent_runtime.narrative.production.live_writer import (
    LIVE_WRITER_REQUEST_NAME,
    prepare_live_writer_session,
)
from agent_runtime.narrative.production.writer_packet_measurement import (
    measure_frozen_writer_packets,
)
from agent_runtime.schemas import AgentRoute, WorkflowPlan


_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_PREFLIGHT_NOTE_PREFIX = "narrative_live_preflight_spec_sha256:"
_ACTIVATION_DIR_NAME = "_narrative_v2_preflight_batches"


class LiveWriterPlanActivationError(ValueError):
    """A v2 Writer plan is not bound to an active preflight batch."""


@dataclass(frozen=True)
class _RunSlot:
    run_dir: Path
    dir_fd: int
    lock_fd: int
    identity: tuple[int, int]


@dataclass(frozen=True)
class _PublishedFile:
    device: int
    inode: int


def preflight_live_writer_sessions(
    spec_path: Path,
    *,
    repository_root: Path,
) -> dict[str, Any]:
    """Build every declared live session without starting a provider."""
    root = repository_root.resolve()
    lexical_spec = spec_path if spec_path.is_absolute() else root / spec_path
    if _has_symlink_component(root, lexical_spec):
        raise ValueError("live_preflight_spec_outside_root_or_symlinked")
    spec_path = lexical_spec.resolve()
    try:
        spec_path.relative_to(root)
    except ValueError as exc:
        raise ValueError("live_preflight_spec_outside_root_or_symlinked") from exc
    spec = _load_mapping(spec_path)
    preflight_spec_sha256 = hashlib.sha256(spec_path.read_bytes()).hexdigest()
    if spec.get("candidate_only") is not True:
        raise ValueError("live_preflight_must_be_candidate_only")
    project = str(spec.get("project") or "").strip()
    task_prefix = str(spec.get("task_prefix") or "").strip()
    if not _IDENTIFIER_RE.fullmatch(project):
        raise ValueError("live_preflight_project_invalid")
    if not _IDENTIFIER_RE.fullmatch(task_prefix):
        raise ValueError("live_preflight_task_prefix_invalid")
    writer_manifest_path = _verified_ref(root, spec.get("writer_input_manifest"))
    writer_manifest = _load_mapping(writer_manifest_path)
    if writer_manifest.get("project") != project:
        raise ValueError("live_preflight_writer_manifest_project_mismatch")

    production_root = root / "projects" / project / "production"
    production_before = _tree_digest(production_root)
    preview_metrics = measure_frozen_writer_packets(
        writer_manifest_path,
        repository_root=root,
    )
    derived = {
        int(item["chapter_id"]): {
            "path": item["path"],
            "sha256": item["sha256"],
        }
        for item in preview_metrics.get("derived_sources") or []
    }
    chapter_inputs = {
        int(item["chapter_id"]): item
        for item in writer_manifest.get("chapter_inputs") or []
    }
    memory_refs = {
        int(item["chapter_id"]): item["snapshot"]
        for item in spec.get("literary_memories") or []
    }
    chapters = [int(item) for item in spec.get("chapters") or []]
    if len(chapters) != len(set(chapters)):
        raise ValueError("live_preflight_duplicate_chapter")
    if set(chapters) != set(derived) or set(chapters) != set(memory_refs):
        raise ValueError("live_preflight_chapter_set_mismatch")

    rows: list[dict[str, Any]] = []
    pending_plans: list[tuple[Path, str, Path, str, tuple[int, int]]] = []
    for chapter_id in chapters:
        memory = _verified_ref(root, memory_refs[chapter_id])
        chapter_input = chapter_inputs.get(chapter_id)
        if chapter_input is None:
            raise ValueError(f"live_preflight_chapter_input_missing:{chapter_id}")
        task_id = f"{task_prefix}_ch{chapter_id:03d}"
        if not _IDENTIFIER_RE.fullmatch(task_id):
            raise ValueError("live_preflight_task_id_invalid")
        run_dir = _safe_run_dir(root, project, task_id)
        run_stat = run_dir.stat(follow_symlinks=False)
        run_identity = (run_stat.st_dev, run_stat.st_ino)
        request = {
            "schema_version": 1,
            "job_kind": "narrative_generation",
            "run_mode": "generate_candidate",
            "project": project,
            "task_id": task_id,
            "chapter_id": chapter_id,
            "candidate_only": True,
            "production_modified": False,
            "external_context_approval_required": True,
            "writer_input_manifest": {
                "path": writer_manifest_path.relative_to(root).as_posix(),
                "sha256": hashlib.sha256(writer_manifest_path.read_bytes()).hexdigest(),
            },
            "creative_brief_source": derived[chapter_id],
            "canon_snapshot": writer_manifest["canon_snapshot"],
            "hard_state": chapter_input["hard_state"],
            "predecessor_prose": {
                **chapter_input["predecessor_prose"],
                "chapter_id": chapter_id - 1,
            },
            "literary_memory": {
                "path": memory.relative_to(root).as_posix(),
                "sha256": hashlib.sha256(memory.read_bytes()).hexdigest(),
            },
            "supplemental_context_sources": list(
                writer_manifest.get("shared_memory_sources") or []
            ),
            "writer_private_sources": list(
                writer_manifest.get("writer_private_sources") or []
            ),
        }
        request_path = run_dir / LIVE_WRITER_REQUEST_NAME
        plan = WorkflowPlan(
            project=project,
            task_id=task_id,
            agentlab_root=str(root),
            project_root=str(root / "projects" / project),
            repo_path=str(root / "projects" / project / "repo"),
            run_dir=str(run_dir),
            user_request_path=str(request_path),
            included_agents={"Writer": {"required_outputs": ["fiction_draft.md"]}},
            route=AgentRoute(
                task_size="small",
                route_key="narrative_generation_v2",
                agents=["Writer"],
            ),
            execution_backend="agentlab_orchestrated_cli",
            budget_mode="balanced",
            risk_level="candidate_only",
            model_profiles={},
            execution_policy={"external_context_approval_required": True},
            notes=[f"{_PREFLIGHT_NOTE_PREFIX}{preflight_spec_sha256}"],
        )
        plan_path = run_dir / "workflow_plan.yml"
        request_content = yaml.safe_dump(
            request,
            sort_keys=False,
            allow_unicode=True,
        )
        plan_content = yaml.safe_dump(
            plan.model_dump(mode="json"),
            sort_keys=False,
            allow_unicode=True,
        )
        _validate_operator_slot(
            request_path=request_path,
            request_content=request_content,
            plan_path=plan_path,
            plan_content=plan_content,
            expected_parent_identity=run_identity,
        )
        _publish_text_exclusive(
            request_path,
            request_content,
            conflict_error="live_preflight_existing_request_conflict",
            expected_parent_identity=run_identity,
        )
        session = prepare_live_writer_session(root, plan)
        if session is None or session.status != "pass":
            issues = session.issues if session is not None else ["not_activated"]
            raise ValueError(
                f"live_preflight_session_blocked:{chapter_id}:{','.join(issues)}"
            )
        repeated = prepare_live_writer_session(root, plan)
        if repeated is None or repeated.status != "pass":
            repeated_issues = (
                repeated.issues if repeated is not None else ["not_activated"]
            )
            raise ValueError(
                "live_preflight_repeat_session_blocked:"
                f"{chapter_id}:{','.join(repeated_issues)}"
            )
        byte_stable = (
            session.packet_sha256 == repeated.packet_sha256
            and session.packet_bytes == repeated.packet_bytes
            and session.context_manifest_sha256 == repeated.context_manifest_sha256
        )
        if not byte_stable:
            raise ValueError(f"live_preflight_session_not_byte_stable:{chapter_id}")
        pending_plans.append(
            (
                plan_path,
                plan_content,
                request_path,
                request_content,
                run_identity,
            )
        )
        rows.append(
            {
                "chapter_id": chapter_id,
                "task_id": task_id,
                "request_path": request_path.relative_to(root).as_posix(),
                "request_sha256": hashlib.sha256(request_path.read_bytes()).hexdigest(),
                "workflow_plan_path": plan_path.relative_to(root).as_posix(),
                "workflow_plan_sha256": hashlib.sha256(
                    plan_content.encode("utf-8")
                ).hexdigest(),
                "packet_sha256": session.packet_sha256,
                "repeat_packet_sha256": repeated.packet_sha256,
                "byte_stable_across_two_compiles": byte_stable,
                "packet_bytes": session.packet_bytes,
                "token_estimate": session.token_estimate,
                "loaded_file_count": session.loaded_file_count,
                "loaded_context_bytes": session.loaded_context_bytes,
                "duplicate_context_ratio": session.duplicate_context_ratio,
                "context_bundle_id": session.context_bundle_id,
                "context_manifest_sha256": session.context_manifest_sha256,
                "literary_memory_sha256": session.literary_memory_sha256,
                "literary_memory_occurrences": session.source_paths.count(memory),
                "provider_calls": session.provider_calls,
            }
        )

    legacy = preview_metrics.get("legacy_medians") or {}
    packet_median = int(median(row["packet_bytes"] for row in rows))
    context_median = int(median(row["loaded_context_bytes"] for row in rows))
    production_after = _tree_digest(production_root)
    result = {
        "schema_version": 1,
        "status": "pass",
        "project": project,
        "chapters": chapters,
        "candidate_only": True,
        "production_modified": production_before != production_after,
        "production_digest_before": production_before,
        "production_digest_after": production_after,
        "provider_calls": sum(row["provider_calls"] for row in rows),
        "rows": rows,
        "medians": {
            "packet_bytes": packet_median,
            "loaded_context_bytes": context_median,
        },
        "legacy_medians": legacy,
        "reductions_percent": {
            "packet_bytes": _reduction(legacy.get("payload_bytes"), packet_median),
            "context_bytes": _reduction(
                legacy.get("inventory_bytes"),
                context_median,
            ),
        },
        "checks": {
            "all_sessions_compiled": len(rows) == len(chapters),
            "literary_memory_present_once": all(
                row["literary_memory_occurrences"] == 1 for row in rows
            ),
            "byte_stable_across_two_compiles": all(
                row["byte_stable_across_two_compiles"] for row in rows
            ),
            "provider_execution_requested": False,
            "production_modified": production_before != production_after,
        },
        "quality_boundary": {
            "quality_equivalent_input_contract_complete": True,
            "literary_output_equivalence_proven": False,
            "positive_calibration_status": "missing_user_samples",
            "phase_2r_accepted": False,
            "gate_1_accepted": False,
        },
    }
    if (
        result["provider_calls"] != 0
        or result["production_modified"]
        or not result["checks"]["byte_stable_across_two_compiles"]
    ):
        raise ValueError("live_preflight_safety_invariant_failed")
    _publish_operator_plans(pending_plans)
    activation = _publish_batch_activation(
        root=root,
        project=project,
        spec_sha256=preflight_spec_sha256,
        rows=rows,
    )
    result["activation_receipt"] = activation
    return result


def load_validated_workflow_plan_data(
    *,
    agentlab_root: Path,
    project: str,
    task_id: str,
    plan_path: Path,
) -> dict[str, Any]:
    """Return sealed plan bytes after checking request and batch activation."""
    lexical_root = Path(agentlab_root).absolute()
    lexical_plan_path = Path(plan_path).absolute()
    expected_lexical_plan = (
        lexical_root / "projects" / project / "runs" / task_id / "workflow_plan.yml"
    )
    if lexical_plan_path != expected_lexical_plan:
        raise LiveWriterPlanActivationError(
            "live_writer_plan_activation_path_invalid"
        )
    root = lexical_root.resolve()
    plan_path = root / "projects" / project / "runs" / task_id / "workflow_plan.yml"
    try:
        plan_bytes = _read_root_relative_bytes(root, plan_path)
        plan = yaml.safe_load(plan_bytes.decode("utf-8")) or {}
    except (OSError, UnicodeDecodeError, yaml.YAMLError, ValueError) as exc:
        raise LiveWriterPlanActivationError(
            "live_writer_plan_activation_path_invalid"
        ) from exc
    if not isinstance(plan, dict):
        raise LiveWriterPlanActivationError("live_writer_plan_activation_invalid")
    if "sealed_user_request_content" in plan:
        raise LiveWriterPlanActivationError(
            "live_writer_plan_runtime_field_persisted"
        )

    notes = plan.get("notes") or []
    route = plan.get("route") if isinstance(plan.get("route"), dict) else {}
    is_registered_v2 = (
        route.get("route_key") == "narrative_generation_v2"
        and Path(str(plan.get("user_request_path") or "")).name
        == LIVE_WRITER_REQUEST_NAME
    )
    if not isinstance(notes, list):
        if is_registered_v2:
            raise LiveWriterPlanActivationError(
                "live_writer_plan_activation_marker_invalid"
            )
        return plan
    markers = [
        str(note)[len(_PREFLIGHT_NOTE_PREFIX) :]
        for note in notes
        if str(note).startswith(_PREFLIGHT_NOTE_PREFIX)
    ]
    if not markers:
        if is_registered_v2:
            raise LiveWriterPlanActivationError(
                "live_writer_plan_activation_marker_missing"
            )
        return plan
    if len(markers) != 1 or not re.fullmatch(r"[0-9a-f]{64}", markers[0]):
        raise LiveWriterPlanActivationError(
            "live_writer_plan_activation_marker_invalid"
        )

    spec_sha256 = markers[0]
    activation_path = (
        root
        / "projects"
        / project
        / "runs"
        / _ACTIVATION_DIR_NAME
        / f"{spec_sha256}.yml"
    )
    try:
        activation_bytes = _read_root_relative_bytes(root, activation_path)
        activation = yaml.safe_load(activation_bytes.decode("utf-8")) or {}
    except (OSError, UnicodeDecodeError, yaml.YAMLError, ValueError) as exc:
        raise LiveWriterPlanActivationError(
            "live_writer_plan_activation_missing"
        ) from exc
    if not isinstance(activation, dict):
        raise LiveWriterPlanActivationError("live_writer_plan_activation_invalid")
    if (
        activation.get("status") != "active"
        or activation.get("project") != project
        or activation.get("preflight_spec_sha256") != spec_sha256
        or activation.get("candidate_only") is not True
        or activation.get("production_modified") is not False
        or activation.get("task_count") != len(activation.get("tasks") or [])
    ):
        raise LiveWriterPlanActivationError("live_writer_plan_activation_invalid")
    task_rows = [
        row
        for row in activation.get("tasks") or []
        if isinstance(row, dict) and row.get("task_id") == task_id
    ]
    if len(task_rows) != 1:
        raise LiveWriterPlanActivationError(
            "live_writer_plan_activation_task_missing"
        )
    row = task_rows[0]
    try:
        relative_plan = plan_path.absolute().relative_to(root).as_posix()
        request_path = Path(str(plan.get("user_request_path") or ""))
        relative_request = request_path.absolute().relative_to(root).as_posix()
        request_bytes = _read_root_relative_bytes(root, request_path)
    except (OSError, ValueError) as exc:
        raise LiveWriterPlanActivationError(
            "live_writer_plan_activation_path_invalid"
        ) from exc
    if (
        row.get("workflow_plan_path") != relative_plan
        or row.get("workflow_plan_sha256")
        != hashlib.sha256(plan_bytes).hexdigest()
        or row.get("request_path") != relative_request
        or row.get("request_sha256")
        != hashlib.sha256(request_bytes).hexdigest()
    ):
        raise LiveWriterPlanActivationError(
            "live_writer_plan_activation_hash_mismatch"
        )
    sealed_plan = dict(plan)
    try:
        sealed_plan["sealed_user_request_content"] = request_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LiveWriterPlanActivationError(
            "live_writer_plan_activation_request_invalid"
        ) from exc
    return sealed_plan


def validate_live_writer_plan_activation(
    *,
    agentlab_root: Path,
    project: str,
    task_id: str,
    plan_path: Path,
) -> None:
    load_validated_workflow_plan_data(
        agentlab_root=agentlab_root,
        project=project,
        task_id=task_id,
        plan_path=plan_path,
    )


def _publish_batch_activation(
    *,
    root: Path,
    project: str,
    spec_sha256: str,
    rows: list[dict[str, Any]],
) -> dict[str, str]:
    batch_dir = _safe_batch_dir(root, project)
    activation_path = batch_dir / f"{spec_sha256}.yml"
    activation = {
        "schema_version": 1,
        "status": "active",
        "project": project,
        "preflight_spec_sha256": spec_sha256,
        "candidate_only": True,
        "production_modified": False,
        "task_count": len(rows),
        "tasks": [
            {
                "task_id": row["task_id"],
                "request_path": row["request_path"],
                "request_sha256": row["request_sha256"],
                "workflow_plan_path": row["workflow_plan_path"],
                "workflow_plan_sha256": row["workflow_plan_sha256"],
            }
            for row in rows
        ],
    }
    content = yaml.safe_dump(activation, sort_keys=False, allow_unicode=True)
    stat = batch_dir.stat(follow_symlinks=False)
    identity = (stat.st_dev, stat.st_ino)
    _publish_text_exclusive(
        activation_path,
        content,
        conflict_error="live_preflight_existing_activation_conflict",
        expected_parent_identity=identity,
    )
    if activation_path.read_text(encoding="utf-8") != content:
        raise ValueError("live_preflight_activation_publish_mismatch")
    return {
        "path": activation_path.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(activation_path.read_bytes()).hexdigest(),
    }


def _validate_operator_slot(
    *,
    request_path: Path,
    request_content: str,
    plan_path: Path,
    plan_content: str,
    expected_parent_identity: tuple[int, int] | None = None,
) -> None:
    if expected_parent_identity is not None:
        _validate_run_dir_identity(plan_path.parent, expected_parent_identity)
    if plan_path.is_symlink():
        raise ValueError("live_preflight_existing_plan_conflict")
    if request_path.is_symlink():
        raise ValueError("live_preflight_existing_request_conflict")
    if plan_path.exists():
        if not plan_path.is_file() or plan_path.read_text(
            encoding="utf-8"
        ) != plan_content:
            raise ValueError("live_preflight_existing_plan_conflict")
        if not request_path.is_file() or request_path.read_text(
            encoding="utf-8"
        ) != request_content:
            raise ValueError("live_preflight_existing_request_conflict")
    elif request_path.exists() and (
        not request_path.is_file()
        or request_path.read_text(encoding="utf-8") != request_content
    ):
        raise ValueError("live_preflight_existing_request_conflict")


def _publish_operator_plans(
    pending_plans: list[
        tuple[Path, str, Path, str, tuple[int, int]]
    ],
) -> None:
    for (
        plan_path,
        plan_content,
        request_path,
        request_content,
        run_identity,
    ) in pending_plans:
        _validate_operator_slot(
            request_path=request_path,
            request_content=request_content,
            plan_path=plan_path,
            plan_content=plan_content,
            expected_parent_identity=run_identity,
        )
    with ExitStack() as stack:
        slot_identities: dict[Path, tuple[int, int]] = {}
        for plan_path, _a, _b, _c, run_identity in pending_plans:
            previous = slot_identities.setdefault(plan_path.parent, run_identity)
            if previous != run_identity:
                raise ValueError("live_preflight_run_slot_identity_conflict")
        slots = {}
        for run_dir in sorted(slot_identities, key=lambda path: path.as_posix()):
            slots[run_dir] = stack.enter_context(
                _locked_run_slot(run_dir, slot_identities[run_dir])
            )
        written: list[tuple[_RunSlot, str, _PublishedFile]] = []
        try:
            for (
                plan_path,
                plan_content,
                _request_path,
                _request_content,
                run_identity,
            ) in pending_plans:
                slot = slots[plan_path.parent]
                published = _publish_text_exclusive(
                    plan_path,
                    plan_content,
                    conflict_error="live_preflight_existing_plan_conflict",
                    expected_parent_identity=run_identity,
                    slot=slot,
                )
                if published is not None:
                    written.append((slot, plan_path.name, published))
            for (
                plan_path,
                plan_content,
                request_path,
                request_content,
                run_identity,
            ) in pending_plans:
                _validate_operator_slot(
                    request_path=request_path,
                    request_content=request_content,
                    plan_path=plan_path,
                    plan_content=plan_content,
                    expected_parent_identity=run_identity,
                )
        except Exception:
            for slot, name, published in reversed(written):
                _remove_published_file(slot, name, published)
            raise


def _publish_text_exclusive(
    path: Path,
    content: str,
    *,
    conflict_error: str,
    expected_parent_identity: tuple[int, int] | None = None,
    slot: _RunSlot | None = None,
) -> _PublishedFile | None:
    if slot is None:
        if expected_parent_identity is None:
            parent_stat = path.parent.stat(follow_symlinks=False)
            expected_parent_identity = (parent_stat.st_dev, parent_stat.st_ino)
        with _locked_run_slot(path.parent, expected_parent_identity) as locked:
            return _publish_text_exclusive(
                path,
                content,
                conflict_error=conflict_error,
                expected_parent_identity=expected_parent_identity,
                slot=locked,
            )
    if slot.run_dir != path.parent:
        raise ValueError("live_preflight_run_slot_mismatch")
    temp_name = f".{path.name}.{secrets.token_hex(12)}.tmp"
    fd = os.open(
        temp_name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
        dir_fd=slot.dir_fd,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(
                temp_name,
                path.name,
                src_dir_fd=slot.dir_fd,
                dst_dir_fd=slot.dir_fd,
                follow_symlinks=False,
            )
        except FileExistsError:
            if _read_slot_file(slot, path.name) == content:
                return None
            raise ValueError(conflict_error) from None
        stat = os.stat(path.name, dir_fd=slot.dir_fd, follow_symlinks=False)
        return _PublishedFile(device=stat.st_dev, inode=stat.st_ino)
    finally:
        try:
            os.unlink(temp_name, dir_fd=slot.dir_fd)
        except FileNotFoundError:
            pass
        os.fsync(slot.dir_fd)


@contextmanager
def _locked_run_slot(
    run_dir: Path,
    expected_identity: tuple[int, int],
):
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        dir_fd = os.open(run_dir, flags)
    except OSError as exc:
        raise ValueError("live_preflight_run_dir_changed") from exc
    lock_fd: int | None = None
    try:
        stat = os.fstat(dir_fd)
        if (stat.st_dev, stat.st_ino) != expected_identity:
            raise ValueError("live_preflight_run_dir_changed")
        lock_fd = os.open(
            ".narrative_v2_preflight.lock",
            os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=dir_fd,
        )
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        yield _RunSlot(
            run_dir=run_dir,
            dir_fd=dir_fd,
            lock_fd=lock_fd,
            identity=expected_identity,
        )
    finally:
        if lock_fd is not None:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
        os.close(dir_fd)


def _read_slot_file(slot: _RunSlot, name: str) -> str | None:
    try:
        fd = os.open(
            name,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=slot.dir_fd,
        )
    except (FileNotFoundError, OSError):
        return None
    with os.fdopen(fd, "r", encoding="utf-8") as handle:
        return handle.read()


def _read_root_relative_bytes(root: Path, path: Path) -> bytes:
    try:
        relative = path.absolute().relative_to(root.absolute())
    except ValueError as exc:
        raise ValueError("live_preflight_read_outside_root") from exc
    if not relative.parts:
        raise ValueError("live_preflight_read_path_invalid")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    dir_flags = flags | getattr(os, "O_DIRECTORY", 0)
    current_fd = os.open(root, dir_flags)
    try:
        for part in relative.parts[:-1]:
            next_fd = os.open(part, dir_flags, dir_fd=current_fd)
            os.close(current_fd)
            current_fd = next_fd
        file_fd = os.open(relative.parts[-1], flags, dir_fd=current_fd)
        with os.fdopen(file_fd, "rb") as handle:
            return handle.read()
    finally:
        os.close(current_fd)


def _remove_published_file(
    slot: _RunSlot,
    name: str,
    published: _PublishedFile,
) -> None:
    try:
        stat = os.stat(name, dir_fd=slot.dir_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    if (stat.st_dev, stat.st_ino) != (published.device, published.inode):
        return
    os.unlink(name, dir_fd=slot.dir_fd)
    os.fsync(slot.dir_fd)


def _validate_run_dir_identity(
    run_dir: Path,
    expected_identity: tuple[int, int],
) -> None:
    if run_dir.is_symlink():
        raise ValueError("live_preflight_run_dir_changed")
    try:
        stat = run_dir.stat(follow_symlinks=False)
    except OSError as exc:
        raise ValueError("live_preflight_run_dir_changed") from exc
    if (stat.st_dev, stat.st_ino) != expected_identity:
        raise ValueError("live_preflight_run_dir_changed")


def _safe_run_dir(root: Path, project: str, task_id: str) -> Path:
    run_dir = root / "projects" / project / "runs" / task_id
    if _has_symlink_component(root, run_dir):
        raise ValueError("live_preflight_run_dir_symlinked")
    run_dir.mkdir(parents=True, exist_ok=True)
    if _has_symlink_component(root, run_dir):
        raise ValueError("live_preflight_run_dir_symlinked")
    resolved = run_dir.resolve()
    if resolved != run_dir.absolute() or root not in resolved.parents:
        raise ValueError("live_preflight_run_dir_outside_root")
    return resolved


def _safe_batch_dir(root: Path, project: str) -> Path:
    batch_dir = root / "projects" / project / "runs" / _ACTIVATION_DIR_NAME
    if _has_symlink_component(root, batch_dir):
        raise ValueError("live_preflight_activation_dir_symlinked")
    batch_dir.mkdir(parents=True, exist_ok=True)
    if _has_symlink_component(root, batch_dir):
        raise ValueError("live_preflight_activation_dir_symlinked")
    resolved = batch_dir.resolve()
    if resolved != batch_dir.absolute() or root not in resolved.parents:
        raise ValueError("live_preflight_activation_dir_outside_root")
    parent_fd = os.open(
        resolved.parent,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)
    return resolved


def _verified_ref(root: Path, raw: Any) -> Path:
    if not isinstance(raw, dict):
        raise ValueError("live_preflight_reference_must_be_mapping")
    raw_path = str(raw.get("path") or "").strip()
    expected = str(raw.get("sha256") or "").strip().lower()
    relative = Path(raw_path)
    if not raw_path or relative.is_absolute() or ".." in relative.parts:
        raise ValueError("live_preflight_reference_path_invalid")
    lexical = root / relative
    if _has_symlink_component(root, lexical):
        raise ValueError(f"live_preflight_reference_symlinked:{raw_path}")
    path = lexical.resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("live_preflight_reference_outside_root") from exc
    if not path.is_file():
        raise ValueError(f"live_preflight_reference_missing:{raw_path}")
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError(f"live_preflight_reference_hash_mismatch:{raw_path}")
    return path


def _load_mapping(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(value, dict):
        raise ValueError(f"live_preflight_mapping_required:{path.name}")
    return value


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    if not root.is_dir():
        return digest.hexdigest()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def _has_symlink_component(root: Path, path: Path) -> bool:
    try:
        relative = path.absolute().relative_to(root.absolute())
    except ValueError:
        return True
    current = root.absolute()
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def _reduction(baseline: Any, current: int) -> float:
    try:
        base = int(baseline)
    except (TypeError, ValueError):
        return 0.0
    if base <= 0:
        return 0.0
    return round((base - current) * 100.0 / base, 2)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", type=Path)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = preflight_live_writer_sessions(
        args.spec,
        repository_root=args.repository_root,
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        atomic_write_text(args.output, rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
