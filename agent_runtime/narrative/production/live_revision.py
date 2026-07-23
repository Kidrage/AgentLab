"""Validation core for hash-bound live narrative revision attempts."""

from __future__ import annotations

from datetime import datetime
import hashlib
from pathlib import Path
import re
from typing import Any

import yaml

from agent_runtime.narrative.production.revision_attempts import (
    validate_revision_attempt_receipt,
)


_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_SOURCE_REQUEST_NAME = "narrative_v2_writer_request.yml"
_SOURCE_OUTPUT_NAME = "writer_v2_output_contract.yml"
_SOURCE_AUDIT_NAME = "deterministic_candidate_audit_v2.yml"
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


def revision_lease_issue(
    request: dict[str, Any],
    *,
    now: datetime | None = None,
) -> str:
    """Return the fail-closed lease issue for one revision request."""
    raw = str(request.get("lease_expires_at") or "").strip()
    try:
        expires_at = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return "live_writer_revision_lease_expiry_invalid"
    if expires_at.tzinfo is None:
        return "live_writer_revision_lease_expiry_invalid"
    observed_now = now or datetime.now(expires_at.tzinfo)
    if observed_now.tzinfo is None:
        return "live_writer_revision_lease_expiry_invalid"
    if observed_now.astimezone(expires_at.tzinfo) >= expires_at:
        return "live_writer_revision_lease_expired"
    return ""


def revision_contract_issues(
    contract: dict[str, Any],
    *,
    chapter_id: int,
    source_candidate_sha256: str,
    triggering_audit_sha256: str,
    prefix: str = "live_writer_revision",
) -> list[str]:
    """Validate one executable contract against its exact source evidence."""
    issues: list[str] = []
    if contract.get("schema_version") != 1 or contract.get("chapter_id") != chapter_id:
        issues.append(f"{prefix}_contract_identity_mismatch")
    if contract.get("rewrite_scope") not in {"scene", "chapter"}:
        issues.append(f"{prefix}_contract_scope_invalid")
    if any(not contract.get(key) for key in _CONTRACT_SCALAR_FIELDS):
        issues.append(f"{prefix}_contract_incomplete")
    for key in _CONTRACT_LIST_FIELDS:
        if not isinstance(contract.get(key), list) or not contract.get(key):
            issues.append(f"{prefix}_contract_incomplete")
            break
    if contract.get("source_candidate_sha256") != source_candidate_sha256:
        issues.append(f"{prefix}_contract_source_hash_mismatch")
    if contract.get("triggering_audit_sha256") != triggering_audit_sha256:
        issues.append(f"{prefix}_contract_audit_hash_mismatch")
    return list(dict.fromkeys(issues))


def validate_live_revision_request(
    *,
    root: Path,
    project: str,
    task_id: str,
    chapter_id: int,
    request: dict[str, Any],
    paths: dict[str, Path | None],
    now: datetime | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Validate lineage, evidence, lease, and context inheritance in one call."""
    issues: list[str] = []
    for key in (
        "candidate_set_id",
        "source_job_id",
        "source_run_id",
        "triggered_by_audit_id",
        "attempt_id",
        "lease_token",
        "fencing_token",
    ):
        if not _IDENTIFIER_RE.fullmatch(str(request.get(key) or "")):
            issues.append(f"live_writer_revision_identity_invalid:{key}")
    rewrite_count = request.get("automatic_rewrite_count")
    if isinstance(rewrite_count, bool) or rewrite_count not in (0, 1):
        issues.append("live_writer_revision_automatic_rewrite_limit_reached")
    lease_issue = revision_lease_issue(request, now=now)
    if lease_issue:
        issues.append(lease_issue)
    source_run_id = str(request.get("source_run_id") or "")
    audit_id = str(request.get("triggered_by_audit_id") or "")
    if source_run_id == task_id:
        issues.append("live_writer_revision_must_use_distinct_run")
    if audit_id == source_run_id:
        issues.append("live_writer_revision_audit_must_use_distinct_run")
    if any(path is None for path in paths.values()):
        return {}, list(dict.fromkeys(issues))

    source_run = root / "projects" / project / "runs" / source_run_id
    audit_run = root / "projects" / project / "runs" / audit_id
    expected_paths = {
        "source_writer_request": source_run / _SOURCE_REQUEST_NAME,
        "source_candidate": source_run / "fiction_draft.md",
        "triggering_audit": audit_run / _SOURCE_AUDIT_NAME,
    }
    for key, expected in expected_paths.items():
        if paths[key] != expected.resolve():
            issues.append(f"live_writer_revision_source_path_mismatch:{key}")
    revision_contract_path = paths["revision_contract"]
    candidate_root = (root / "projects" / project / "candidates").resolve()
    try:
        revision_contract_path.relative_to(candidate_root)  # type: ignore[union-attr]
    except ValueError:
        issues.append("live_writer_revision_contract_outside_candidates")

    source_request_path = paths["source_writer_request"]
    source_candidate = paths["source_candidate"]
    triggering_audit = paths["triggering_audit"]
    if (
        source_request_path is None
        or source_candidate is None
        or triggering_audit is None
        or revision_contract_path is None
    ):
        return {}, list(dict.fromkeys(issues))
    source_request_raw, source_request = _read_mapping(
        source_request_path,
        "live_writer_revision_source_request_invalid",
        issues,
    )
    expected_source_identity = {
        "schema_version": 1,
        "job_kind": "narrative_generation",
        "run_mode": "generate_candidate",
        "project": project,
        "task_id": source_run_id,
        "chapter_id": chapter_id,
        "candidate_only": True,
        "production_modified": False,
    }
    if any(source_request.get(key) != value for key, value in expected_source_identity.items()):
        issues.append("live_writer_revision_source_request_identity_mismatch")
    try:
        from agent_runtime.narrative.production.live_writer_preflight import (
            load_validated_workflow_plan_data,
        )

        source_plan = load_validated_workflow_plan_data(
            agentlab_root=root,
            project=project,
            task_id=source_run_id,
            plan_path=source_run / "workflow_plan.yml",
        )
        source_request_activated = str(
            source_plan.get("sealed_user_request_content") or ""
        ).encode("utf-8") == source_request_raw
    except (OSError, RuntimeError, TypeError, ValueError):
        source_request_activated = False
    if not source_request_activated:
        issues.append("live_writer_revision_source_request_not_activated")
    for key in _CONTEXT_FIELDS:
        if request.get(key) != source_request.get(key):
            issues.append(f"live_writer_revision_source_context_mismatch:{key}")

    try:
        source_candidate_sha256 = hashlib.sha256(source_candidate.read_bytes()).hexdigest()
    except OSError:
        source_candidate_sha256 = ""
        issues.append("live_writer_revision_source_candidate_unreadable")
    _raw, source_output = _read_mapping(
        source_run / _SOURCE_OUTPUT_NAME,
        "live_writer_revision_source_output_contract_invalid",
        issues,
    )
    if (
        source_output.get("status") != "pass"
        or source_output.get("task_id") != source_run_id
        or source_output.get("prose_sha256") != source_candidate_sha256
        or source_output.get("candidate_only") is not True
        or source_output.get("production_modified") is not False
    ):
        issues.append("live_writer_revision_source_output_contract_mismatch")
    audit_raw, audit = _read_mapping(
        triggering_audit,
        "live_writer_revision_triggering_audit_invalid",
        issues,
    )
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
        issues.append("live_writer_revision_audit_not_actionable")
    if audit.get("candidate_sha256") != source_candidate_sha256:
        issues.append("live_writer_revision_audit_source_hash_mismatch")
    _raw, contract = _read_mapping(
        revision_contract_path,
        "live_writer_revision_contract_invalid",
        issues,
    )
    issues.extend(
        revision_contract_issues(
            contract,
            chapter_id=chapter_id,
            source_candidate_sha256=source_candidate_sha256,
            triggering_audit_sha256=hashlib.sha256(audit_raw).hexdigest()
            if audit_raw
            else "",
        )
    )
    issues.extend(
        validate_revision_attempt_receipt(
            root=root,
            project=project,
            request=request,
            receipt_path=paths.get("attempt_receipt"),
        )
    )
    return contract, list(dict.fromkeys(issues))


def _read_mapping(
    path: Path,
    issue: str,
    issues: list[str],
) -> tuple[bytes, dict[str, Any]]:
    try:
        raw = path.read_bytes()
        value = yaml.safe_load(raw.decode("utf-8")) or {}
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        issues.append(issue)
        return b"", {}
    if not isinstance(value, dict):
        issues.append(issue)
        return raw, {}
    return raw, value
