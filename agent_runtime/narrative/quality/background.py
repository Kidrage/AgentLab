"""Background adapter for hash-bound, candidate-only narrative revisions."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import secrets
import fcntl
from typing import Any, Mapping

import yaml

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_CONTRACT_LIST_FIELDS = (
    "must_preserve",
    "must_change",
    "causal_requirements",
    "character_knowledge_before",
    "character_knowledge_after",
    "forbidden_regressions",
)
_CONTRACT_SCALAR_FIELDS = (
    "revision_contract_id",
    "target_scene",
    "problem_type",
    "evidence",
    "allowed_freedom",
    "decision_cost",
    "new_information",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def _identifier(value: object) -> str:
    candidate = str(value or "").strip()
    if not _IDENTIFIER_RE.fullmatch(candidate):
        raise ValueError("background_revision_identifier_invalid")
    return candidate


def _publish_yaml_exclusive(root: Path, path: Path, value: Mapping[str, Any]) -> bool:
    """Publish one immutable YAML file via no-follow directory descriptors."""
    root = root.resolve(strict=True)
    try:
        relative = path.absolute().relative_to(root.absolute())
    except ValueError as exc:
        raise ValueError("background_revision_publish_outside_root") from exc
    if not relative.parts or ".." in relative.parts:
        raise ValueError("background_revision_publish_path_invalid")
    content = yaml.safe_dump(dict(value), sort_keys=False, allow_unicode=True)
    dir_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    current_fd = os.open(root, dir_flags)
    lock_fd: int | None = None
    try:
        for part in relative.parts[:-1]:
            try:
                next_fd = os.open(part, dir_flags, dir_fd=current_fd)
            except FileNotFoundError:
                os.mkdir(part, 0o700, dir_fd=current_fd)
                next_fd = os.open(part, dir_flags, dir_fd=current_fd)
                os.fsync(current_fd)
            os.close(current_fd)
            current_fd = next_fd
        lock_fd = os.open(
            ".background_revision.lock",
            os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=current_fd,
        )
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        name = relative.parts[-1]
        try:
            existing_fd = os.open(
                name,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=current_fd,
            )
        except FileNotFoundError:
            existing_fd = None
        if existing_fd is not None:
            with os.fdopen(existing_fd, "r", encoding="utf-8") as handle:
                if handle.read() != content:
                    raise ValueError("background_revision_existing_artifact_conflict")
            return False
        temp_name = f".{name}.{secrets.token_hex(12)}.tmp"
        fd = os.open(
            temp_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=current_fd,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.link(
                temp_name,
                name,
                src_dir_fd=current_fd,
                dst_dir_fd=current_fd,
                follow_symlinks=False,
            )
            os.fsync(current_fd)
        finally:
            try:
                os.unlink(temp_name, dir_fd=current_fd)
            except FileNotFoundError:
                pass
        return True
    finally:
        if lock_fd is not None:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
        os.close(current_fd)


def _ref(root: Path, path: Path) -> dict[str, str]:
    from agent_runtime.narrative.production.live_writer_preflight import (
        _read_root_relative_bytes,
    )

    resolved = path.absolute()
    resolved.relative_to(root.absolute())
    if _has_symlink_component(root, path):
        raise ValueError("background_revision_symlink_forbidden")
    raw = _read_root_relative_bytes(root, path)
    return {
        "path": resolved.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def _load_project_yaml(
    root: Path,
    project: str,
    value: object,
    expected_sha256: object,
) -> tuple[Path, dict[str, Any], str]:
    from agent_runtime.narrative.production.live_writer_preflight import (
        _read_root_relative_bytes,
    )

    path = Path(str(value or ""))
    candidate = path if path.is_absolute() else root / path
    try:
        candidate.absolute().relative_to((root / "projects" / project).absolute())
    except ValueError as exc:
        raise ValueError("background_revision_proposal_unsafe") from exc
    expected = str(expected_sha256 or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError("background_revision_proposal_hash_missing")
    if _has_symlink_component(root, candidate):
        raise ValueError("background_revision_proposal_unsafe")
    raw = _read_root_relative_bytes(root, candidate)
    observed = hashlib.sha256(raw).hexdigest()
    if observed != expected:
        raise ValueError("background_revision_proposal_hash_mismatch")
    try:
        value = yaml.safe_load(raw.decode("utf-8")) or {}
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ValueError("background_revision_proposal_invalid") from exc
    if not isinstance(value, dict):
        raise ValueError("background_revision_proposal_invalid")
    return candidate.absolute(), value, observed


def _load_existing_yaml(root: Path, path: Path) -> dict[str, Any] | None:
    from agent_runtime.narrative.production.live_writer_preflight import (
        _read_root_relative_bytes,
    )

    try:
        raw = _read_root_relative_bytes(root, path)
    except FileNotFoundError:
        return None
    try:
        value = yaml.safe_load(raw.decode("utf-8")) or {}
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ValueError("background_revision_existing_yaml_invalid") from exc
    if not isinstance(value, dict):
        raise ValueError("background_revision_existing_yaml_invalid")
    return value


def _contract_issues(contract: Mapping[str, Any], *, chapter: int) -> list[str]:
    issues: list[str] = []
    if contract.get("chapter_id") != chapter:
        issues.append("revision_contract_identity_mismatch")
    if contract.get("rewrite_scope") not in {"scene", "chapter"}:
        issues.append("revision_contract_scope_invalid")
    if any(not contract.get(field) for field in _CONTRACT_SCALAR_FIELDS):
        issues.append("revision_contract_incomplete")
    if any(
        not isinstance(contract.get(field), list) or not contract.get(field)
        for field in _CONTRACT_LIST_FIELDS
    ):
        issues.append("revision_contract_incomplete")
    return list(dict.fromkeys(issues))


def _source_task_id(request: Mapping[str, Any], chapter: int) -> str:
    configured = request.get("source_task_ids")
    if isinstance(configured, Mapping) and configured.get(str(chapter)):
        return _identifier(configured[str(chapter)])
    from agent_runtime.narrative_eval import _safe_eval_task_id

    return _safe_eval_task_id(chapter, str((request.get("config") or {}).get("eval_id")))


def _write_triggering_audit(
    *,
    root: Path,
    project: str,
    source_task_id: str,
    source_candidate: Path,
    lineage_id: str,
    chapter: int,
    contract: Mapping[str, Any],
) -> tuple[str, Path]:
    audit_id = f"audit-revision-ch{chapter:03d}-{lineage_id}"
    audit_path = (
        root
        / "projects"
        / project
        / "runs"
        / audit_id
        / "deterministic_candidate_audit_v2.yml"
    )
    _publish_yaml_exclusive(
        root,
        audit_path,
        {
            "schema_version": 1,
            "report_type": "agentlab_background_revision_audit",
            "contract_version": 2,
            "project": project,
            "task_id": source_task_id,
            "candidate_sha256": _sha256(source_candidate),
            "status": "fail",
            "issues": [
                {
                    "id": str(contract.get("problem_type") or "literary_revision"),
                    "status": "fail",
                    "revision_contract_id": str(contract.get("revision_contract_id") or ""),
                }
            ],
            "candidate_only": True,
            "production_modified": False,
        },
    )
    return audit_id, audit_path


def _build_revision_row(
    *,
    root: Path,
    project: str,
    chapter: int,
    job_id: str,
    candidate_set_id: str,
    revision_attempt_id: str,
    source_task_id: str,
    revision_task_id: str,
    proposal_path: Path,
    proposal_sha256: str,
    contract_path: Path,
    triggering_audit: Path,
) -> dict[str, Any]:
    revision_run = root / "projects" / project / "runs" / revision_task_id
    revised_draft = revision_run / "fiction_draft.md"
    row = {
        "chapter": chapter,
        "job_id": job_id,
        "candidate_set_id": candidate_set_id,
        "revision_attempt_id": revision_attempt_id,
        "task_id": revision_task_id,
        "source_task_id": source_task_id,
        **_prefixed_ref(root, revised_draft, "draft"),
        **_prefixed_ref(root, proposal_path, "proposal", sha256=proposal_sha256),
        **_prefixed_ref(root, contract_path, "contract"),
        **_prefixed_ref(
            root,
            revision_run / "narrative_v2_writer_request.yml",
            "revision_request",
        ),
        **_prefixed_ref(
            root,
            revision_run / "writer_v2_output_contract.yml",
            "writer_output_contract",
        ),
        **_prefixed_ref(
            root,
            revision_run / "narrative_v2_writer_session_receipt.yml",
            "writer_session_receipt",
        ),
        **_prefixed_ref(root, triggering_audit, "triggering_audit"),
    }
    row["path"] = row["draft_path"]
    row["sha256"] = row["draft_sha256"]
    return row


def _prefixed_ref(
    root: Path,
    path: Path,
    prefix: str,
    *,
    sha256: str | None = None,
) -> dict[str, str]:
    reference = _ref(root, path)
    if sha256 is not None and reference["sha256"] != sha256:
        raise ValueError(f"background_revision_{prefix}_hash_drift")
    return {
        f"{prefix}_path": reference["path"],
        f"{prefix}_sha256": reference["sha256"],
    }


def _execute_contract(
    request: Mapping[str, Any],
    *,
    proposal_path: Path,
    proposal_sha256: str,
    contract: Mapping[str, Any],
    contract_index: int,
) -> dict[str, Any]:
    from agent_runtime.narrative.production.live_revision_preflight import (
        preflight_live_writer_revision,
    )
    from agent_runtime.narrative.production.live_writer import (
        materialize_registered_writer_result,
    )
    from agent_runtime.narrative.production.live_writer_preflight import (
        load_validated_workflow_plan_data,
    )
    from agent_runtime.schemas import WorkflowPlan

    # agent_runner is also a direct CLI entry module, so use its canonical import.
    from agent_runner import run_agent_model

    root = Path(str(request["agentlab_root"])).resolve()
    project = _identifier(request.get("project"))
    chapter = int(contract.get("chapter_id") or 0)
    source_task_id = _source_task_id(request, chapter)
    source_run = root / "projects" / project / "runs" / source_task_id
    source_request = source_run / "narrative_v2_writer_request.yml"
    source_candidate = source_run / "fiction_draft.md"
    source_contract = source_run / "writer_v2_output_contract.yml"
    source_paths = (source_request, source_candidate, source_contract)
    if not all(
        path.is_file() and not _has_symlink_component(root, path)
        for path in source_paths
    ):
        raise ValueError(f"background_revision_source_invalid:{chapter}")

    job_id = _identifier(request.get("job_id"))
    lineage_id = hashlib.sha256(
        (
            f"{project}:{job_id}:{proposal_sha256}:{chapter}:{contract_index}:"
            f"{contract.get('revision_contract_id')}"
        ).encode("utf-8")
    ).hexdigest()[:16]
    audit_id, triggering_audit = _write_triggering_audit(
        root=root,
        project=project,
        source_task_id=source_task_id,
        source_candidate=source_candidate,
        lineage_id=lineage_id,
        chapter=chapter,
        contract=contract,
    )
    candidate_root = (
        root
        / "projects"
        / project
        / "candidates"
        / "background_revisions"
        / job_id
        / proposal_sha256[:16]
    )
    contract_path = candidate_root / f"contract-{contract_index:02d}-ch{chapter:03d}.yml"
    bound_contract = {
        **dict(contract),
        "schema_version": 1,
        "source_candidate_sha256": _sha256(source_candidate),
        "triggering_audit_sha256": _sha256(triggering_audit),
        "source_proposal": {
            "path": proposal_path.relative_to(root).as_posix(),
            "sha256": proposal_sha256,
        },
    }
    _publish_yaml_exclusive(
        root,
        contract_path,
        bound_contract,
    )

    revision_task_id = f"task-narrative-revision-ch{chapter:03d}-{lineage_id}"
    lease_expires_at = str(request.get("lease_expires_at") or "").strip()
    spec_path = candidate_root / f"spec-{contract_index:02d}-ch{chapter:03d}.yml"
    candidate_set_id = _identifier(
        request.get("candidate_set_id") or request.get("job_id")
    )
    revision_attempt_id = f"attempt-{lineage_id}"
    revision_lease_token = f"lease-{lineage_id}"
    revision_run = root / "projects" / project / "runs" / revision_task_id
    materialized_path = candidate_root / f"materialized-{contract_index:02d}.yml"
    call_fence = candidate_root / f"provider-call-{contract_index:02d}.yml"

    # A controller retry receives a fresh lease, but the provider result is bound
    # to the proposal lineage rather than to that controller attempt. Recover a
    # complete immutable materialization before consulting the old spec/lease so
    # a later controller attempt can close the batch without paying twice.
    existing_materialized = _load_existing_yaml(root, materialized_path)
    if existing_materialized is not None:
        from agent_runtime.narrative_heavy_audit import (
            validate_revision_draft_binding,
        )

        existing = validate_revision_draft_binding(
            root / "projects" / project,
            chapter=chapter,
            source_task_id=source_task_id,
            revision_task_id=revision_task_id,
            expected_binding=existing_materialized,
        )
        if existing.get("status") != "pass":
            raise RuntimeError("background_revision_materialized_binding_invalid")
        row = _build_revision_row(
            root=root,
            project=project,
            chapter=chapter,
            job_id=job_id,
            candidate_set_id=candidate_set_id,
            revision_attempt_id=revision_attempt_id,
            source_task_id=source_task_id,
            revision_task_id=revision_task_id,
            proposal_path=proposal_path,
            proposal_sha256=proposal_sha256,
            contract_path=contract_path,
            triggering_audit=triggering_audit,
        )
        _publish_yaml_exclusive(root, materialized_path, row)
        return row

    # An incomplete lineage cannot prove whether the provider call completed.
    # Never refresh its lease or issue another provider call automatically.
    if (
        _load_existing_yaml(root, spec_path) is not None
        or _load_existing_yaml(root, call_fence) is not None
        or revision_run.exists()
    ):
        raise RuntimeError("background_revision_provider_result_unknown")

    from agent_runtime.narrative.production.revision_attempts import (
        revision_attempt_count,
    )

    source_rewrite_count = revision_attempt_count(
        root=root,
        project=project,
        source_run_id=source_task_id,
        candidate_set_id=candidate_set_id,
    )
    _publish_yaml_exclusive(
        root,
        spec_path,
        {
            "schema_version": 1,
            "project": project,
            "task_id": revision_task_id,
            "chapter_id": chapter,
            "candidate_only": True,
            "candidate_set_id": candidate_set_id,
            "source_job_id": job_id,
            "source_run_id": source_task_id,
            "triggered_by_audit_id": audit_id,
            "attempt_id": revision_attempt_id,
            "lease_token": revision_lease_token,
            "lease_expires_at": lease_expires_at,
            "automatic_rewrite_count": source_rewrite_count,
            "source_writer_request": _ref(root, source_request),
            "source_candidate": _ref(root, source_candidate),
            "triggering_audit": _ref(root, triggering_audit),
            "revision_contract": _ref(root, contract_path),
        },
    )
    preflight_live_writer_revision(spec_path, repository_root=root)
    call_reserved = _publish_yaml_exclusive(
        root,
        call_fence,
        {
            "schema_version": 1,
            "status": "provider_call_reserved",
            "candidate_only": True,
            "production_modified": False,
            "project": project,
            "job_id": job_id,
            "chapter": chapter,
            "revision_task_id": revision_task_id,
            "spec_path": spec_path.relative_to(root).as_posix(),
            "spec_sha256": _sha256(spec_path),
        },
    )
    if not call_reserved:
        raise RuntimeError("background_revision_provider_result_unknown")
    plan = WorkflowPlan.model_validate(
        load_validated_workflow_plan_data(
            agentlab_root=root,
            project=project,
            task_id=revision_task_id,
            plan_path=revision_run / "workflow_plan.yml",
        )
    )
    result = run_agent_model(
        root,
        plan,
        "Writer",
        revision_run / "fiction_draft.md",
        apply_patches=False,
    )
    delivery = materialize_registered_writer_result(
        result,
        revision_run,
        revision_task_id,
    )
    if delivery.get("status") != "pass":
        reason = str(getattr(result, "error", "") or "")
        issues = [str(item) for item in delivery.get("issues") or []]
        raise RuntimeError(
            "background_revision_writer_blocked:"
            + (reason or ",".join(issues) or "materialization_failed")
        )
    row = _build_revision_row(
        root=root,
        project=project,
        chapter=chapter,
        job_id=job_id,
        candidate_set_id=candidate_set_id,
        revision_attempt_id=revision_attempt_id,
        source_task_id=source_task_id,
        revision_task_id=revision_task_id,
        proposal_path=proposal_path,
        proposal_sha256=proposal_sha256,
        contract_path=contract_path,
        triggering_audit=triggering_audit,
    )
    _publish_yaml_exclusive(
        root,
        materialized_path,
        row,
    )
    return row


def run_background_revision(request: dict[str, Any]) -> dict[str, object]:
    """Execute every verified contract once and retain only materialized candidates."""
    root = Path(str(request["agentlab_root"])).resolve()
    project = _identifier(request.get("project"))
    job_id = _identifier(request.get("job_id"))
    controller_attempt_id = _identifier(request.get("attempt_id"))
    prior_results = request.get("prior_results") or {}
    heavy = prior_results.get("heavy_audit") or {}
    verifier = prior_results.get("revision_support_verifier") or {}
    attempt_dir = (
        root
        / "projects"
        / project
        / "background_jobs"
        / job_id
        / "attempts"
        / controller_attempt_id
    )
    receipt_path = attempt_dir / "revision_closure_receipt.yml"
    selected: dict[str, dict[str, Any]] = {}
    changed_chapters: list[int] = []
    normalized: list[dict[str, Any]] = []
    try:
        from agent_runtime.narrative.quality.selection import (
            load_selected_revision_records,
        )

        selected = {
            str(chapter): record
            for chapter, record in load_selected_revision_records(request).items()
        }
        proposal_path, proposal, proposal_sha256 = _load_project_yaml(
            root,
            project,
            verifier.get("output_path") or heavy.get("rewrite_proposal"),
            verifier.get("output_sha256")
            or heavy.get("rewrite_proposal_sha256"),
        )
        contracts = proposal.get("proposals") if isinstance(proposal, dict) else None
        if (
            not isinstance(proposal, dict)
            or proposal.get("status") != "proposed"
            or proposal.get("rewrite_required") is not True
            or proposal.get("direct_draft_edits") is not False
            or not isinstance(contracts, list)
            or not contracts
        ):
            raise ValueError("missing_executable_scene_revision_contracts")
        start = int(
            (request.get("config") or {}).get("start_chapter")
            or request["batch"]["start"]
        )
        end = int(
            (request.get("config") or {}).get("end_chapter")
            or request["batch"]["end"]
        )
        chapters: list[int] = []
        for raw in contracts:
            if not isinstance(raw, Mapping):
                raise ValueError("revision_contract_not_mapping")
            chapter = int(raw.get("chapter_id") or 0)
            if chapter < start or chapter > end:
                raise ValueError(f"revision_contract_chapter_out_of_range:{chapter}")
            issues = _contract_issues(raw, chapter=chapter)
            if issues:
                raise ValueError(issues[0])
            if chapter in chapters:
                raise ValueError(f"multiple_revision_contracts_for_chapter:{chapter}")
            chapters.append(chapter)
            normalized.append(dict(raw))
        for index, contract in enumerate(normalized, start=1):
            row = _execute_contract(
                request,
                proposal_path=proposal_path,
                proposal_sha256=proposal_sha256,
                contract=contract,
                contract_index=index,
            )
            selected[str(row["chapter"])] = row
            changed_chapters.append(int(row["chapter"]))
        receipt: dict[str, object] = {
            "schema_version": 1,
            "status": "pass",
            "project": project,
            "job_id": job_id,
            "attempt_id": controller_attempt_id,
            "candidate_only": True,
            "production_modified": False,
            "chapter_range": [start, end],
            "source_audit_task_id": heavy.get("task_id"),
            "revision_contract_count": len(normalized),
            "selected_revision_count": len(selected),
            "changed_chapters": sorted(changed_chapters),
            "selected_revisions": selected,
            "fact_dependencies": {},
        }
    except (KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
        receipt = {
            "schema_version": 1,
            "status": "decision_required",
            "project": project,
            "job_id": job_id,
            "attempt_id": controller_attempt_id,
            "candidate_only": True,
            "production_modified": False,
            "chapter_range": [request["batch"]["start"], request["batch"]["end"]],
            "source_audit_task_id": heavy.get("task_id"),
            "revision_contract_count": len(normalized),
            "selected_revision_count": len(selected),
            "changed_chapters": sorted(changed_chapters),
            "selected_revisions": selected,
            "reason": str(exc) or type(exc).__name__,
        }
    _publish_yaml_exclusive(root, receipt_path, receipt)
    receipt_ref = _ref(root, receipt_path)
    return {
        **receipt,
        "revision_closure_receipt": str(receipt_path),
        "revision_closure_receipt_sha256": receipt_ref["sha256"],
    }
