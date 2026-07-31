"""Evidence-bound detached acceptance for governed narrative candidates."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping
import hashlib
import re

import yaml

from agent_runtime.atomic_io import atomic_write_yaml
from agent_runtime.narrative.outbound_transfer import acceptance_boundary_issues
from agent_runtime.narrative.production.delta_verifier import verify_state_delta
from agent_runtime.narrative.production.state_projector import (
    StateProjector,
    project_state,
)
from agent_runtime.narrative.state_store import (
    NarrativeStateStore,
    narrative_payload_sha256,
)
from agent_runtime.project_truth import ProjectTruthStore
from agent_runtime.task_runtime_v2 import TaskRuntime
from agent_runtime.task_runtime_v2.narrative_projection_executor import (
    NarrativeProjectionAttemptExecutor,
    TOOL_ID as DETACHED_PROJECTOR_TOOL_ID,
)


_AUTHORITY_KEY = "policies.outbound_context_auto_approval"
_SENIOR_HARD_GATES = frozenset(
    {
        "length",
        "continuity",
        "scene_order",
        "single_anomaly",
        "mark_no_glow",
        "knowledge_boundary",
        "institutional_detail",
        "character_policy",
    }
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _project_file(
    root: Path,
    project_root: Path,
    raw_path: str | Path,
) -> tuple[Path, str]:
    candidate = Path(raw_path)
    candidate = candidate if candidate.is_absolute() else root / candidate
    if candidate.is_symlink():
        raise ValueError("detached acceptance evidence cannot be a symlink")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_file() or not resolved.is_relative_to(project_root):
        raise ValueError("detached acceptance evidence must be a project file")
    return resolved, resolved.relative_to(root).as_posix()


def _authorized_detached_policy(
    root: Path,
    *,
    project: str,
) -> tuple[Path, str]:
    project_root = (root / "projects" / project).resolve(strict=True)
    policy_path = project_root / "production" / "outbound_context_policy.yml"
    if policy_path.is_symlink() or not policy_path.is_file():
        raise ValueError("detached acceptance policy is missing")
    try:
        policy = yaml.safe_load(policy_path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError("detached acceptance policy is invalid") from exc
    if not isinstance(policy, dict):
        raise ValueError("detached acceptance policy must be a mapping")
    authorization = policy.get("authorization")
    authorization = authorization if isinstance(authorization, dict) else {}
    constraints = policy.get("constraints")
    constraints = constraints if isinstance(constraints, dict) else {}
    if (
        policy.get("schema_version") != "narrative-outbound-auto-approval/v1"
        or policy.get("status") != "active"
        or policy.get("project") != project
        or authorization.get("user_responsibility")
        != "final_part_acceptance_only"
        or constraints.get("state_projection_requires_user_acceptance") is not False
        or acceptance_boundary_issues(policy, authorization, constraints)
    ):
        raise ValueError("detached acceptance policy boundary is invalid")
    policy_sha256 = _sha256(policy_path)
    truth = ProjectTruthStore(project_root)
    truth.audit()
    revision = truth.current().resources.get(_AUTHORITY_KEY)
    authority = (
        revision.content
        if revision is not None and isinstance(revision.content, dict)
        else {}
    )
    if (
        revision is None
        or authority.get("schema_version")
        != "narrative-outbound-auto-approval-authority/v1"
        or authority.get("status") != "active"
        or authority.get("project") != project
        or authority.get("policy_path")
        != "production/outbound_context_policy.yml"
        or authority.get("policy_sha256") != policy_sha256
        or revision.actor_id != authority.get("authorized_by")
    ):
        raise ValueError("detached acceptance policy lacks current Project Truth authority")
    return policy_path, policy_sha256


def _load_review(path: Path, *, role: str) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError(f"{role} review is invalid") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{role} review must be a mapping")
    return value


def _attempt_review_output(path: Path) -> dict[str, Any]:
    content = path.read_text(encoding="utf-8")
    matches = re.findall(r"```(?:yaml|yml)\s*(.*?)```", content, flags=re.DOTALL)
    candidates = [*matches, content]
    for candidate in candidates:
        try:
            value = yaml.safe_load(candidate) or {}
        except yaml.YAMLError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("Reviewer Attempt output has no machine-readable review")


def _score_value(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    raw = str(value or "").split("/", 1)[0].strip()
    try:
        return float(raw)
    except ValueError:
        return None


def _validate_review_derivation(
    review: Mapping[str, Any],
    source: Mapping[str, Any],
    *,
    expected_work_item_id: str,
) -> None:
    if source.get("verdict") != review.get("verdict"):
        raise ValueError("normalized review verdict is not in Reviewer output")
    if source.get("remaining_blockers") != review.get("remaining_blockers"):
        raise ValueError("normalized review blockers are not in Reviewer output")
    if review.get("schema_version") == "senior-editor-final-review/v1":
        if source.get("candidate_sha256") != review.get("candidate_sha256"):
            raise ValueError("Senior Editor output does not bind the candidate")
        gates = review.get("gates") or {}
        for gate, status in gates.items():
            if str(source.get(f"{gate}_gate") or "").lower() != str(status).lower():
                raise ValueError("normalized hard gate is not in Senior Editor output")
        return
    if source.get("policy_risks") != review.get("policy_risks"):
        raise ValueError("normalized policy risks are not in Reader output")
    source_score_keys = {
        "clarity": "clarity",
        "hook": "hook",
        "pacing": "pacing",
        "emotional_credibility": "emotional_credibility",
        "agency": "agency_read",
    }
    for score, source_key in source_score_keys.items():
        source_value = source.get(source_key)
        source_value = (
            source_value.get("score")
            if isinstance(source_value, Mapping)
            else source_value
        )
        if _score_value(source_value) != _score_value((review.get("scores") or {}).get(score)):
            raise ValueError("normalized reader score is not in Reader output")


def _attempt_receipt(
    root: Path,
    project_root: Path,
    *,
    task_id: str,
    task_projection: Mapping[str, Any],
    review: Mapping[str, Any],
    expected_work_item_id: str,
    expected_candidate_sha256: str,
) -> tuple[Path, str, tuple[Path, str] | None]:
    attempt_id = str(review.get("source_attempt_id") or "")
    if not attempt_id or Path(attempt_id).name != attempt_id:
        raise ValueError("review source attempt identity is invalid")
    task_root = project_root / "runtime" / "tasks" / task_id
    receipt, relative = _project_file(
        root,
        project_root,
        task_root / "attempt_logs" / attempt_id / "attempt_receipt.yml",
    )
    value = _load_review(receipt, role="attempt")
    attempt = (task_projection.get("attempts") or {}).get(attempt_id)
    work_item = (task_projection.get("work_items") or {}).get(
        expected_work_item_id
    )
    outcome = attempt.get("outcome") if isinstance(attempt, Mapping) else None
    outcome = outcome if isinstance(outcome, Mapping) else {}
    execution_contract = (
        attempt.get("execution_contract")
        if isinstance(attempt, Mapping)
        else None
    )
    execution_contract = (
        execution_contract if isinstance(execution_contract, Mapping) else {}
    )
    receipt_from_task = receipt.relative_to(task_root).as_posix()
    if (
        not isinstance(attempt, Mapping)
        or not isinstance(work_item, Mapping)
        or work_item.get("status") != "accepted"
        or attempt.get("work_item_id") != expected_work_item_id
        or attempt.get("status") != "succeeded"
        or execution_contract.get("role") != "Reviewer"
        or outcome.get("execution_origin") != "role_attempt_executor"
        or outcome.get("receipt_path") != receipt_from_task
        or outcome.get("receipt_sha256") != _sha256(receipt)
        or outcome.get("output_sha256") != review.get("source_output_sha256")
        or (review.get("execution") or {}).get("cli_agent") != attempt.get("worker")
        or (review.get("execution") or {}).get("runtime_provider")
        != execution_contract.get("runtime_provider")
        or (review.get("execution") or {}).get("model_id")
        != execution_contract.get("model_id")
        or (review.get("execution") or {}).get("model_tier")
        != execution_contract.get("model_tier")
    ):
        raise ValueError("review is not bound to the TaskRuntime attempt ledger")
    if (
        value.get("schema_version") != "task-runtime-role-attempt-receipt/v1"
        or value.get("project") != project_root.name
        or value.get("task_id") != task_id
        or value.get("work_item_id") != expected_work_item_id
        or value.get("attempt_id") != attempt_id
        or value.get("role") != "Reviewer"
        or value.get("status") != "pass"
        or value.get("output_sha256") != review.get("source_output_sha256")
    ):
        raise ValueError("review is not bound to a passing Reviewer attempt")
    output = task_root / str(value.get("output_path") or "")
    if (
        not output.is_file()
        or not output.resolve().is_relative_to(task_root.resolve())
        or _sha256(output) != value.get("output_sha256")
    ):
        raise ValueError("review attempt output binding is invalid")
    model_execution = value.get("model_execution")
    model_execution = model_execution if isinstance(model_execution, dict) else {}
    model_receipt = task_root / str(model_execution.get("path") or "")
    if (
        not model_receipt.is_file()
        or not model_receipt.resolve().is_relative_to(task_root.resolve())
        or _sha256(model_receipt) != model_execution.get("sha256")
    ):
        raise ValueError("review model execution receipt binding is invalid")
    raw_review = _attempt_review_output(output)
    _validate_review_derivation(
        review,
        raw_review,
        expected_work_item_id=expected_work_item_id,
    )
    candidate_binding: tuple[Path, str] | None = None
    raw_candidate_sha256 = str(raw_review.get("candidate_sha256") or "")
    if raw_candidate_sha256:
        if raw_candidate_sha256 != expected_candidate_sha256:
            raise ValueError("Reviewer attempt output targets a different candidate")
    else:
        manifest, manifest_relative = _project_file(
            root,
            project_root,
            receipt.parent / "outbound_context_manifest_reviewer.yml",
        )
        manifest_data = _load_review(manifest, role="outbound_context_manifest")
        inventory = (manifest_data.get("source_inventory") or {}).get("files") or []
        if (
            manifest_data.get("status") != "pass"
            or manifest_data.get("execution_allowed") is not True
            or manifest_data.get("role") != "Reviewer"
            or manifest_data.get("item_id") != task_id
            or not any(
                isinstance(item, Mapping)
                and item.get("sha256") == expected_candidate_sha256
                for item in inventory
            )
        ):
            raise ValueError("Reviewer attempt input does not bind the candidate")
        candidate_binding = (manifest, manifest_relative)
    return receipt, relative, candidate_binding


def _validate_reviews(
    *,
    project: str,
    task_id: str,
    chapter_id: int,
    candidate_sha256: str,
    senior_review: Mapping[str, Any],
    reader_review: Mapping[str, Any],
) -> None:
    for review, schema in (
        (senior_review, "senior-editor-final-review/v1"),
        (reader_review, "reader-panel-final-review/v1"),
    ):
        authority = review.get("authority")
        authority = authority if isinstance(authority, dict) else {}
        execution = review.get("execution")
        execution = execution if isinstance(execution, dict) else {}
        if (
            review.get("schema_version") != schema
            or review.get("status") != "pass"
            or review.get("disposition") != "candidate_only"
            or review.get("project") != project
            or not str(review.get("work_item_id") or "").strip()
            or not str(review.get("source_attempt_id") or "").strip()
            or not str(review.get("source_output_sha256") or "").strip()
            or any(
                not str(execution.get(field) or "").strip()
                for field in ("cli_agent", "runtime_provider", "model_id", "model_tier")
            )
            or authority
            != {
                "may_accept_candidate": False,
                "may_modify_canonical": False,
                "may_project_state": False,
            }
        ):
            raise ValueError("detached acceptance review provenance is invalid")
    common = (senior_review, reader_review)
    if any(
        review.get("project") != project
        or review.get("task_id") != task_id
        or review.get("chapter_id") != chapter_id
        or review.get("candidate_sha256") != candidate_sha256
        or str(review.get("status") or "").lower() != "pass"
        or str(review.get("verdict") or "").upper() != "PASS"
        or review.get("remaining_blockers") != []
        or (review.get("execution") or {}).get("fallback_used") is not False
        for review in common
    ):
        raise ValueError("detached acceptance reviews do not pass the exact candidate")
    gates = senior_review.get("gates")
    if (
        not isinstance(gates, dict)
        or set(gates) != _SENIOR_HARD_GATES
        or any(str(value).lower() != "pass" for value in gates.values())
    ):
        raise ValueError("senior editor hard gates did not all pass")
    if reader_review.get("policy_risks") not in (None, []):
        raise ValueError("reader panel reported a policy risk")


def validate_detached_candidate_acceptance(
    agentlab_root: Path,
    *,
    project: str,
    task_id: str,
    work_item_id: str,
    data: Mapping[str, Any],
    task_projection: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate one immutable auto-acceptance record against current evidence."""

    root = Path(agentlab_root).resolve()
    project_root = (root / "projects" / project).resolve(strict=True)
    if task_projection is None:
        task_projection = TaskRuntime(root, project=project).load_task(task_id)
    _, policy_sha256 = _authorized_detached_policy(root, project=project)
    if (
        data.get("schema_version") != "narrative-auto-acceptance-gate/v1"
        or data.get("status") != "accepted"
        or data.get("mode") != "detached"
        or data.get("project") != project
        or data.get("task_id") != task_id
        or data.get("work_item_id") != work_item_id
        or data.get("policy_sha256") != policy_sha256
        or data.get("hard_gate_status") != "pass"
        or data.get("fallback_used") is not False
        or data.get("exception_count") != 0
    ):
        raise ValueError("detached acceptance record identity or policy binding is invalid")
    chapter_id = data.get("chapter_id")
    if not isinstance(chapter_id, int) or isinstance(chapter_id, bool) or chapter_id < 1:
        raise ValueError("detached acceptance chapter_id is invalid")
    candidate, _ = _project_file(root, project_root, str(data.get("candidate_path") or ""))
    senior_path, _ = _project_file(
        root,
        project_root,
        str(data.get("senior_editor_review_path") or ""),
    )
    reader_path, _ = _project_file(
        root,
        project_root,
        str(data.get("reader_panel_review_path") or ""),
    )
    candidate_sha256 = _sha256(candidate)
    if candidate_sha256 != data.get("candidate_sha256"):
        raise ValueError("detached acceptance candidate hash is stale")
    evidence_paths = data.get("evidence_paths")
    content_hashes = data.get("content_hashes")
    if (
        not isinstance(evidence_paths, list)
        or len(evidence_paths) not in {5, 6, 7}
        or len(set(evidence_paths)) != len(evidence_paths)
        or not isinstance(content_hashes, dict)
        or set(content_hashes) != set(evidence_paths)
    ):
        raise ValueError("detached acceptance evidence inventory is invalid")
    for relative in evidence_paths:
        evidence, normalized = _project_file(root, project_root, str(relative))
        if normalized != relative or _sha256(evidence) != content_hashes.get(relative):
            raise ValueError("detached acceptance evidence hash is stale")
    senior_review = _load_review(senior_path, role="senior_editor")
    reader_review = _load_review(reader_path, role="reader_panel")
    _validate_review_dependencies(
        _state_projector_work_item(
            task_projection,
            work_item_id=work_item_id,
        ),
        task_projection,
        senior_review,
        reader_review,
    )
    _validate_reviews(
        project=project,
        task_id=task_id,
        chapter_id=chapter_id,
        candidate_sha256=candidate_sha256,
        senior_review=senior_review,
        reader_review=reader_review,
    )
    for review, expected_work_item_id in (
        (senior_review, str(senior_review["work_item_id"])),
        (reader_review, str(reader_review["work_item_id"])),
    ):
        _, receipt_relative, candidate_binding = _attempt_receipt(
            root,
            project_root,
            task_id=task_id,
            task_projection=task_projection,
            review=review,
            expected_work_item_id=expected_work_item_id,
            expected_candidate_sha256=candidate_sha256,
        )
        if receipt_relative not in evidence_paths:
            raise ValueError("detached acceptance omits a Reviewer attempt receipt")
        if candidate_binding is not None and candidate_binding[1] not in evidence_paths:
            raise ValueError("detached acceptance omits Reviewer candidate input evidence")
    return {
        "schema_version": "narrative-auto-acceptance-validation/v1",
        "status": "accepted",
        "project": project,
        "task_id": task_id,
        "work_item_id": work_item_id,
        "chapter_id": chapter_id,
        "candidate_sha256": candidate_sha256,
        "policy_sha256": policy_sha256,
    }


def record_detached_candidate_acceptance(
    agentlab_root: Path,
    *,
    project: str,
    task_id: str,
    work_item_id: str,
    chapter_id: int,
    candidate_path: Path,
    senior_editor_review_path: Path,
    reader_panel_review_path: Path,
    idempotency_key: str,
) -> dict[str, Any]:
    """Record a dual-review, hard-gate automatic acceptance decision."""

    root = Path(agentlab_root).resolve()
    project_root = (root / "projects" / project).resolve(strict=True)
    runtime = TaskRuntime(root, project=project)
    task_projection = runtime.load_task(task_id)
    _state_projector_work_item(
        task_projection,
        work_item_id=work_item_id,
    )
    _, policy_sha256 = _authorized_detached_policy(root, project=project)
    candidate, candidate_relative = _project_file(root, project_root, candidate_path)
    senior, senior_relative = _project_file(
        root, project_root, senior_editor_review_path
    )
    reader, reader_relative = _project_file(
        root, project_root, reader_panel_review_path
    )
    candidate_sha256 = _sha256(candidate)
    senior_review = _load_review(senior, role="senior_editor")
    reader_review = _load_review(reader, role="reader_panel")
    _validate_review_dependencies(
        task_projection["work_items"][work_item_id],
        task_projection,
        senior_review,
        reader_review,
    )
    _validate_reviews(
        project=project,
        task_id=task_id,
        chapter_id=chapter_id,
        candidate_sha256=candidate_sha256,
        senior_review=senior_review,
        reader_review=reader_review,
    )
    _, senior_attempt_relative, senior_candidate_binding = _attempt_receipt(
        root,
        project_root,
        task_id=task_id,
        task_projection=task_projection,
        review=senior_review,
        expected_work_item_id=str(senior_review["work_item_id"]),
        expected_candidate_sha256=candidate_sha256,
    )
    _, reader_attempt_relative, reader_candidate_binding = _attempt_receipt(
        root,
        project_root,
        task_id=task_id,
        task_projection=task_projection,
        review=reader_review,
        expected_work_item_id=str(reader_review["work_item_id"]),
        expected_candidate_sha256=candidate_sha256,
    )
    evidence_paths = [
        candidate_relative,
        senior_relative,
        reader_relative,
        senior_attempt_relative,
        reader_attempt_relative,
    ]
    evidence_paths.extend(
        binding[1]
        for binding in (senior_candidate_binding, reader_candidate_binding)
        if binding is not None
    )
    record = {
        "schema_version": "narrative-auto-acceptance-gate/v1",
        "status": "accepted",
        "mode": "detached",
        "project": project,
        "task_id": task_id,
        "work_item_id": work_item_id,
        "chapter_id": chapter_id,
        "candidate_path": candidate_relative,
        "candidate_sha256": candidate_sha256,
        "senior_editor_review_path": senior_relative,
        "reader_panel_review_path": reader_relative,
        "policy_sha256": policy_sha256,
        "hard_gate_status": "pass",
        "fallback_used": False,
        "exception_count": 0,
        "evidence_paths": evidence_paths,
        "content_hashes": {
            relative: _sha256(root / relative) for relative in evidence_paths
        },
    }
    task_root = runtime.tasks_root / task_id
    staging = task_root / "records" / "staging"
    staging.mkdir(parents=True, exist_ok=True)
    record_id = (
        f"narrative-auto-acceptance-chapter-{chapter_id:03d}-{work_item_id}"
    )
    source = staging / f"{record_id}.yml"
    atomic_write_yaml(source, record, sort_keys=False)
    projection = runtime.record_trace(
        task_id,
        record_id=record_id,
        record_type="narrative_auto_acceptance",
        producer="agentlab",
        producer_role="Runtime",
        path=source,
        idempotency_key=f"{idempotency_key}.trace",
    )
    immutable = projection["trace_records"][record_id]
    validate_detached_candidate_acceptance(
        root,
        project=project,
        task_id=task_id,
        work_item_id=work_item_id,
        data=immutable["record_data"],
        task_projection=projection,
    )
    return {
        "schema_version": "narrative-auto-acceptance-result/v1",
        "status": "accepted",
        "project": project,
        "task_id": task_id,
        "work_item_id": work_item_id,
        "chapter_id": chapter_id,
        "candidate_sha256": candidate_sha256,
        "policy_sha256": policy_sha256,
        "record_id": record_id,
        "record_path": immutable["path"],
    }


def _chapter_contract(project_root: Path, chapter_id: int) -> tuple[dict[str, Any], Path]:
    path = project_root / "production" / "chapter_cards" / "index.yml"
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError("chapter contract authority is invalid") from exc
    plans = document.get("chapter_state_plan") if isinstance(document, dict) else None
    matches = [
        item
        for item in (plans or [])
        if isinstance(item, dict) and item.get("chapter") == chapter_id
    ]
    if len(matches) != 1:
        raise ValueError("detached state projection requires one chapter contract")
    return matches[0], path


def _state_projector_work_item(
    projection: Mapping[str, Any],
    *,
    work_item_id: str,
) -> dict[str, Any]:
    work_item = (projection.get("work_items") or {}).get(work_item_id)
    if (
        not isinstance(work_item, dict)
        or work_item.get("kind") != "verification"
        or work_item.get("requires_user_acceptance") is not True
        or (
            work_item_id != "state-projector"
            and not work_item_id.endswith("-state-projector")
        )
    ):
        raise ValueError("detached acceptance target is not a governed state projector")
    if work_item.get("status") not in {"ready", "running", "accepted"}:
        raise ValueError("state projector is not ready for detached acceptance")
    return work_item


def _validate_review_dependencies(
    work_item: Mapping[str, Any],
    task_projection: Mapping[str, Any],
    senior_review: Mapping[str, Any],
    reader_review: Mapping[str, Any],
) -> None:
    senior_id = str(senior_review.get("work_item_id") or "")
    reader_id = str(reader_review.get("work_item_id") or "")
    required = {senior_id, reader_id}
    dependencies = set(work_item.get("depends_on") or [])
    work_items = task_projection.get("work_items") or {}
    senior_item = work_items.get(senior_id)
    reader_item = work_items.get(reader_id)
    if (
        "" in required
        or len(required) != 2
        or not required.issubset(dependencies)
        or not isinstance(senior_item, Mapping)
        or not isinstance(reader_item, Mapping)
        or senior_item.get("assigned_agent_id") not in {None, "senior_editor"}
        or reader_item.get("assigned_agent_id")
        not in {None, "reader_simulation_panel"}
    ):
        raise ValueError("detached reviews are not declared state-projector dependencies")


def _contract_state_facts(
    contract: Mapping[str, Any],
    *,
    prose_line_count: int,
) -> list[dict[str, str]]:
    if prose_line_count < 1:
        raise ValueError("detached state projection requires non-empty prose")
    opening = str(contract.get("opening_state") or "").strip()
    closing = str(contract.get("closing_state") or "").strip()
    turn = str(contract.get("turn") or "").strip()
    drive = contract.get("protagonist_drive")
    drive = drive if isinstance(drive, dict) else {}
    desire_delta = str(drive.get("desire_delta") or "").strip()
    world_delta = contract.get("world_state_delta")
    world_delta = world_delta if isinstance(world_delta, dict) else {}
    foreshadow = contract.get("foreshadow_actions")
    foreshadow = foreshadow if isinstance(foreshadow, list) else []
    if not all((opening, closing, turn, desire_delta, world_delta, foreshadow)):
        raise ValueError("chapter contract lacks required projection facts")
    last = prose_line_count
    return [
        {
            "category": "chapter_state_transition",
            "evidence_location": f"L1-{last}",
            "content": f"{opening} -> {closing}; irreversible_turn={turn}",
        },
        {
            "category": "protagonist_drive_delta",
            "evidence_location": "L1",
            "content": desire_delta,
        },
        {
            "category": "world_state_delta",
            "evidence_location": f"L{2 if last >= 2 else 1}-{last}",
            "content": yaml.safe_dump(
                world_delta,
                sort_keys=True,
                allow_unicode=True,
            ).strip(),
        },
        {
            "category": "foreshadow_actions",
            "evidence_location": f"L{last}",
            "content": yaml.safe_dump(
                foreshadow,
                sort_keys=True,
                allow_unicode=True,
            ).strip(),
        },
    ]


def _commit_authoritative_state(
    *,
    root: Path,
    project_root: Path,
    project: str,
    task_id: str,
    chapter_id: int,
    candidate_sha256: str,
    contract: Mapping[str, Any],
    delta: Mapping[str, Any],
    verification: Mapping[str, Any],
    acceptance_record_id: str,
    acceptance_record_sha256: str,
    work_item_id: str,
    projection_attempt_id: str,
    output_dir: Path,
) -> dict[str, Any]:
    store = NarrativeStateStore(project_root / "project_brain", project=project)
    current = store.read()
    existing = (current.get("chapters") or {}).get(str(chapter_id))
    brief_sha256 = narrative_payload_sha256(contract)
    source_projection_sha256 = narrative_payload_sha256(delta)
    verification_result_sha256 = narrative_payload_sha256(verification)
    evidence_binding_id = (
        f"{task_id}:chapter-{chapter_id:03d}:{candidate_sha256[:16]}"
    )
    binding = {
        "artifact_sha256": candidate_sha256,
        "brief_sha256": brief_sha256,
        "source_projection_sha256": source_projection_sha256,
        "verification_result_sha256": verification_result_sha256,
        "state_delta_sha256": source_projection_sha256,
    }
    decision_tag = hashlib.sha256(acceptance_record_id.encode("utf-8")).hexdigest()[:12]
    seal_receipt_path = (
        output_dir / f"chapter_{chapter_id:03d}_{decision_tag}_auto_seal.yml"
    )
    verification_receipt_path = (
        output_dir
        / f"chapter_{chapter_id:03d}_{decision_tag}_delta_verification_receipt.yml"
    )
    verified_commit_path = (
        output_dir / f"chapter_{chapter_id:03d}_{decision_tag}_verified_commit.yml"
    )
    seal_receipt = {
        "schema_version": "narrative-detached-auto-seal-receipt/v1",
        "issuer": "AgentLab.DetachedAcceptance",
        "decision_id": acceptance_record_id,
        "acceptance_record_sha256": acceptance_record_sha256,
        "task_id": task_id,
        "work_item_id": work_item_id,
        "evidence_binding_id": evidence_binding_id,
        "status": "accepted",
        **binding,
    }
    verification_receipt = {
        "schema_version": "delta-verification-receipt/v1",
        "issuer": "AgentLab.DeltaVerifier",
        "attempt_id": projection_attempt_id,
        "evidence_binding_id": evidence_binding_id,
        "status": "pass",
        "source_projection_sha256": source_projection_sha256,
        "verification_result_sha256": verification_result_sha256,
    }
    expected_commit = {
        "schema_version": "verified-chapter-commit/v1",
        "project": project,
        "chapter": chapter_id,
        "artifact_sha256": candidate_sha256,
        "brief_sha256": brief_sha256,
        "source_projection_sha256": source_projection_sha256,
        "state_delta_sha256": source_projection_sha256,
        "seal": {
            "status": "accepted",
            "mode": "detached",
            "decision_id": acceptance_record_id,
            "acceptance_record_sha256": acceptance_record_sha256,
            "task_id": task_id,
            "work_item_id": work_item_id,
            "evidence_binding_id": evidence_binding_id,
            "receipt_path": seal_receipt_path.relative_to(project_root).as_posix(),
            "receipt_sha256": "",
            **binding,
        },
        "delta_verification": {
            "status": "pass",
            "attempt_id": verification_receipt["attempt_id"],
            "evidence_binding_id": evidence_binding_id,
            "receipt_path": verification_receipt_path.relative_to(
                project_root
            ).as_posix(),
            "receipt_sha256": "",
            "source_projection_sha256": source_projection_sha256,
            "verification_result_sha256": verification_result_sha256,
        },
        "previous_state_sha256": current["state_sha256"],
        "state_delta": dict(delta),
    }
    if verified_commit_path.exists():
        verified_commit = _load_review(
            verified_commit_path,
            role="verified_chapter_commit",
        )
        for field in (
            "schema_version",
            "project",
            "chapter",
            "artifact_sha256",
            "brief_sha256",
            "source_projection_sha256",
            "state_delta_sha256",
            "state_delta",
        ):
            if verified_commit.get(field) != expected_commit.get(field):
                raise ValueError("existing verified chapter commit binding changed")
        if (
            verified_commit.get("seal", {}).get("decision_id")
            != acceptance_record_id
            or verified_commit.get("delta_verification", {}).get("attempt_id")
            != projection_attempt_id
        ):
            raise ValueError("existing verified chapter commit Attempt binding changed")
    else:
        if isinstance(existing, Mapping):
            raise ValueError("narrative authority chapter lacks its verified commit artifact")
        atomic_write_yaml(seal_receipt_path, seal_receipt, sort_keys=False)
        atomic_write_yaml(
            verification_receipt_path,
            verification_receipt,
            sort_keys=False,
        )
        expected_commit["seal"]["receipt_sha256"] = _sha256(seal_receipt_path)
        expected_commit["delta_verification"]["receipt_sha256"] = _sha256(
            verification_receipt_path
        )
        verified_commit = expected_commit
        atomic_write_yaml(verified_commit_path, verified_commit, sort_keys=False)
    receipt = store.commit(verified_commit)
    return {
        "verified_commit_path": verified_commit_path.relative_to(root).as_posix(),
        "verified_commit_sha256": _sha256(verified_commit_path),
        **receipt,
        "status": (
            "already_committed" if isinstance(existing, Mapping) else "committed"
        ),
    }


def project_detached_candidate_state(
    agentlab_root: Path,
    *,
    project: str,
    task_id: str,
    work_item_id: str,
    idempotency_key: str,
) -> dict[str, Any]:
    """Project and verify non-empty chapter state, then accept its WorkItem."""

    root = Path(agentlab_root).resolve()
    project_root = (root / "projects" / project).resolve(strict=True)
    runtime = TaskRuntime(root, project=project)
    projection = runtime.load_task(task_id)
    work_item = _state_projector_work_item(
        projection,
        work_item_id=work_item_id,
    )
    records = [
        record
        for record in projection.get("trace_records", {}).values()
        if record.get("record_type") == "narrative_auto_acceptance"
        and (record.get("record_data") or {}).get("work_item_id") == work_item_id
    ]
    valid_records: list[tuple[Mapping[str, Any], dict[str, Any]]] = []
    for record in records:
        try:
            validation = validate_detached_candidate_acceptance(
                root,
                project=project,
                task_id=task_id,
                work_item_id=work_item_id,
                data=record.get("record_data") or {},
                task_projection=projection,
            )
        except (OSError, RuntimeError, ValueError):
            continue
        valid_records.append((record, validation))
    if len(valid_records) != 1:
        raise ValueError("state projection requires one automatic acceptance record")
    acceptance_record, accepted = valid_records[0]
    chapter_id = int(accepted["chapter_id"])
    candidate = root / str((acceptance_record["record_data"])["candidate_path"])
    attempt_prefix = f"{work_item_id}-detached-chapter-{chapter_id:03d}-attempt-"
    matching_attempts = sorted(
        (
            int(attempt_id.removeprefix(attempt_prefix)),
            attempt_id,
            attempt,
        )
        for attempt_id, attempt in (projection.get("attempts") or {}).items()
        if attempt_id.startswith(attempt_prefix)
        and attempt_id.removeprefix(attempt_prefix).isdigit()
    )
    reusable_attempt = next(
        (
            attempt_id
            for _, attempt_id, attempt in reversed(matching_attempts)
            if attempt.get("status") in {"scheduled", "running", "succeeded"}
            and (
                (attempt.get("execution_contract") or {})
                .get("deterministic_tool", {})
                .get("acceptance_record_id")
                == acceptance_record.get("record_id")
            )
        ),
        None,
    )
    projection_attempt_id = reusable_attempt or (
        f"{attempt_prefix}{(matching_attempts[-1][0] + 1) if matching_attempts else 1:03d}"
    )
    attempt_idempotency_key = f"{idempotency_key}.attempt.{projection_attempt_id}"
    attempt_executor = NarrativeProjectionAttemptExecutor(root, project=project)
    attempt_run = attempt_executor.start(
        task_id=task_id,
        work_item_id=work_item_id,
        attempt_id=projection_attempt_id,
        candidate_sha256=accepted["candidate_sha256"],
        acceptance_record_id=str(acceptance_record.get("record_id") or ""),
        idempotency_key=attempt_idempotency_key,
    )
    projection = attempt_run["projection"]
    work_item = projection["work_items"][work_item_id]
    contract, contract_path = _chapter_contract(project_root, chapter_id)
    state_delta = project_state(candidate, chapter_id=chapter_id)
    for fact in _contract_state_facts(
        contract,
        prose_line_count=len(candidate.read_text(encoding="utf-8").splitlines()),
    ):
        state_delta = StateProjector.record_hard_fact(state_delta, **fact)
    delta = state_delta.to_dict()
    delta["chapter_contract_path"] = contract_path.relative_to(root).as_posix()
    delta["chapter_contract_sha256"] = _sha256(contract_path)
    delta["acceptance_record_id"] = acceptance_record.get("record_id")
    world_delta = contract.get("world_state_delta")
    if isinstance(world_delta, Mapping):
        delta["world_updates"] = [
            {
                "axis": str(
                    world_delta.get("axis")
                    or f"chapter_{chapter_id:03d}_story_state"
                ),
                "value": dict(world_delta),
            }
        ]
    foreshadow = contract.get("foreshadow_actions")
    if isinstance(foreshadow, list):
        delta["foreshadow_updates"] = [
            {"id": str(item["foreshadow_id"]), **dict(item)}
            for item in foreshadow
            if isinstance(item, Mapping) and str(item.get("foreshadow_id") or "")
        ]
    verification = verify_state_delta(candidate, delta)
    if verification.get("status") != "pass" or state_delta.is_empty:
        raise ValueError("detached state projection verification failed")
    task_root = runtime.tasks_root / task_id
    output_dir = task_root / "artifacts" / "state_deltas"
    output_dir.mkdir(parents=True, exist_ok=True)
    delta_path = output_dir / f"chapter_{chapter_id:03d}.yml"
    verification_path = output_dir / f"chapter_{chapter_id:03d}_verification.yml"
    atomic_write_yaml(delta_path, delta, sort_keys=False)
    atomic_write_yaml(verification_path, verification, sort_keys=False)
    attempt_verification = attempt_executor.complete(
        task_id=task_id,
        work_item_id=work_item_id,
        attempt_id=projection_attempt_id,
        output_path=delta_path,
        deterministic_tool=attempt_run["deterministic_tool"],
        idempotency_key=attempt_idempotency_key,
    )
    authority_commit = _commit_authoritative_state(
        root=root,
        project_root=project_root,
        project=project,
        task_id=task_id,
        chapter_id=chapter_id,
        candidate_sha256=accepted["candidate_sha256"],
        contract=contract,
        delta=delta,
        verification=verification,
        acceptance_record_id=str(acceptance_record.get("record_id") or ""),
        acceptance_record_sha256=str(acceptance_record.get("sha256") or ""),
        work_item_id=work_item_id,
        projection_attempt_id=projection_attempt_id,
        output_dir=output_dir,
    )
    projection = runtime.load_task(task_id)
    work_item = projection["work_items"][work_item_id]

    if work_item.get("status") == "ready":
        projection = runtime.transition_work_item(
            task_id,
            work_item_id=work_item_id,
            status="running",
            idempotency_key=f"{idempotency_key}.running",
        )
        work_item = projection["work_items"][work_item_id]
    if work_item.get("status") == "running":
        staging = task_root / "records" / "staging"
        staging.mkdir(parents=True, exist_ok=True)
        validation_record = {
            "schema_version": "local-validation-receipt/v1",
            "status": "pass",
            "checks": [
                f"candidate_sha256:{accepted['candidate_sha256']}",
                f"chapter_contract_sha256:{delta['chapter_contract_sha256']}",
                f"state_delta_sha256:{_sha256(delta_path)}",
                f"delta_verification_sha256:{_sha256(verification_path)}",
                f"narrative_authority_event:{authority_commit.get('event_id')}",
                f"projection_attempt_id:{projection_attempt_id}",
            ],
        }
        record_id = f"detached-state-projection-{work_item_id}"
        source = staging / f"{record_id}.yml"
        atomic_write_yaml(source, validation_record, sort_keys=False)
        runtime.record_trace(
            task_id,
            record_id=record_id,
            record_type="local_validation_receipt",
            producer="agentlab",
            producer_role="Runtime",
            path=source,
            idempotency_key=f"{idempotency_key}.validation",
        )
        projection = runtime.transition_work_item(
            task_id,
            work_item_id=work_item_id,
            status="accepted",
            idempotency_key=f"{idempotency_key}.accepted",
        )
    elif work_item.get("status") != "accepted":
        raise ValueError("state projector work item is not ready or running")
    downstream_work_items = {
        item_id: item
        for item_id, item in projection["work_items"].items()
        if work_item_id in set(item.get("depends_on") or [])
    }
    next_ready_work_items = sorted(
        item_id
        for item_id, item in downstream_work_items.items()
        if item.get("status") == "ready"
    )
    if not any(
        item.get("status") in {"ready", "running", "accepted"}
        for item in downstream_work_items.values()
    ):
        raise ValueError("detached projection has no ready downstream DAG node")
    return {
        "schema_version": "narrative-detached-state-projection-result/v1",
        "status": "pass",
        "project": project,
        "task_id": task_id,
        "work_item_id": work_item_id,
        "chapter_id": chapter_id,
        "candidate_sha256": accepted["candidate_sha256"],
        "state_delta_path": delta_path.relative_to(root).as_posix(),
        "state_delta_sha256": _sha256(delta_path),
        "verification_path": verification_path.relative_to(root).as_posix(),
        "verification": verification,
        "authority_commit": authority_commit,
        "projection_attempt": attempt_verification,
        "next_ready_work_items": next_ready_work_items,
        "work_item_status": projection["work_items"][work_item_id]["status"],
    }


def auto_accept_and_project_candidate(
    agentlab_root: Path,
    *,
    project: str,
    task_id: str,
    work_item_id: str,
    chapter_id: int,
    candidate_path: Path,
    senior_editor_review_path: Path,
    reader_panel_review_path: Path,
    idempotency_key: str,
) -> dict[str, Any]:
    """Run the detached acceptance/projection transaction and pause on exception."""

    accepted: dict[str, Any] | None = None
    try:
        accepted = record_detached_candidate_acceptance(
            agentlab_root,
            project=project,
            task_id=task_id,
            work_item_id=work_item_id,
            chapter_id=chapter_id,
            candidate_path=candidate_path,
            senior_editor_review_path=senior_editor_review_path,
            reader_panel_review_path=reader_panel_review_path,
            idempotency_key=f"{idempotency_key}.accept",
        )
        projected = project_detached_candidate_state(
            agentlab_root,
            project=project,
            task_id=task_id,
            work_item_id=work_item_id,
            idempotency_key=f"{idempotency_key}.project",
        )
    except (OSError, RuntimeError, ValueError):
        runtime = TaskRuntime(agentlab_root, project=project)
        projection = runtime.load_task(task_id)
        for attempt in (projection.get("attempts") or {}).values():
            deterministic_tool = (attempt.get("execution_contract") or {}).get(
                "deterministic_tool"
            ) or {}
            if (
                accepted is None
                or attempt.get("work_item_id") != work_item_id
                or attempt.get("worker")
                != DETACHED_PROJECTOR_TOOL_ID
                or deterministic_tool.get("acceptance_record_id")
                != accepted.get("record_id")
            ):
                continue
            if attempt.get("status") == "running":
                runtime.transition_attempt(
                    task_id,
                    attempt_id=str(attempt["attempt_id"]),
                    status="failed",
                    outcome={"reason": "detached_acceptance_exception"},
                    idempotency_key=(
                        f"{idempotency_key}.exception-attempt-failed."
                        f"{attempt['attempt_id']}"
                    ),
                )
            elif attempt.get("status") == "scheduled":
                runtime.transition_attempt(
                    task_id,
                    attempt_id=str(attempt["attempt_id"]),
                    status="cancelled",
                    outcome={"reason": "detached_acceptance_exception"},
                    idempotency_key=(
                        f"{idempotency_key}.exception-attempt-cancelled."
                        f"{attempt['attempt_id']}"
                    ),
                )
        projection = runtime.load_task(task_id)
        if projection["task"].get("status") in {
            "created",
            "ready",
            "running",
            "waiting",
            "blocked",
        }:
            runtime.transition_task(
                task_id,
                status="paused",
                idempotency_key=f"{idempotency_key}.exception-pause",
            )
        raise
    return {
        "schema_version": "narrative-detached-auto-advance-result/v1",
        "status": "pass",
        "acceptance": accepted,
        "projection": projected,
    }
