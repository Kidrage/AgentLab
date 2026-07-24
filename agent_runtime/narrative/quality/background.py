"""Background adapter for hash-bound, candidate-only narrative revisions."""

from __future__ import annotations

import hashlib
import json
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
_PROPOSAL_SCALAR_FIELDS = tuple(
    field for field in _CONTRACT_SCALAR_FIELDS if field != "revision_contract_id"
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


def _blocking_revision_chapters(heavy: Mapping[str, Any]) -> set[int]:
    """Return chapters with evidence-bound blocking findings in the heavy audit."""
    chapters: set[int] = set()
    for document_name, collection_name in (
        ("fiction_review", "findings"),
        ("continuity_failure_report_data", "failures"),
    ):
        document = heavy.get(document_name)
        if not isinstance(document, Mapping):
            continue
        for finding in document.get(collection_name) or []:
            if not isinstance(finding, Mapping) or finding.get("severity") != "blocking":
                continue
            try:
                chapter = int(finding.get("chapter") or 0)
            except (TypeError, ValueError):
                continue
            if chapter > 0:
                chapters.add(chapter)
    scorecard = heavy.get("narrative_quality_scorecard")
    if isinstance(scorecard, Mapping):
        for chapter_record in scorecard.get("chapters") or []:
            if not isinstance(chapter_record, Mapping):
                continue
            if chapter_record.get("status") != "blocked":
                continue
            try:
                chapter = int(chapter_record.get("chapter_id") or 0)
            except (TypeError, ValueError):
                continue
            if chapter > 0:
                chapters.add(chapter)
    return chapters


def _deduplicated_strings(
    contracts: list[Mapping[str, Any]],
    field: str,
) -> list[str]:
    values: list[str] = []
    for contract in contracts:
        raw_values = contract.get(field)
        if not isinstance(raw_values, list) or not raw_values:
            raise ValueError("revision_contract_incomplete")
        for raw in raw_values:
            value = str(raw).strip()
            if value and value not in values:
                values.append(value)
    if not values:
        raise ValueError("revision_contract_incomplete")
    return values


def _compile_executable_revision_contracts(
    contracts: list[Any],
    *,
    blocking_chapters: set[int],
) -> list[dict[str, Any]]:
    """Compile one executable, evidence-preserving contract per blocked chapter."""
    grouped: dict[int, list[Mapping[str, Any]]] = {}
    for raw in contracts:
        if not isinstance(raw, Mapping):
            raise ValueError("revision_contract_not_mapping")
        try:
            chapter = int(raw.get("chapter_id") or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError("revision_contract_identity_mismatch") from exc
        if blocking_chapters and chapter not in blocking_chapters:
            continue
        supplied_scope = raw.get("rewrite_scope")
        if supplied_scope is not None and supplied_scope not in {"scene", "chapter"}:
            raise ValueError("revision_contract_scope_invalid")
        if supplied_scope is None and not any(raw.get(field) for field in _PROPOSAL_SCALAR_FIELDS):
            raise ValueError("revision_contract_scope_invalid")
        if any(not raw.get(field) for field in _PROPOSAL_SCALAR_FIELDS):
            raise ValueError("revision_contract_incomplete")
        _deduplicated_strings([raw], "must_preserve")
        _deduplicated_strings([raw], "must_change")
        _deduplicated_strings([raw], "causal_requirements")
        _deduplicated_strings([raw], "character_knowledge_before")
        _deduplicated_strings([raw], "character_knowledge_after")
        _deduplicated_strings([raw], "forbidden_regressions")
        grouped.setdefault(chapter, []).append(raw)
    if not grouped:
        raise ValueError("missing_executable_scene_revision_contracts")

    normalized: list[dict[str, Any]] = []
    for chapter, chapter_contracts in grouped.items():
        if len(chapter_contracts) == 1:
            existing = dict(chapter_contracts[0])
            if not _contract_issues(existing, chapter=chapter):
                normalized.append(existing)
                continue
        compiled: dict[str, Any] = {
            "schema_version": 1,
            "chapter_id": chapter,
            "target_scene": "；".join(
                dict.fromkeys(
                    str(contract["target_scene"]).strip()
                    for contract in chapter_contracts
                )
            ),
            "rewrite_scope": (
                "chapter"
                if any(contract.get("rewrite_scope") == "chapter" for contract in chapter_contracts)
                else "scene"
            ),
            "problem_type": " + ".join(
                dict.fromkeys(
                    str(contract["problem_type"]).strip()
                    for contract in chapter_contracts
                )
            ),
            "evidence": "\n".join(
                dict.fromkeys(
                    str(contract["evidence"]).strip()
                    for contract in chapter_contracts
                )
            ),
            "must_preserve": _deduplicated_strings(
                chapter_contracts,
                "must_preserve",
            ),
            "must_change": _deduplicated_strings(chapter_contracts, "must_change"),
            "allowed_freedom": "\n".join(
                dict.fromkeys(
                    str(contract["allowed_freedom"]).strip()
                    for contract in chapter_contracts
                )
            ),
            "causal_requirements": _deduplicated_strings(
                chapter_contracts,
                "causal_requirements",
            ),
            "character_knowledge_before": _deduplicated_strings(
                chapter_contracts,
                "character_knowledge_before",
            ),
            "character_knowledge_after": _deduplicated_strings(
                chapter_contracts,
                "character_knowledge_after",
            ),
            "decision_cost": "\n".join(
                dict.fromkeys(
                    str(contract["decision_cost"]).strip()
                    for contract in chapter_contracts
                )
            ),
            "new_information": "\n".join(
                dict.fromkeys(
                    str(contract["new_information"]).strip()
                    for contract in chapter_contracts
                )
            ),
            "forbidden_regressions": _deduplicated_strings(
                chapter_contracts,
                "forbidden_regressions",
            ),
        }
        compiled["revision_contract_id"] = "rev-" + hashlib.sha256(
            json.dumps(
                compiled,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()[:24]
        issues = _contract_issues(compiled, chapter=chapter)
        if issues:
            raise ValueError(issues[0])
        normalized.append(compiled)
    return normalized


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
    legacy_request = revision_run / "narrative_v2_writer_request.yml"
    revision_request = (
        legacy_request
        if legacy_request.is_file()
        else revision_run / "revision_request.yml"
    )
    legacy_output_contract = revision_run / "writer_v2_output_contract.yml"
    writer_output_contract = (
        legacy_output_contract
        if legacy_output_contract.is_file()
        else revision_run / "writer_output_contract.yml"
    )
    legacy_session_receipt = revision_run / "narrative_v2_writer_session_receipt.yml"
    writer_session_receipt = (
        legacy_session_receipt
        if legacy_session_receipt.is_file()
        else revision_run / "writer_session_receipt.yml"
    )
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
            revision_request,
            "revision_request",
        ),
        **_prefixed_ref(
            root,
            writer_output_contract,
            "writer_output_contract",
        ),
        **_prefixed_ref(
            root,
            writer_session_receipt,
            "writer_session_receipt",
        ),
        **_prefixed_ref(root, triggering_audit, "triggering_audit"),
    }
    row["path"] = row["draft_path"]
    row["sha256"] = row["draft_sha256"]
    return row


def _execute_v3_targeted_revision(
    *,
    root: Path,
    project: str,
    chapter: int,
    job_id: str,
    candidate_set_id: str,
    source_task_id: str,
    source_run: Path,
    source_request: Path,
    source_candidate: Path,
    contract_path: Path,
    triggering_audit: Path,
    revision_task_id: str,
    revision_attempt_id: str,
    revision_run: Path,
    call_fence: Path,
    capacity_route_override: str | None = None,
    previous_short_revision: str = "",
    allow_length_retry: bool = True,
) -> str:
    """Run one prose-only revision against a hash-bound V3 chapter packet."""
    from agent_runtime.narrative.quality.prose_length import (
        CJK_CHARACTER_UNIT,
        HAN_CHARACTER_UNIT,
        build_character_contract,
    )
    from agent_runtime.schemas import WorkflowPlan
    from agent_runtime.writer_output_materializer import (
        materialize_writer_v2_content,
    )

    # agent_runner is also a direct CLI entry module, so use its canonical import.
    from agent_runner import run_agent_model

    try:
        source_plan = yaml.safe_load(
            (source_run / "workflow_plan.yml").read_text(encoding="utf-8")
        ) or {}
        chapter_packet = yaml.safe_load(
            (source_run / "chapter_packet.yml").read_text(encoding="utf-8")
        ) or {}
        bound_contract = yaml.safe_load(
            contract_path.read_text(encoding="utf-8")
        ) or {}
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ValueError("background_revision_v3_source_invalid") from exc
    if not all(
        isinstance(value, dict)
        for value in (source_plan, chapter_packet, bound_contract)
    ):
        raise ValueError("background_revision_v3_source_invalid")
    hard_range = (chapter_packet.get("chapter_intent") or {}).get(
        "hard_character_range"
    )
    length_policy_path = (
        root
        / "projects"
        / project
        / "production"
        / "chapter_length_policy.yml"
    )
    length_unit = HAN_CHARACTER_UNIT
    length_policy_ref: dict[str, str] | None = None
    if length_policy_path.is_file():
        if _has_symlink_component(root, length_policy_path):
            raise ValueError("background_revision_v3_length_policy_invalid")
        try:
            length_policy = yaml.safe_load(
                length_policy_path.read_text(encoding="utf-8")
            ) or {}
        except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
            raise ValueError(
                "background_revision_v3_length_policy_invalid"
            ) from exc
        if not isinstance(length_policy, dict):
            raise ValueError("background_revision_v3_length_policy_invalid")
        length_unit = str(length_policy.get("unit") or "").strip()
        length_policy_ref = _ref(root, length_policy_path)
    length_contract = build_character_contract(hard_range, unit=length_unit)
    if length_contract is None:
        raise ValueError("background_revision_v3_length_contract_invalid")

    source_delivery = source_run / "narrative_delivery_receipt.yml"
    source_task_packet = source_run / "task_packet_writer.json"
    source_output_contract = source_run / "writer_output_contract.yml"
    for path in (source_delivery, source_task_packet, source_output_contract):
        if not path.is_file() or _has_symlink_component(root, path):
            raise ValueError("background_revision_v3_source_invalid")
    delivery = yaml.safe_load(source_delivery.read_text(encoding="utf-8")) or {}
    artifact_hashes = delivery.get("artifact_sha256") if isinstance(delivery, dict) else {}
    if (
        not isinstance(artifact_hashes, Mapping)
        or artifact_hashes.get("fiction_draft.md") != _sha256(source_candidate)
        or artifact_hashes.get("chapter_packet.yml")
        != _sha256(source_run / "chapter_packet.yml")
    ):
        raise ValueError("background_revision_v3_source_binding_mismatch")

    plan_data = dict(source_plan)
    plan_data["task_id"] = revision_task_id
    plan_data["run_dir"] = str(revision_run)
    plan_data["user_request_path"] = str(revision_run / "revision_request.yml")
    route = dict(plan_data.get("route") or {})
    route["agents"] = ["Writer"]
    route["skipped_agents"] = []
    plan_data["route"] = route
    writer_config = dict((plan_data.get("included_agents") or {}).get("Writer") or {})
    writer_config["required_outputs"] = [
        f"runs/{revision_task_id}/fiction_draft.md"
    ]
    plan_data["included_agents"] = {"Writer": writer_config}
    writer_profile = dict((plan_data.get("model_profiles") or {}).get("Writer") or {})
    plan_data["model_profiles"] = {"Writer": writer_profile}
    plan_data["notes"] = [
        *list(plan_data.get("notes") or []),
        "Targeted V3 revision: one hash-bound prose candidate, candidate-only.",
    ]
    plan = WorkflowPlan.model_validate(plan_data)
    _publish_yaml_exclusive(
        root,
        revision_run / "workflow_plan.yml",
        plan.model_dump(mode="json"),
    )
    _publish_yaml_exclusive(
        root,
        revision_run / "chapter_packet.yml",
        chapter_packet,
    )
    _publish_yaml_exclusive(
        root,
        revision_run / "mission_contract.yml",
        {
            "schema_version": 1,
            "status": "active",
            "project": project,
            "task_id": revision_task_id,
            "route_decision": "narrative_light_chapter",
            "writer_contract_version": 2,
            "candidate_only": True,
            "production_modified": False,
            "required_outputs": ["fiction_draft.md"],
            "forbidden_outputs": [
                "continuity_ledger.yml",
                "state_transition_proposal.yml",
                "narrative_delivery_receipt.yml",
            ],
        },
    )
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
            "source_candidate_sha256": _sha256(source_candidate),
            "revision_contract_sha256": _sha256(contract_path),
        },
    )
    if not call_reserved:
        raise RuntimeError("background_revision_provider_result_unknown")
    minimum = int(length_contract["minimum"])
    maximum = int(length_contract["maximum"])
    unit_label = (
        "CJK characters using the project measurement"
        if length_unit == CJK_CHARACTER_UNIT
        else "Han characters excluding Markdown headings"
    )
    instructions = [
        "Return exactly one complete fiction_draft.md edit block.",
        "Rewrite only the contracted locations and preserve all other prose.",
        (
            "The complete revised chapter must contain between "
            f"{minimum} and {maximum} {unit_label}; do not return a shortened "
            "excerpt or patch fragment."
        ),
        "Do not emit audit language, explanations, ledgers, or receipts.",
    ]
    if previous_short_revision:
        instructions.insert(
            1,
            (
                "Continue from previous_short_revision_text, retain its contracted "
                "corrections, and expand the complete chapter into the required "
                "length range without padding or new facts."
            ),
        )
    revision_request = {
        "schema_version": 1,
        "job_kind": "narrative_revision",
        "run_mode": "targeted_rewrite",
        "project": project,
        "task_id": revision_task_id,
        "chapter_id": chapter,
        "candidate_only": True,
        "production_modified": False,
        "candidate_set_id": candidate_set_id,
        "source_job_id": job_id,
        "source_run_id": source_task_id,
        "attempt_id": revision_attempt_id,
        "source_writer_request": _ref(root, source_request),
        "source_candidate": _ref(root, source_candidate),
        "source_task_packet": _ref(root, source_task_packet),
        "source_delivery_receipt": _ref(root, source_delivery),
        "triggering_audit": _ref(root, triggering_audit),
        "revision_contract": _ref(root, contract_path),
        "attempt_receipt": _ref(root, call_fence),
        "workflow_plan_sha256": _sha256(revision_run / "workflow_plan.yml"),
        "instructions": instructions,
        "prose_length_contract": length_contract,
        "revision_contract_content": bound_contract,
        "source_candidate_text": source_candidate.read_text(encoding="utf-8"),
    }
    if length_policy_ref is not None:
        revision_request["chapter_length_policy"] = length_policy_ref
    if previous_short_revision:
        revision_request["previous_short_revision_text"] = previous_short_revision
    _publish_yaml_exclusive(
        root,
        revision_run / "revision_request.yml",
        revision_request,
    )

    result = run_agent_model(
        root,
        plan,
        "Writer",
        revision_run / "writer_role_session_capture.md",
        capacity_route_override=capacity_route_override,
        apply_patches=False,
    )
    usage = getattr(result, "raw_usage", None)
    usage = usage if isinstance(usage, dict) else {}
    call_id = str(
        usage.get("provider_session_id")
        or usage.get("session_id")
        or usage.get("command_id")
        or ""
    )
    delivery_result = materialize_writer_v2_content(
        str(getattr(result, "content", "") or ""),
        revision_run,
        revision_task_id,
        capture_name="writer_role_session_capture.md",
        provider=str(getattr(result, "provider", "") or ""),
        model=str(getattr(result, "model", "") or ""),
        call_id=call_id,
        prose_length_contract=length_contract,
    )
    if delivery_result.get("status") != "pass":
        reason = str(getattr(result, "error", "") or "")
        issues = [str(item) for item in delivery_result.get("issues") or []]
        below_minimum = any(
            item.startswith("fiction_draft_")
            and "_characters_below_minimum:" in item
            for item in issues
        )
        short_revision = str(
            delivery_result.get("rejected_canonical_prose") or ""
        )
        if below_minimum and short_revision.strip() and allow_length_retry:
            retry_task_id = f"{revision_task_id}-length-retry-2"
            retry_run = revision_run.parent / retry_task_id
            retry_fence = call_fence.with_name(
                f"{call_fence.stem}-length-retry-2{call_fence.suffix}"
            )
            observed_route = str(
                usage.get("capacity_route_id")
                or usage.get("capacity_route")
                or ""
            ).strip()
            return _execute_v3_targeted_revision(
                root=root,
                project=project,
                chapter=chapter,
                job_id=job_id,
                candidate_set_id=candidate_set_id,
                source_task_id=source_task_id,
                source_run=source_run,
                source_request=source_request,
                source_candidate=source_candidate,
                contract_path=contract_path,
                triggering_audit=triggering_audit,
                revision_task_id=retry_task_id,
                revision_attempt_id=f"{revision_attempt_id}-length-retry-2",
                revision_run=retry_run,
                call_fence=retry_fence,
                capacity_route_override=observed_route or None,
                previous_short_revision=short_revision,
                allow_length_retry=False,
            )
        raise RuntimeError(
            "background_revision_writer_blocked:"
            + (reason or ",".join(issues) or "materialization_failed")
        )
    _publish_yaml_exclusive(
        root,
        revision_run / "writer_output_contract.yml",
        {
            "schema_version": 1,
            "status": "pass",
            "task_id": revision_task_id,
            "candidate_only": True,
            "production_modified": False,
            "prose_sha256": delivery_result["prose_sha256"],
            "issues": [],
            "prose_length_contract": delivery_result.get("prose_length_contract"),
        },
    )
    _publish_yaml_exclusive(
        root,
        revision_run / "writer_session_receipt.yml",
        {
            "schema_version": 1,
            "status": "pass",
            "project": project,
            "task_id": revision_task_id,
            "chapter_id": chapter,
            "candidate_only": True,
            "production_modified": False,
            "request_sha256": _sha256(revision_run / "revision_request.yml"),
            "workflow_plan_sha256": _sha256(revision_run / "workflow_plan.yml"),
            "source_candidate_sha256": _sha256(source_candidate),
            "revision_contract_sha256": _sha256(contract_path),
            "prose_sha256": delivery_result["prose_sha256"],
            "observed_provider": str(getattr(result, "provider", "") or ""),
            "observed_model": str(getattr(result, "model", "") or ""),
            "observed_call_id": call_id,
        },
    )
    return revision_task_id


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
    source_candidate = source_run / "fiction_draft.md"
    legacy_source_request = source_run / "narrative_v2_writer_request.yml"
    legacy_source_contract = source_run / "writer_v2_output_contract.yml"
    v3_source_request = source_run / "live_generation_request.yml"
    v3_source_contract = source_run / "writer_output_contract.yml"
    legacy_source = legacy_source_request.is_file() and legacy_source_contract.is_file()
    source_request = (
        legacy_source_request if legacy_source else v3_source_request
    )
    source_contract = (
        legacy_source_contract if legacy_source else v3_source_contract
    )
    source_paths = (source_request, source_candidate, source_contract)
    if not all(
        path.is_file() and not _has_symlink_component(root, path)
        for path in source_paths
    ):
        raise ValueError(f"background_revision_source_invalid:{chapter}")

    job_id = _identifier(request.get("job_id"))
    lineage_version = "" if legacy_source else ":v3-targeted-revision-4"
    lineage_id = hashlib.sha256(
        (
            f"{project}:{job_id}:{proposal_sha256}:{chapter}:{contract_index}:"
            f"{contract.get('revision_contract_id')}{lineage_version}"
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
    call_fence = candidate_root / (
        f"provider-call-{contract_index:02d}.yml"
        if legacy_source
        else f"provider-call-{contract_index:02d}-{lineage_id}.yml"
    )

    # A controller retry receives a fresh lease, but the provider result is bound
    # to the proposal lineage rather than to that controller attempt. Recover a
    # complete immutable materialization before consulting the old spec/lease so
    # a later controller attempt can close the batch without paying twice.
    existing_materialized = _load_existing_yaml(root, materialized_path)
    if existing_materialized is not None:
        from agent_runtime.narrative_heavy_audit import (
            validate_revision_draft_binding,
        )

        existing_revision_task_id = _identifier(
            existing_materialized.get("revision_task_id") or revision_task_id
        )
        if not existing_revision_task_id.startswith(revision_task_id):
            raise RuntimeError("background_revision_materialized_binding_invalid")
        existing = validate_revision_draft_binding(
            root / "projects" / project,
            chapter=chapter,
            source_task_id=source_task_id,
            revision_task_id=existing_revision_task_id,
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
            revision_task_id=existing_revision_task_id,
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

    if not legacy_source:
        materialized_revision_task_id = _execute_v3_targeted_revision(
            root=root,
            project=project,
            chapter=chapter,
            job_id=job_id,
            candidate_set_id=candidate_set_id,
            source_task_id=source_task_id,
            source_run=source_run,
            source_request=source_request,
            source_candidate=source_candidate,
            contract_path=contract_path,
            triggering_audit=triggering_audit,
            revision_task_id=revision_task_id,
            revision_attempt_id=revision_attempt_id,
            revision_run=revision_run,
            call_fence=call_fence,
        )
        row = _build_revision_row(
            root=root,
            project=project,
            chapter=chapter,
            job_id=job_id,
            candidate_set_id=candidate_set_id,
            revision_attempt_id=revision_attempt_id,
            source_task_id=source_task_id,
            revision_task_id=materialized_revision_task_id,
            proposal_path=proposal_path,
            proposal_sha256=proposal_sha256,
            contract_path=contract_path,
            triggering_audit=triggering_audit,
        )
        _publish_yaml_exclusive(root, materialized_path, row)
        return row

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
        blocking_chapters = _blocking_revision_chapters(heavy)
        normalized = _compile_executable_revision_contracts(
            contracts,
            blocking_chapters=blocking_chapters,
        )
        chapters: list[int] = []
        for contract in normalized:
            chapter = int(contract.get("chapter_id") or 0)
            if chapter < start or chapter > end:
                raise ValueError(f"revision_contract_chapter_out_of_range:{chapter}")
            issues = _contract_issues(contract, chapter=chapter)
            if issues:
                raise ValueError(issues[0])
            if chapter in chapters:
                raise ValueError(f"multiple_revision_contracts_for_chapter:{chapter}")
            chapters.append(chapter)
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
            "source_proposal_count": len(contracts),
            "blocking_chapters": sorted(blocking_chapters),
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
            "source_proposal_count": len(contracts) if isinstance(contracts, list) else 0,
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
