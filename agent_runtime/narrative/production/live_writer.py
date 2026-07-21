"""Narrative-only live Writer adapter for the v2 compiled packet."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
from typing import Any

import yaml

from agent_runtime.atomic_io import atomic_write_yaml
from agent_runtime.narrative.production.brief_compiler import BriefCompiler
from agent_runtime.narrative.production.context_compiler import ContextRequest
from agent_runtime.narrative.production.literary_memory import (
    validate_literary_memory_snapshot,
)
from agent_runtime.narrative.production.writer_packet_preview import (
    build_writer_packet_preview,
)


LIVE_WRITER_REQUEST_NAME = "narrative_v2_writer_request.yml"
LIVE_WRITER_RECEIPT_NAME = "narrative_v2_writer_session_receipt.yml"
LIVE_WRITER_OUTPUT_CONTRACT_NAME = "writer_v2_output_contract.yml"
MAX_REQUEST_BYTES = 128 * 1024
MAX_SUPPLEMENTAL_SOURCES = 8
MAX_SUPPLEMENTAL_BYTES = 512 * 1024
MAX_WRITER_PRIVATE_SOURCES = 3
MAX_WRITER_PRIVATE_BYTES = 128 * 1024

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CHAPTER_RE = re.compile(
    r"(?:^|[_-])(?:chapter|ch)[_-]?0*(\d+)(?=[_.-]|$)",
    flags=re.IGNORECASE,
)


@dataclass
class LiveWriterSession:
    status: str
    messages: list[dict[str, str]] = field(default_factory=list)
    source_paths: list[Path] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    packet_sha256: str = ""
    packet_bytes: int = 0
    token_estimate: int = 0
    loaded_file_count: int = 0
    loaded_context_bytes: int = 0
    duplicate_context_ratio: float = 0.0
    context_bundle_id: str = ""
    context_manifest_path: str = ""
    context_manifest_sha256: str = ""
    literary_memory_sha256: str = ""
    receipt_path: str = ""
    provider_calls: int = 0
    candidate_only: bool = True
    production_modified: bool = False


@dataclass(frozen=True)
class _ReferenceSnapshot:
    name: str
    path: Path
    sha256: str


def prepare_live_writer_session(
    agentlab_root: Path,
    plan: Any,
) -> LiveWriterSession | None:
    """Compile one live v2 Writer session, or return ``None`` for legacy runs."""
    root = Path(agentlab_root).resolve()
    try:
        raw_run_dir = Path(getattr(plan, "run_dir", None))
    except (OSError, TypeError, ValueError):
        return None
    activation_run_dir = raw_run_dir if raw_run_dir.is_absolute() else root / raw_run_dir
    activation_path = activation_run_dir / LIVE_WRITER_REQUEST_NAME
    sealed_request = str(
        getattr(plan, "sealed_user_request_content", "") or ""
    )
    request_missing = not activation_path.exists() and not activation_path.is_symlink()
    if request_missing and not sealed_request:
        return None
    project = str(getattr(plan, "project", "") or "").strip()
    task_id = str(getattr(plan, "task_id", "") or "").strip()
    issues: list[str] = []
    if not _IDENTIFIER_RE.fullmatch(project):
        return LiveWriterSession(status="blocked", issues=["live_writer_project_invalid"])
    if not _IDENTIFIER_RE.fullmatch(task_id):
        return LiveWriterSession(status="blocked", issues=["live_writer_task_id_invalid"])

    expected_run = root / "projects" / project / "runs" / task_id
    project_root = _bound_plan_path(
        root,
        getattr(plan, "project_root", None),
        root / "projects" / project,
        "live_writer_project_root_invalid",
        issues,
    )
    run_dir = _bound_plan_path(
        root,
        getattr(plan, "run_dir", None),
        expected_run,
        "live_writer_run_dir_invalid",
        issues,
    )
    if project_root is None or run_dir is None:
        return LiveWriterSession(status="blocked", issues=issues)
    request_path = run_dir / LIVE_WRITER_REQUEST_NAME

    receipt_path = run_dir / LIVE_WRITER_RECEIPT_NAME
    _remove_stale_receipt(receipt_path)
    if request_missing:
        return _blocked_live_writer_preflight(
            run_dir,
            task_id,
            ["live_writer_request_missing_after_activation"],
        )
    if request_path.is_symlink() or _has_symlink_component(root, request_path):
        return _blocked_live_writer_preflight(
            run_dir,
            task_id,
            ["live_writer_request_symlink_forbidden"],
        )
    if sealed_request:
        raw = sealed_request.encode("utf-8")
        if len(raw) > MAX_REQUEST_BYTES:
            issues.append("live_writer_request_too_large")
            raw = b""
    else:
        raw = _read_bounded(
            request_path,
            MAX_REQUEST_BYTES,
            "live_writer_request",
            issues,
        )
    if not raw:
        return _blocked_live_writer_preflight(run_dir, task_id, issues)
    request_sha256 = hashlib.sha256(raw).hexdigest()
    request = _decode_mapping(raw, "live_writer_request", issues)
    if not request:
        return _blocked_live_writer_preflight(run_dir, task_id, issues)

    _validate_identity(request, project, task_id, issues)
    chapter_id = request.get("chapter_id")
    if not _positive_int(chapter_id):
        issues.append("live_writer_chapter_id_invalid")
        chapter_id = 0
    required_outputs = (
        (getattr(plan, "included_agents", {}) or {}).get("Writer") or {}
    ).get("required_outputs")
    if required_outputs != ["fiction_draft.md"]:
        issues.append("live_writer_required_outputs_must_be_prose_only")
    execution_policy = getattr(plan, "execution_policy", {}) or {}
    if execution_policy.get("external_context_approval_required") is not True:
        issues.append("live_writer_external_context_approval_policy_required")
    route_key = str(
        getattr(getattr(plan, "route", None), "route_key", "") or ""
    )
    if route_key not in {"narrative_light_chapter", "narrative_generation_v2"}:
        issues.append("live_writer_runtime_route_is_not_narrative_generation")

    writer_manifest_path = _verified_ref(
        root,
        project,
        request.get("writer_input_manifest"),
        "writer_input_manifest",
        issues,
        project_scoped=False,
    )
    brief_source = _verified_ref(
        root,
        project,
        request.get("creative_brief_source"),
        "creative_brief_source",
        issues,
        project_scoped=True,
    )
    canon = _verified_ref(
        root,
        project,
        request.get("canon_snapshot"),
        "canon_snapshot",
        issues,
        project_scoped=True,
    )
    hard_state = _verified_ref(
        root,
        project,
        request.get("hard_state"),
        "hard_state",
        issues,
        project_scoped=True,
    )
    predecessor_ref = request.get("predecessor_prose")
    predecessor = _verified_ref(
        root,
        project,
        predecessor_ref,
        "predecessor_prose",
        issues,
        project_scoped=True,
    )
    predecessor_chapter = (
        predecessor_ref.get("chapter_id")
        if isinstance(predecessor_ref, dict)
        else None
    )
    if chapter_id and predecessor_chapter != chapter_id - 1:
        issues.append("live_writer_predecessor_chapter_mismatch")
    literary_memory = _verified_ref(
        root,
        project,
        request.get("literary_memory"),
        "literary_memory",
        issues,
        project_scoped=True,
        required_project_area="candidates",
    )
    supplemental = _verified_ref_list(
        root,
        project,
        request.get("supplemental_context_sources"),
        "supplemental_context_sources",
        issues,
        max_count=MAX_SUPPLEMENTAL_SOURCES,
        max_bytes=MAX_SUPPLEMENTAL_BYTES,
        project_scoped=True,
    )
    writer_private = _verified_ref_list(
        root,
        project,
        request.get("writer_private_sources"),
        "writer_private_sources",
        issues,
        max_count=MAX_WRITER_PRIVATE_SOURCES,
        max_bytes=MAX_WRITER_PRIVATE_BYTES,
        project_scoped=False,
        allowed_prefix=Path("agent_templates"),
    )
    for index, path in enumerate(supplemental):
        if not _supplemental_source_is_allowlisted(root, project, path):
            issues.append(f"live_writer_supplemental_source_not_allowlisted:{index}")
    expected_writer_template = (root / "agent_templates" / "writer.md").resolve()
    if writer_private != [expected_writer_template]:
        issues.append("live_writer_writer_template_must_be_canonical")
    writer_manifest: dict[str, Any] = {}
    writer_source_plan_path: Path | None = None
    if writer_manifest_path is not None:
        writer_manifest = _decode_mapping(
            writer_manifest_path.read_bytes(),
            "live_writer_input_manifest",
            issues,
        )
        writer_source_plan_path = _verified_ref(
            root,
            project,
            writer_manifest.get("source_plan"),
            "writer_input_manifest_source_plan",
            issues,
            project_scoped=True,
        )
        _validate_writer_input_manifest(
            root,
            writer_manifest,
            request,
            project,
            int(chapter_id or 0),
            brief_source,
            writer_source_plan_path,
            issues,
        )
    if brief_source is not None:
        _validate_path_chapter(
            root,
            brief_source,
            int(chapter_id or 0),
            "creative_brief_source",
            issues,
        )
    if predecessor is not None:
        _validate_path_chapter(
            root,
            predecessor,
            int(predecessor_chapter or 0),
            "predecessor_prose",
            issues,
        )
    if hard_state is not None and predecessor is not None:
        if hard_state.parent != predecessor.parent:
            issues.append("live_writer_hard_state_not_bound_to_predecessor_run")
        _validate_path_chapter(
            root,
            hard_state,
            int(predecessor_chapter or 0),
            "hard_state",
            issues,
        )
    if literary_memory is not None:
        _validate_path_chapter(
            root,
            literary_memory,
            int(chapter_id or 0),
            "literary_memory",
            issues,
        )

    memory_sha256 = ""
    memory_dependencies: dict[Path, str] = {}
    if literary_memory is not None:
        memory_validation = validate_literary_memory_snapshot(
            project_id=project,
            chapter_id=int(chapter_id or 0),
            snapshot_path=literary_memory,
            source_root=root,
        )
        memory_sha256 = memory_validation.snapshot_sha256
        if memory_validation.status != "pass":
            issues.extend(f"live_writer_{issue}" for issue in memory_validation.issues)
        else:
            memory_dependencies = {
                (root / relative).resolve(): digest
                for relative, digest in memory_validation.dependency_hashes.items()
            }
    brief = None
    if brief_source is not None:
        brief_data = _decode_mapping(
            brief_source.read_bytes(),
            "live_writer_creative_brief_source",
            issues,
        )
        if brief_data and brief_data.get("chapter") != chapter_id:
            issues.append("live_writer_creative_brief_chapter_mismatch")
        if brief_data and not issues:
            try:
                brief = BriefCompiler.from_v1_state_plan(
                    brief_data,
                    chapter_id=int(chapter_id),
                    source_paths=[str(brief_source)],
                )
            except (OSError, TypeError, ValueError) as exc:
                issues.append(
                    f"live_writer_creative_brief_invalid:{type(exc).__name__}"
                )
    if issues:
        return _blocked_live_writer_preflight(run_dir, task_id, issues)

    reference_snapshots = _reference_snapshots(
        request=request,
        paths={
            "writer_input_manifest": writer_manifest_path,
            "creative_brief_source": brief_source,
            "canon_snapshot": canon,
            "hard_state": hard_state,
            "predecessor_prose": predecessor,
            "literary_memory": literary_memory,
        },
        list_paths={
            "supplemental_context_sources": supplemental,
            "writer_private_sources": writer_private,
        },
        extra_paths=memory_dependencies,
        extra_references=(
            [
                _ReferenceSnapshot(
                    "writer_input_manifest_source_plan",
                    writer_source_plan_path,
                    _normalized_ref(writer_manifest.get("source_plan"))[1],
                )
            ]
            if writer_source_plan_path is not None
            and _normalized_ref(writer_manifest.get("source_plan")) is not None
            else []
        ),
    )

    candidate_root = (root / "projects" / project / "candidates").resolve()
    output_dir = candidate_root / "live_writer_context" / task_id
    if _has_symlink_component(root, output_dir):
        return _blocked_live_writer_preflight(
            run_dir,
            task_id,
            ["live_writer_context_output_symlink_forbidden"],
        )
    optional_context = _dedupe_paths([literary_memory, *supplemental])
    preview = build_writer_packet_preview(
        ContextRequest(
            chapter_id=int(chapter_id),
            creative_brief=brief,
            canon_snapshot_path=canon,
            hard_state_path=hard_state,
            predecessor_prose_path=predecessor,
            predecessor_chapter_id=int(predecessor_chapter),
            predecessor_prose_sha256=hashlib.sha256(predecessor.read_bytes()).hexdigest(),
            voice_memory_paths=optional_context,
            role_slices={"Writer": writer_private},
            output_dir=output_dir,
            source_root=root,
        ),
        project=project,
        task_id=task_id,
    )
    if preview.status != "pass" or preview.payload is None:
        return _blocked_live_writer_preflight(
            run_dir,
            task_id,
            [f"live_writer_packet_blocked:{issue}" for issue in preview.issues],
        )

    changed_issues = _changed_reference_issues(reference_snapshots)
    if changed_issues:
        return _blocked_live_writer_preflight(
            run_dir,
            task_id,
            changed_issues,
        )

    messages = _live_messages(preview.payload, project, task_id)
    packet = copy.deepcopy(preview.payload)
    packet["messages"] = messages
    packet_json = json.dumps(
        packet,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    packet_sha256 = hashlib.sha256(packet_json.encode("utf-8")).hexdigest()
    context_manifest = Path(preview.context_manifest_path).resolve()
    try:
        current_request_sha256 = hashlib.sha256(request_path.read_bytes()).hexdigest()
    except FileNotFoundError:
        return _blocked_live_writer_preflight(
            run_dir,
            task_id,
            ["live_writer_request_missing_during_compile"],
        )
    except OSError:
        return _blocked_live_writer_preflight(
            run_dir,
            task_id,
            ["live_writer_request_unreadable_during_compile"],
        )
    if current_request_sha256 != request_sha256:
        return _blocked_live_writer_preflight(
            run_dir,
            task_id,
            ["live_writer_request_changed_during_compile"],
        )
    try:
        current_context_manifest_sha256 = hashlib.sha256(
            context_manifest.read_bytes()
        ).hexdigest()
    except FileNotFoundError:
        return _blocked_live_writer_preflight(
            run_dir,
            task_id,
            ["live_writer_context_manifest_missing_during_compile"],
        )
    except OSError:
        return _blocked_live_writer_preflight(
            run_dir,
            task_id,
            ["live_writer_context_manifest_unreadable_during_compile"],
        )
    if current_context_manifest_sha256 != preview.context_manifest_sha256:
        return _blocked_live_writer_preflight(
            run_dir,
            task_id,
            ["live_writer_context_manifest_changed_during_compile"],
        )
    source_paths = _context_source_paths(root, context_manifest, issues)
    if issues:
        return _blocked_live_writer_preflight(run_dir, task_id, issues)
    source_paths = _dedupe_paths([request_path, context_manifest, *source_paths])
    receipt = {
        "schema_version": 1,
        "status": "pass",
        "job_kind": "narrative_generation",
        "run_mode": "generate_candidate",
        "project": project,
        "task_id": task_id,
        "chapter_id": chapter_id,
        "candidate_only": True,
        "production_modified": False,
        "external_context_approval_required": True,
        "provider_calls": 0,
        "request_sha256": request_sha256,
        "compiled_packet_sha256": packet_sha256,
        "compiled_packet_bytes": len(packet_json.encode("utf-8")),
        "token_estimate": (len(packet_json.encode("utf-8")) + 3) // 4,
        "loaded_file_count": preview.loaded_file_count,
        "loaded_context_bytes": preview.loaded_context_bytes,
        "duplicate_context_ratio": preview.duplicate_context_ratio,
        "context_bundle_id": preview.context_bundle_id,
        "context_manifest_sha256": preview.context_manifest_sha256,
        "literary_memory_sha256": memory_sha256,
        "source_inventory": [
            {
                "path": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path in source_paths
        ],
    }
    atomic_write_yaml(receipt_path, receipt, sort_keys=False, allow_unicode=True)
    return LiveWriterSession(
        status="pass",
        messages=messages,
        source_paths=source_paths,
        packet_sha256=packet_sha256,
        packet_bytes=len(packet_json.encode("utf-8")),
        token_estimate=(len(packet_json.encode("utf-8")) + 3) // 4,
        loaded_file_count=preview.loaded_file_count,
        loaded_context_bytes=preview.loaded_context_bytes,
        duplicate_context_ratio=preview.duplicate_context_ratio,
        context_bundle_id=preview.context_bundle_id,
        context_manifest_path=str(context_manifest),
        context_manifest_sha256=preview.context_manifest_sha256,
        literary_memory_sha256=memory_sha256,
        receipt_path=str(receipt_path),
    )


def materialize_live_writer_result(
    result: Any,
    run_dir: Path,
    task_id: str,
) -> dict[str, Any]:
    """Materialize the one prose envelope and persist a content-free contract."""
    from agent_runtime.writer_output_materializer import materialize_writer_v2_content

    run_dir = Path(run_dir)
    issues: list[str] = []
    if getattr(result, "status", None) != "completed":
        issues.append("live_writer_result_not_completed")
    else:
        issues.extend(_validate_delivery_session(run_dir, task_id))
    if issues:
        _remove_delivery_success_outputs(run_dir)
        validation = {
            "status": "blocked",
            "issues": list(dict.fromkeys(issues)),
            "prose_sha256": "",
            "non_prose_output_count": 0,
            "writer_self_receipt_present": False,
        }
    else:
        raw_usage = getattr(result, "raw_usage", None)
        usage = raw_usage if isinstance(raw_usage, dict) else {}
        validation = materialize_writer_v2_content(
            str(getattr(result, "content", "") or ""),
            run_dir,
            task_id,
            provider=str(getattr(result, "provider", "") or ""),
            model=str(getattr(result, "model", "") or ""),
            call_id=str(
                usage.get("provider_session_id")
                or usage.get("session_id")
                or usage.get("command_id")
                or ""
            ),
        )
    _persist_live_writer_output_contract(run_dir, task_id, validation)
    return validation


def _persist_live_writer_output_contract(
    run_dir: Path,
    task_id: str,
    validation: dict[str, Any],
) -> None:
    contract = {
        "schema_version": 1,
        "status": validation.get("status"),
        "task_id": task_id,
        "candidate_only": True,
        "production_modified": False,
        "issues": list(validation.get("issues") or []),
        "prose_sha256": str(validation.get("prose_sha256") or ""),
        "non_prose_output_count": int(
            validation.get("non_prose_output_count") or 0
        ),
        "writer_self_receipt_present": bool(
            validation.get("writer_self_receipt_present")
        ),
        "writer_execution_receipt": (
            "writer_execution_receipt.yml"
            if validation.get("status") == "pass"
            else None
        ),
    }
    atomic_write_yaml(
        run_dir / LIVE_WRITER_OUTPUT_CONTRACT_NAME,
        contract,
        sort_keys=False,
        allow_unicode=True,
    )


def _blocked_live_writer_preflight(
    run_dir: Path,
    task_id: str,
    issues: list[str],
) -> LiveWriterSession:
    normalized_issues = list(dict.fromkeys(str(issue) for issue in issues if issue))
    if not normalized_issues:
        normalized_issues = ["live_writer_preflight_blocked"]
    _remove_delivery_success_outputs(run_dir)
    _persist_live_writer_output_contract(
        run_dir,
        task_id,
        {
            "status": "blocked",
            "issues": normalized_issues,
            "prose_sha256": "",
            "non_prose_output_count": 0,
            "writer_self_receipt_present": False,
        },
    )
    return LiveWriterSession(status="blocked", issues=normalized_issues)


def materialize_registered_writer_result(
    result: Any,
    run_dir: Path,
    task_id: str,
    *,
    capture_name: str = "writer_role_session_capture.md",
) -> dict[str, Any]:
    """Select the v2 or legacy Writer materializer from run-local identity."""
    run_dir = Path(run_dir)
    request_path = run_dir / LIVE_WRITER_REQUEST_NAME
    if request_path.is_file() or request_path.is_symlink():
        validation = materialize_live_writer_result(result, run_dir, task_id)
        contract_path = run_dir / LIVE_WRITER_OUTPUT_CONTRACT_NAME
    else:
        from agent_runtime.writer_output_materializer import (
            REQUIRED_WRITER_OUTPUTS,
            materialize_writer_candidate_result,
        )

        passed = materialize_writer_candidate_result(
            result,
            run_dir,
            task_id,
            capture_name=capture_name,
        )
        contract_path = run_dir / "writer_output_contract.yml"
        contract = (
            _decode_mapping(
                contract_path.read_bytes(),
                "writer_output_contract",
                [],
            )
            if contract_path.is_file()
            else {}
        )
        if not passed:
            issues = list(contract.get("issues") or [])
            if not issues:
                issues = [
                    "writer_result_not_completed"
                    if getattr(result, "status", None) != "completed"
                    else "writer_result_empty"
                ]
            contract = {
                **contract,
                "schema_version": 1,
                "status": "blocked",
                "task_id": task_id,
                "capture_path": capture_name,
                "required_outputs": list(REQUIRED_WRITER_OUTPUTS),
                "materialized_outputs": [],
                "candidate_only": True,
                "harness_generated_story_state": False,
                "issues": issues,
            }
            atomic_write_yaml(
                contract_path,
                contract,
                sort_keys=False,
                allow_unicode=True,
            )
            for name in REQUIRED_WRITER_OUTPUTS:
                candidate_path = run_dir / name
                if candidate_path.is_file() or candidate_path.is_symlink():
                    candidate_path.unlink()
        validation = {
            "status": "pass" if passed else "blocked",
            "issues": list(contract.get("issues") or []),
        }
    passed = validation.get("status") == "pass"
    output_path = run_dir / "fiction_draft.md" if passed else contract_path
    output_content = (
        output_path.read_text(encoding="utf-8", errors="replace")
        if output_path.is_file()
        else str(getattr(result, "content", "") or "")
    )
    return {
        **validation,
        "contract_path": str(contract_path),
        "output_path": str(output_path),
        "output_content": output_content,
    }


def _validate_delivery_session(run_dir: Path, task_id: str) -> list[str]:
    request_path = run_dir / LIVE_WRITER_REQUEST_NAME
    receipt_path = run_dir / LIVE_WRITER_RECEIPT_NAME
    if request_path.is_symlink() or receipt_path.is_symlink():
        return ["live_writer_session_binding_symlinked"]
    try:
        request_raw = request_path.read_bytes()
        request = yaml.safe_load(request_raw.decode("utf-8")) or {}
        receipt = yaml.safe_load(receipt_path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return ["live_writer_session_binding_missing_or_invalid"]
    if not isinstance(request, dict) or not isinstance(receipt, dict):
        return ["live_writer_session_binding_missing_or_invalid"]
    if receipt.get("request_sha256") != hashlib.sha256(request_raw).hexdigest():
        return ["live_writer_session_request_hash_mismatch"]
    expected = {
        "schema_version": 1,
        "job_kind": "narrative_generation",
        "run_mode": "generate_candidate",
        "task_id": task_id,
        "candidate_only": True,
        "production_modified": False,
        "external_context_approval_required": True,
    }
    for key, value in expected.items():
        if request.get(key) != value or receipt.get(key) != value:
            return [f"live_writer_session_binding_mismatch:{key}"]
    if receipt.get("status") != "pass":
        return ["live_writer_session_receipt_not_pass"]
    if request.get("project") != receipt.get("project"):
        return ["live_writer_session_binding_mismatch:project"]
    if request.get("chapter_id") != receipt.get("chapter_id"):
        return ["live_writer_session_binding_mismatch:chapter_id"]
    if not _SHA256_RE.fullmatch(str(receipt.get("compiled_packet_sha256") or "")):
        return ["live_writer_session_packet_hash_invalid"]
    return []


def _remove_delivery_success_outputs(run_dir: Path) -> None:
    for name in ("fiction_draft.md", "writer_execution_receipt.yml"):
        path = run_dir / name
        try:
            if path.exists() or path.is_symlink():
                path.unlink()
        except OSError:
            pass


def _validate_identity(
    request: dict[str, Any], project: str, task_id: str, issues: list[str]
) -> None:
    expected = {
        "schema_version": 1,
        "job_kind": "narrative_generation",
        "run_mode": "generate_candidate",
        "project": project,
        "task_id": task_id,
        "candidate_only": True,
        "production_modified": False,
        "external_context_approval_required": True,
    }
    for key, value in expected.items():
        if request.get(key) != value:
            issues.append(f"live_writer_identity_mismatch:{key}")


def _validate_writer_input_manifest(
    root: Path,
    manifest: dict[str, Any],
    request: dict[str, Any],
    project: str,
    chapter_id: int,
    brief_source: Path | None,
    source_plan_path: Path | None,
    issues: list[str],
) -> None:
    expected = {
        "schema_version": 2,
        "project": project,
        "candidate_only": True,
        "production_modified": False,
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            issues.append(f"live_writer_input_manifest_mismatch:{key}")
    chapters = manifest.get("chapters")
    if not isinstance(chapters, list) or chapter_id not in chapters:
        issues.append("live_writer_input_manifest_chapter_missing")
    for key in ("canon_snapshot",):
        if _normalized_ref(manifest.get(key)) != _normalized_ref(request.get(key)):
            issues.append(f"live_writer_manifest_reference_mismatch:{key}")
    derived_relative = Path(str(manifest.get("derived_candidate_dir") or ""))
    candidate_root = (root / "projects" / project / "candidates").resolve()
    if (
        not str(derived_relative)
        or derived_relative.is_absolute()
        or ".." in derived_relative.parts
        or _has_symlink_component(root, root / derived_relative)
    ):
        issues.append("live_writer_input_manifest_derived_dir_invalid")
        derived_dir = None
    else:
        derived_dir = (root / derived_relative).resolve()
        try:
            derived_dir.relative_to(candidate_root)
        except ValueError:
            issues.append("live_writer_input_manifest_derived_dir_invalid")
            derived_dir = None
    expected_brief = (
        derived_dir / f"creative_brief_source_ch{chapter_id:03d}.yml"
        if derived_dir is not None
        else None
    )
    if brief_source is None or expected_brief is None or brief_source != expected_brief:
        issues.append("live_writer_manifest_reference_mismatch:creative_brief_source")
    if source_plan_path is not None:
        source_plan = _decode_mapping(
            source_plan_path.read_bytes(),
            "live_writer_input_manifest_source_plan",
            issues,
        )
        rows = [
            row
            for row in source_plan.get("chapter_state_plan") or []
            if isinstance(row, dict) and row.get("chapter") == chapter_id
        ]
        if len(rows) != 1:
            issues.append("live_writer_input_manifest_source_plan_chapter_invalid")
        else:
            projected = copy.deepcopy(rows[0])
            for key in ("target_character_range", "hard_character_range"):
                if source_plan.get(key) is not None:
                    projected[key] = copy.deepcopy(source_plan[key])
            expected_hash = hashlib.sha256(
                yaml.safe_dump(
                    projected,
                    sort_keys=False,
                    allow_unicode=True,
                ).encode("utf-8")
            ).hexdigest()
            creative_ref = _normalized_ref(request.get("creative_brief_source"))
            if creative_ref is None or creative_ref[1] != expected_hash:
                issues.append(
                    "live_writer_manifest_reference_mismatch:creative_brief_source"
                )
    for key in ("shared_memory_sources", "writer_private_sources"):
        request_key = (
            "supplemental_context_sources"
            if key == "shared_memory_sources"
            else key
        )
        if _normalized_ref_list(manifest.get(key)) != _normalized_ref_list(
            request.get(request_key)
        ):
            issues.append(f"live_writer_manifest_reference_mismatch:{request_key}")
    chapter_rows = [
        row
        for row in manifest.get("chapter_inputs") or []
        if isinstance(row, dict) and row.get("chapter_id") == chapter_id
    ]
    if len(chapter_rows) != 1:
        issues.append("live_writer_input_manifest_chapter_input_invalid")
        return
    for key in ("hard_state", "predecessor_prose"):
        if _normalized_ref(chapter_rows[0].get(key)) != _normalized_ref(
            request.get(key)
        ):
            issues.append(f"live_writer_manifest_reference_mismatch:{key}")


def _normalized_ref(raw: Any) -> tuple[str, str] | None:
    if not isinstance(raw, dict):
        return None
    return (
        str(raw.get("path") or "").strip(),
        str(raw.get("sha256") or "").strip().lower(),
    )


def _normalized_ref_list(raw: Any) -> list[tuple[str, str] | None] | None:
    if not isinstance(raw, list):
        return None
    return [_normalized_ref(item) for item in raw]


def _reference_snapshots(
    *,
    request: dict[str, Any],
    paths: dict[str, Path | None],
    list_paths: dict[str, list[Path]],
    extra_paths: dict[Path, str],
    extra_references: list[_ReferenceSnapshot],
) -> list[_ReferenceSnapshot]:
    result: list[_ReferenceSnapshot] = []
    for name, path in paths.items():
        normalized = _normalized_ref(request.get(name))
        if path is not None and normalized is not None:
            result.append(_ReferenceSnapshot(name, path, normalized[1]))
    for name, resolved_paths in list_paths.items():
        raw_refs = request.get(name) if isinstance(request.get(name), list) else []
        for index, (path, raw_ref) in enumerate(zip(resolved_paths, raw_refs)):
            normalized = _normalized_ref(raw_ref)
            if normalized is not None:
                result.append(
                    _ReferenceSnapshot(f"{name}:{index}", path, normalized[1])
                )
    for index, (path, declared_hash) in enumerate(extra_paths.items()):
        result.append(
            _ReferenceSnapshot(
                f"literary_memory_dependency:{index}",
                path,
                declared_hash,
            )
        )
    result.extend(extra_references)
    return result


def _changed_reference_issues(
    references: list[_ReferenceSnapshot],
) -> list[str]:
    issues: list[str] = []
    for reference in references:
        try:
            current = hashlib.sha256(reference.path.read_bytes()).hexdigest()
        except OSError:
            current = ""
        if current != reference.sha256:
            issues.append(
                f"live_writer_reference_changed_during_compile:{reference.name}"
            )
    return list(dict.fromkeys(issues))


def _bound_plan_path(
    root: Path,
    raw_path: Any,
    expected: Path,
    issue: str,
    issues: list[str],
) -> Path | None:
    try:
        lexical = Path(raw_path)
    except (OSError, TypeError, ValueError):
        issues.append(issue)
        return None
    if not lexical.is_absolute():
        lexical = root / lexical
    if _has_symlink_component(root, lexical):
        issues.append(issue)
        return None
    try:
        resolved = lexical.resolve()
        resolved.relative_to(root)
    except (OSError, ValueError):
        issues.append(issue)
        return None
    if resolved != expected.resolve():
        issues.append(issue)
        return None
    return resolved


def _verified_ref(
    root: Path,
    project: str,
    raw_ref: Any,
    name: str,
    issues: list[str],
    *,
    project_scoped: bool,
    required_project_area: str | None = None,
    allowed_prefix: Path | None = None,
) -> Path | None:
    if not isinstance(raw_ref, dict):
        issues.append(f"live_writer_reference_invalid:{name}")
        return None
    raw_path = str(raw_ref.get("path") or "").strip()
    declared_hash = str(raw_ref.get("sha256") or "").strip().lower()
    relative = Path(raw_path)
    if not raw_path or relative.is_absolute() or ".." in relative.parts:
        issues.append(f"live_writer_reference_path_invalid:{name}")
        return None
    if not _SHA256_RE.fullmatch(declared_hash):
        issues.append(f"live_writer_reference_sha256_invalid:{name}")
        return None
    lexical = root / relative
    if _has_symlink_component(root, lexical):
        issues.append(f"live_writer_reference_symlink_forbidden:{name}")
        return None
    try:
        path = lexical.resolve()
        canonical = path.relative_to(root)
    except (OSError, ValueError):
        issues.append(f"live_writer_reference_outside_root:{name}")
        return None
    project_prefix = Path("projects") / project
    if project_scoped:
        try:
            project_relative = canonical.relative_to(project_prefix)
        except ValueError:
            issues.append(f"live_writer_reference_outside_project:{name}")
            return None
        if required_project_area and (
            not project_relative.parts
            or project_relative.parts[0] != required_project_area
        ):
            issues.append(f"live_writer_reference_wrong_project_area:{name}")
            return None
    elif allowed_prefix is not None:
        try:
            canonical.relative_to(allowed_prefix)
        except ValueError:
            issues.append(f"live_writer_reference_not_allowlisted:{name}")
            return None
    if not path.is_file():
        issues.append(f"live_writer_reference_missing:{name}")
        return None
    if hashlib.sha256(path.read_bytes()).hexdigest() != declared_hash:
        issues.append(f"live_writer_reference_hash_mismatch:{name}")
        return None
    return path


def _verified_ref_list(
    root: Path,
    project: str,
    raw_refs: Any,
    name: str,
    issues: list[str],
    *,
    max_count: int,
    max_bytes: int,
    project_scoped: bool,
    allowed_prefix: Path | None = None,
) -> list[Path]:
    if not isinstance(raw_refs, list):
        issues.append(f"live_writer_reference_list_invalid:{name}")
        return []
    if len(raw_refs) > max_count:
        issues.append(f"live_writer_reference_count_exceeded:{name}")
        return []
    paths = [
        path
        for index, ref in enumerate(raw_refs)
        if (
            path := _verified_ref(
                root,
                project,
                ref,
                f"{name}:{index}",
                issues,
                project_scoped=project_scoped,
                allowed_prefix=allowed_prefix,
            )
        )
        is not None
    ]
    if sum(path.stat().st_size for path in paths) > max_bytes:
        issues.append(f"live_writer_reference_bytes_exceeded:{name}")
    return paths


def _validate_path_chapter(
    root: Path,
    path: Path,
    expected: int,
    name: str,
    issues: list[str],
) -> None:
    try:
        relative = path.relative_to(root)
    except ValueError:
        issues.append(f"live_writer_source_chapter_unverifiable:{name}")
        return
    observed = {
        int(match)
        for part in relative.parts
        for match in _CHAPTER_RE.findall(part)
    }
    if len(observed) != 1:
        issues.append(f"live_writer_source_chapter_unverifiable:{name}")
    elif next(iter(observed)) != expected:
        issues.append(f"live_writer_source_chapter_mismatch:{name}")


def _supplemental_source_is_allowlisted(
    root: Path,
    project: str,
    path: Path,
) -> bool:
    project_root = root / "projects" / project
    allowed_file = (project_root / "project_brain" / "project_fact_snapshot.yml").resolve()
    if path == allowed_file:
        return True
    bible_root = (project_root / "production" / "bible").resolve()
    try:
        path.relative_to(bible_root)
    except ValueError:
        return False
    return True


def _live_messages(
    payload: dict[str, Any], project: str, task_id: str
) -> list[dict[str, str]]:
    messages = copy.deepcopy(payload.get("messages") or [])
    target = f"runs/{task_id}/fiction_draft.md"
    messages[0]["content"] = (
        "Act only as the prose Writer for this chapter. Preserve the sealed "
        "CreativeBrief, canon, state, and literary memory. Return exactly one "
        f"full-file AGENTLAB_EDIT block targeting {target}. The block body must "
        "contain only the complete chapter prose. Do not emit any other file, "
        "report, audit, state ledger, receipt, promotion decision, or commentary."
    )
    messages[1]["content"] = (
        f"Project: {project}\nTask: {task_id}\nRequired target: {target}\n\n"
        + messages[1]["content"]
    )
    return messages


def _context_source_paths(
    root: Path, manifest_path: Path, issues: list[str]
) -> list[Path]:
    try:
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        issues.append("live_writer_context_manifest_unreadable")
        return []
    paths: list[Path] = []
    records = list(manifest.get("shared_files") or [])
    records.extend((manifest.get("role_specific_files") or {}).get("Writer") or [])
    for record in records:
        if not isinstance(record, dict):
            issues.append("live_writer_context_manifest_record_invalid")
            continue
        path = _verified_ref(
            root,
            "",
            record,
            "context_manifest_source",
            issues,
            project_scoped=False,
        )
        if path is not None:
            paths.append(path)
    return paths


def _read_bounded(
    path: Path, limit: int, prefix: str, issues: list[str]
) -> bytes:
    try:
        with path.open("rb") as handle:
            raw = handle.read(limit + 1)
    except OSError:
        issues.append(f"{prefix}_unreadable")
        return b""
    if len(raw) > limit:
        issues.append(f"{prefix}_size_limit_exceeded")
        return b""
    if not raw:
        issues.append(f"{prefix}_empty")
    return raw


def _decode_mapping(raw: bytes, prefix: str, issues: list[str]) -> dict[str, Any]:
    try:
        value = yaml.safe_load(raw.decode("utf-8")) or {}
    except (UnicodeDecodeError, yaml.YAMLError):
        issues.append(f"{prefix}_yaml_invalid")
        return {}
    if not isinstance(value, dict):
        issues.append(f"{prefix}_root_must_be_mapping")
        return {}
    return value


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


def _remove_stale_receipt(path: Path) -> None:
    try:
        if path.exists() or path.is_symlink():
            path.unlink()
    except OSError:
        pass


def _dedupe_paths(paths: list[Path | None]) -> list[Path]:
    result: list[Path] = []
    seen: set[Path] = set()
    for raw_path in paths:
        if raw_path is None:
            continue
        path = raw_path.resolve()
        if path not in seen:
            seen.add(path)
            result.append(path)
    return result


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0
