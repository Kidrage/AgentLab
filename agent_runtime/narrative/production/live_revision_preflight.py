"""Provider-free publication of one hash-bound live Writer revision attempt."""

from __future__ import annotations

import argparse
import copy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Any

import yaml

from agent_runtime.atomic_io import atomic_write_text
from agent_runtime.narrative.production.live_writer import (
    LIVE_WRITER_REQUEST_NAME,
    prepare_live_writer_session,
)
from agent_runtime.narrative.production.live_revision import (
    revision_contract_issues,
)
from agent_runtime.narrative.production.live_writer_preflight import (
    _PREFLIGHT_NOTE_PREFIX,
    _has_symlink_component,
    _publish_batch_activation,
    _publish_operator_plans,
    _publish_text_exclusive,
    _safe_run_dir,
    _tree_digest,
    _validate_operator_slot,
    _verified_ref,
    load_validated_workflow_plan_data,
)
from agent_runtime.narrative.production.revision_attempts import (
    reserve_revision_attempt,
)
from agent_runtime.schemas import AgentRoute, WorkflowPlan


_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_CONTEXT_FIELDS = (
    "writer_input_manifest",
    "creative_brief_source",
    "canon_snapshot",
    "hard_state",
    "predecessor_prose",
    "literary_memory",
    "supplemental_context_sources",
    "writer_private_sources",
)


def preflight_live_writer_revision(
    spec_path: Path,
    *,
    repository_root: Path,
) -> dict[str, Any]:
    """Publish one inert-until-activated revision plan without calling a provider."""
    root = Path(repository_root).resolve()
    spec_path = _safe_spec_path(root, spec_path)
    spec_raw = spec_path.read_bytes()
    spec = _mapping(spec_raw, "live_revision_spec_invalid")
    spec_sha256 = hashlib.sha256(spec_raw).hexdigest()
    if spec.get("candidate_only") is not True:
        raise ValueError("live_revision_must_be_candidate_only")

    identifiers = {
        key: str(spec.get(key) or "").strip()
        for key in (
            "project",
            "task_id",
            "candidate_set_id",
            "source_job_id",
            "source_run_id",
            "triggered_by_audit_id",
            "attempt_id",
            "lease_token",
        )
    }
    for key, value in identifiers.items():
        if not _IDENTIFIER_RE.fullmatch(value):
            raise ValueError(f"live_revision_{key}_invalid")
    project = identifiers["project"]
    task_id = identifiers["task_id"]
    source_run_id = identifiers["source_run_id"]
    audit_id = identifiers["triggered_by_audit_id"]
    if task_id == source_run_id:
        raise ValueError("live_revision_must_use_distinct_run")
    if audit_id == source_run_id:
        raise ValueError("live_revision_audit_must_use_distinct_run")
    try:
        chapter_id = int(spec.get("chapter_id"))
    except (TypeError, ValueError) as exc:
        raise ValueError("live_revision_chapter_id_invalid") from exc
    if chapter_id < 1:
        raise ValueError("live_revision_chapter_id_invalid")
    rewrite_count = spec.get("automatic_rewrite_count")
    if isinstance(rewrite_count, bool) or rewrite_count not in (0, 1):
        raise ValueError("live_revision_automatic_rewrite_limit_reached")
    lease_expires_at = str(spec.get("lease_expires_at") or "").strip()
    try:
        lease_expiry = datetime.fromisoformat(lease_expires_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("live_revision_lease_expiry_invalid") from exc
    if lease_expiry.tzinfo is None:
        raise ValueError("live_revision_lease_expiry_invalid")
    if lease_expiry <= datetime.now(lease_expiry.tzinfo):
        raise ValueError("live_revision_lease_expired")

    source_request_path = _verified_ref(root, spec.get("source_writer_request"))
    source_candidate = _verified_ref(root, spec.get("source_candidate"))
    triggering_audit = _verified_ref(root, spec.get("triggering_audit"))
    revision_contract = _verified_ref(root, spec.get("revision_contract"))
    source_run = root / "projects" / project / "runs" / source_run_id
    audit_run = root / "projects" / project / "runs" / audit_id
    expected_paths = {
        source_request_path: source_run / LIVE_WRITER_REQUEST_NAME,
        source_candidate: source_run / "fiction_draft.md",
        triggering_audit: audit_run / "deterministic_candidate_audit_v2.yml",
    }
    for observed, expected in expected_paths.items():
        if observed != expected.resolve():
            raise ValueError("live_revision_source_lineage_path_mismatch")
    candidate_root = (root / "projects" / project / "candidates").resolve()
    try:
        revision_contract.relative_to(candidate_root)
    except ValueError as exc:
        raise ValueError("live_revision_contract_outside_candidates") from exc

    source_request_raw = source_request_path.read_bytes()
    source_request = _mapping(
        source_request_raw,
        "live_revision_source_request_invalid",
    )
    if (
        source_request.get("job_kind") != "narrative_generation"
        or source_request.get("run_mode") != "generate_candidate"
        or source_request.get("project") != project
        or source_request.get("task_id") != source_run_id
        or source_request.get("chapter_id") != chapter_id
        or source_request.get("candidate_only") is not True
        or source_request.get("production_modified") is not False
    ):
        raise ValueError("live_revision_source_request_identity_mismatch")
    source_plan = load_validated_workflow_plan_data(
        agentlab_root=root,
        project=project,
        task_id=source_run_id,
        plan_path=source_run / "workflow_plan.yml",
    )
    if str(source_plan.get("sealed_user_request_content") or "").encode(
        "utf-8"
    ) != source_request_raw:
        raise ValueError("live_revision_source_request_not_activated")

    source_candidate_sha256 = hashlib.sha256(source_candidate.read_bytes()).hexdigest()
    audit_sha256 = hashlib.sha256(triggering_audit.read_bytes()).hexdigest()
    source_output_contract = _mapping(
        (source_run / "writer_v2_output_contract.yml").read_bytes(),
        "live_revision_source_output_contract_invalid",
    )
    if (
        source_output_contract.get("status") != "pass"
        or source_output_contract.get("task_id") != source_run_id
        or source_output_contract.get("prose_sha256") != source_candidate_sha256
        or source_output_contract.get("candidate_only") is not True
        or source_output_contract.get("production_modified") is not False
    ):
        raise ValueError("live_revision_source_output_contract_mismatch")
    audit = _mapping(triggering_audit.read_bytes(), "live_revision_audit_invalid")
    if (
        audit.get("schema_version") != 1
        or audit.get("contract_version") != 2
        or audit.get("project") != project
        or not str(audit.get("report_type") or "").strip()
        or audit.get("task_id") != source_run_id
        or audit.get("status") not in {"fail", "blocked"}
        or not isinstance(audit.get("issues"), list)
        or not audit.get("issues")
    ):
        raise ValueError("live_revision_audit_not_actionable")
    if audit.get("candidate_sha256") != source_candidate_sha256:
        raise ValueError("live_revision_audit_source_hash_mismatch")
    contract = _mapping(
        revision_contract.read_bytes(),
        "live_revision_contract_invalid",
    )
    contract_issues = revision_contract_issues(
        contract,
        chapter_id=chapter_id,
        source_candidate_sha256=source_candidate_sha256,
        triggering_audit_sha256=audit_sha256,
        prefix="live_revision",
    )
    if contract_issues:
        raise ValueError(contract_issues[0])

    reservation = reserve_revision_attempt(
        root=root,
        project=project,
        candidate_set_id=identifiers["candidate_set_id"],
        source_job_id=identifiers["source_job_id"],
        source_run_id=source_run_id,
        triggered_by_audit_id=identifiers["triggered_by_audit_id"],
        task_id=task_id,
        attempt_id=identifiers["attempt_id"],
        lease_token=identifiers["lease_token"],
        lease_expires_at=lease_expires_at,
        preflight_spec_sha256=spec_sha256,
        claimed_rewrite_count=rewrite_count,
        source_candidate_sha256=source_candidate_sha256,
        triggering_audit_sha256=audit_sha256,
        revision_contract_sha256=hashlib.sha256(
            revision_contract.read_bytes()
        ).hexdigest(),
    )

    project_root = root / "projects" / project
    production_root = project_root / "production"
    production_before = _tree_digest(production_root)
    source_before = _tree_digest(source_run)
    run_dir = _safe_run_dir(root, project, task_id)
    run_stat = run_dir.stat(follow_symlinks=False)
    run_identity = (run_stat.st_dev, run_stat.st_ino)
    request = {
        "schema_version": 1,
        "job_kind": "narrative_revision",
        "run_mode": "targeted_rewrite",
        "project": project,
        "task_id": task_id,
        "chapter_id": chapter_id,
        "candidate_only": True,
        "production_modified": False,
        "external_context_approval_required": True,
        **identifiers,
        "lease_expires_at": lease_expires_at,
        "automatic_rewrite_count": reservation.automatic_rewrite_count,
        "automatic_rewrite_number": reservation.automatic_rewrite_number,
        "fencing_token": reservation.fencing_token,
        "attempt_receipt": reservation.reference(root),
        **{key: copy.deepcopy(source_request.get(key)) for key in _CONTEXT_FIELDS},
        "source_writer_request": _portable_ref(root, source_request_path),
        "source_candidate": _portable_ref(root, source_candidate),
        "triggering_audit": _portable_ref(root, triggering_audit),
        "revision_contract": _portable_ref(root, revision_contract),
    }
    request_path = run_dir / LIVE_WRITER_REQUEST_NAME
    plan = WorkflowPlan(
        project=project,
        task_id=task_id,
        agentlab_root=str(root),
        project_root=str(project_root),
        repo_path=str(project_root / "repo"),
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
        notes=[f"{_PREFLIGHT_NOTE_PREFIX}{spec_sha256}"],
    )
    plan_path = run_dir / "workflow_plan.yml"
    request_content = yaml.safe_dump(request, sort_keys=False, allow_unicode=True)
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
        conflict_error="live_revision_existing_request_conflict",
        expected_parent_identity=run_identity,
    )
    session = prepare_live_writer_session(root, plan)
    if session is None or session.status != "pass":
        issues = session.issues if session is not None else ["not_activated"]
        raise ValueError("live_revision_session_blocked:" + ",".join(issues))
    repeated = prepare_live_writer_session(root, plan)
    if repeated is None or repeated.status != "pass":
        issues = repeated.issues if repeated is not None else ["not_activated"]
        raise ValueError("live_revision_repeat_session_blocked:" + ",".join(issues))
    if (
        session.packet_sha256 != repeated.packet_sha256
        or session.packet_bytes != repeated.packet_bytes
        or session.context_manifest_sha256 != repeated.context_manifest_sha256
    ):
        raise ValueError("live_revision_session_not_byte_stable")
    row = {
        "chapter_id": chapter_id,
        "task_id": task_id,
        "request_path": request_path.relative_to(root).as_posix(),
        "request_sha256": hashlib.sha256(request_path.read_bytes()).hexdigest(),
        "workflow_plan_path": plan_path.relative_to(root).as_posix(),
        "workflow_plan_sha256": hashlib.sha256(
            plan_content.encode("utf-8")
        ).hexdigest(),
        "packet_sha256": session.packet_sha256,
        "packet_bytes": session.packet_bytes,
        "token_estimate": session.token_estimate,
        "loaded_file_count": session.loaded_file_count,
        "loaded_context_bytes": session.loaded_context_bytes,
        "duplicate_context_ratio": session.duplicate_context_ratio,
        "context_bundle_id": session.context_bundle_id,
        "context_manifest_sha256": session.context_manifest_sha256,
        "provider_calls": session.provider_calls,
        "activation_bound_references": [
            _portable_ref(root, path)
            for path in (
                source_request_path,
                source_candidate,
                triggering_audit,
                revision_contract,
                reservation.receipt_path,
            )
        ],
        "activation_production_digest": production_before,
    }
    _publish_operator_plans(
        [(plan_path, plan_content, request_path, request_content, run_identity)]
    )
    activation = _publish_batch_activation(
        root=root,
        project=project,
        spec_sha256=spec_sha256,
        rows=[row],
    )
    production_after = _tree_digest(production_root)
    source_after = _tree_digest(source_run)
    if session.provider_calls or production_before != production_after:
        raise ValueError("live_revision_safety_invariant_failed")
    if source_before != source_after:
        raise ValueError("live_revision_source_run_modified")
    load_validated_workflow_plan_data(
        agentlab_root=root,
        project=project,
        task_id=task_id,
        plan_path=plan_path,
    )
    return {
        "schema_version": 1,
        "status": "pass",
        "project": project,
        "task_id": task_id,
        "chapter_id": chapter_id,
        "job_kind": "narrative_revision",
        "run_mode": "targeted_rewrite",
        "candidate_only": True,
        "production_modified": False,
        "source_run_unchanged": True,
        "provider_calls": 0,
        "automatic_rewrite_count": reservation.automatic_rewrite_count,
        "automatic_rewrite_number": reservation.automatic_rewrite_number,
        "fencing_token": reservation.fencing_token,
        "attempt_receipt": reservation.reference(root),
        "row": row,
        "activation_receipt": activation,
    }


def _safe_spec_path(root: Path, spec_path: Path) -> Path:
    lexical = spec_path if spec_path.is_absolute() else root / spec_path
    if _has_symlink_component(root, lexical):
        raise ValueError("live_revision_spec_symlinked")
    try:
        resolved = lexical.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise ValueError("live_revision_spec_outside_root") from exc
    if lexical.is_symlink():
        raise ValueError("live_revision_spec_symlinked")
    return resolved


def _mapping(raw: bytes, issue: str) -> dict[str, Any]:
    try:
        value = yaml.safe_load(raw.decode("utf-8")) or {}
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ValueError(issue) from exc
    if not isinstance(value, dict):
        raise ValueError(issue)
    return value


def _portable_ref(root: Path, path: Path) -> dict[str, str]:
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", type=Path)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = preflight_live_writer_revision(
        args.spec,
        repository_root=args.repository_root,
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        atomic_write_text(args.output, rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by operator use
    raise SystemExit(main())
