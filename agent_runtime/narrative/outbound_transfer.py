"""Approval contract for sending minimal Crown context to an external service."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
import hashlib
import json
import re

import yaml

from agent_runtime.outbound_context import build_outbound_context_manifest
from agent_runtime.project_truth import ProjectTruthStore

_PROJECT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,127}$")
_TASK_ID = re.compile(r"^task[_-][A-Za-z0-9][A-Za-z0-9_-]{0,80}$")
_CANONICAL_ROOTS = frozenset(
    {"production", "project_brain", "runs", "runtime"}
)
_AUTO_APPROVAL_AUTHORITY_KEY = "policies.outbound_context_auto_approval"
_DETACHED_ACCEPTANCE_MODE = "dual_review_hard_gate_auto_project"
_DETACHED_REVIEW_ROLES = frozenset(
    {"senior_editor", "reader_simulation_panel"}
)


def acceptance_boundary_issues(
    policy: dict[str, Any],
    authorization: dict[str, Any],
    constraints: dict[str, Any],
) -> list[str]:
    responsibility = authorization.get("user_responsibility")
    requires_user = constraints.get(
        "state_projection_requires_user_acceptance"
    )
    manual_acceptance = (
        responsibility == "candidate_acceptance_only"
        and requires_user is True
    )
    detached = policy.get("automatic_acceptance")
    detached = detached if isinstance(detached, dict) else {}
    required_roles = detached.get("required_review_roles")
    detached_acceptance = (
        responsibility == "final_part_acceptance_only"
        and requires_user is False
        and detached.get("mode") == _DETACHED_ACCEPTANCE_MODE
        and isinstance(required_roles, list)
        and set(required_roles) == _DETACHED_REVIEW_ROLES
        and detached.get("require_all_hard_gates") is True
        and detached.get("exception_action") == "pause"
        and detached.get("user_acceptance_scope") == "final_part_only"
    )
    issues: list[str] = []
    if (
        authorization.get("mode") != "policy_auto_approve"
        or authorization.get("user_authorized") is not True
        or not (manual_acceptance or detached_acceptance)
    ):
        issues.append("auto_approval_user_authorization_invalid")
    if (
        constraints.get("candidate_only") is not True
        or constraints.get("fallback_allowed") is not False
        or not (manual_acceptance or detached_acceptance)
    ):
        issues.append("auto_approval_acceptance_boundary_invalid")
    return issues


def _parse_future_expiry(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed if parsed > datetime.now(timezone.utc) else None


def evaluate_narrative_auto_approval(
    agentlab_root: Path,
    *,
    project: str,
    task_id: str,
    recipient: str,
    role: str,
    purpose: str,
    source_paths: Iterable[Path],
    expires_at: str,
) -> dict[str, Any]:
    """Evaluate one user-owned, project-scoped outbound approval policy."""

    root = Path(agentlab_root).resolve()
    project_root = (root / "projects" / project).resolve()
    policy_path = project_root / "production" / "outbound_context_policy.yml"
    issues: list[str] = []
    if policy_path.is_symlink() or not policy_path.is_file():
        issues.append("auto_approval_policy_missing")
        policy_bytes = b""
        policy: dict[str, Any] = {}
    else:
        try:
            policy_bytes = policy_path.read_bytes()
            loaded = yaml.safe_load(policy_bytes.decode("utf-8")) or {}
            policy = loaded if isinstance(loaded, dict) else {}
        except (OSError, UnicodeDecodeError, yaml.YAMLError):
            policy_bytes = b""
            policy = {}
            issues.append("auto_approval_policy_invalid")

    authorization = policy.get("authorization")
    authorization = authorization if isinstance(authorization, dict) else {}
    constraints = policy.get("constraints")
    constraints = constraints if isinstance(constraints, dict) else {}
    if policy.get("schema_version") != "narrative-outbound-auto-approval/v1":
        issues.append("auto_approval_schema_invalid")
    if policy.get("status") != "active" or policy.get("project") != project:
        issues.append("auto_approval_policy_inactive_or_project_mismatch")
    issues.extend(acceptance_boundary_issues(policy, authorization, constraints))

    policy_sha256 = (
        hashlib.sha256(policy_bytes).hexdigest() if policy_bytes else None
    )
    truth_snapshot_id: str | None = None
    truth_revision_id: str | None = None
    try:
        truth = ProjectTruthStore(project_root)
        truth.audit()
        snapshot = truth.current()
        truth_snapshot_id = snapshot.snapshot_id
        authority_revision = snapshot.resources.get(
            _AUTO_APPROVAL_AUTHORITY_KEY
        )
        authority = (
            authority_revision.content
            if authority_revision is not None
            and isinstance(authority_revision.content, dict)
            else {}
        )
        truth_revision_id = (
            authority_revision.revision_id
            if authority_revision is not None
            else None
        )
        if (
            authority.get("schema_version")
            != "narrative-outbound-auto-approval-authority/v1"
            or authority.get("status") != "active"
            or authority.get("project") != project
            or authority.get("policy_path")
            != "production/outbound_context_policy.yml"
            or authority.get("policy_sha256") != policy_sha256
            or not str(authority.get("authorized_by") or "").strip()
            or authority_revision is None
            or authority_revision.actor_id
            != authority.get("authorized_by")
        ):
            issues.append("auto_approval_truth_authority_invalid")
    except (OSError, ValueError, RuntimeError):
        issues.append("auto_approval_truth_authority_invalid")

    allowed_recipients = constraints.get("allowed_recipients")
    allowed_roles = constraints.get("allowed_roles")
    allowed_task_prefixes = constraints.get("allowed_task_prefixes")
    allowed_source_roots = constraints.get("allowed_source_roots")
    if not isinstance(allowed_recipients, list) or recipient not in allowed_recipients:
        issues.append("recipient_not_allowed")
    if not isinstance(allowed_roles, list) or role not in allowed_roles:
        issues.append("role_not_allowed")
    if (
        not isinstance(allowed_task_prefixes, list)
        or not any(
            isinstance(prefix, str) and task_id.startswith(prefix)
            for prefix in allowed_task_prefixes
        )
    ):
        issues.append("task_not_allowed")
    if not purpose.strip():
        issues.append("purpose_required")

    expiry = _parse_future_expiry(expires_at)
    max_expiry_hours = constraints.get("max_expiry_hours")
    if (
        expiry is None
        or not isinstance(max_expiry_hours, int)
        or isinstance(max_expiry_hours, bool)
        or max_expiry_hours < 1
        or (expiry - datetime.now(timezone.utc)).total_seconds()
        > max_expiry_hours * 3600
    ):
        issues.append("expiry_outside_policy")

    selected_sources = list(source_paths)
    max_source_files = constraints.get("max_source_files")
    max_total_bytes = constraints.get("max_total_bytes")
    if (
        not isinstance(max_source_files, int)
        or isinstance(max_source_files, bool)
        or max_source_files < 1
        or len(selected_sources) > max_source_files
    ):
        issues.append("source_count_outside_policy")
    total_bytes = 0
    for index, raw in enumerate(selected_sources):
        selected = Path(raw)
        if selected.is_symlink():
            issues.append(f"source_symlink_forbidden:{index}")
            continue
        try:
            resolved = selected.resolve(strict=True)
            relative = resolved.relative_to(project_root)
        except (OSError, ValueError):
            issues.append(f"source_outside_project:{index}")
            continue
        if (
            not relative.parts
            or not isinstance(allowed_source_roots, list)
            or relative.parts[0] not in allowed_source_roots
        ):
            issues.append(f"source_root_not_allowed:{relative.as_posix()}")
            continue
        if not resolved.is_file():
            issues.append(f"source_not_regular_file:{index}")
            continue
        try:
            total_bytes += resolved.stat().st_size
        except OSError:
            issues.append(f"source_unreadable:{index}")
    if (
        not isinstance(max_total_bytes, int)
        or isinstance(max_total_bytes, bool)
        or max_total_bytes < 1
        or total_bytes > max_total_bytes
    ):
        issues.append("source_bytes_outside_policy")

    return {
        "schema_version": "narrative-outbound-auto-approval-result/v1",
        "status": "pass" if not issues else "blocked",
        "execution_allowed": not issues,
        "project": project,
        "task_id": task_id,
        "policy_path": policy_path.relative_to(root).as_posix(),
        "policy_sha256": policy_sha256,
        "truth_snapshot_id": truth_snapshot_id,
        "truth_authority_revision_id": truth_revision_id,
        "source_count": len(selected_sources),
        "source_bytes": total_bytes,
        "issues": issues,
    }


def build_narrative_outbound_transfer_contract(
    agentlab_root: Path,
    *,
    project: str,
    task_id: str,
    recipient: str,
    purpose: str,
    minimal_fragment: str,
    source_paths: Iterable[Path],
    expires_at: str,
    role: str = "research_style_curator",
    defer_exact_payload_to_execution: bool = False,
    source_inventory_required: bool = True,
) -> dict[str, Any]:
    """Fail closed unless one exact, minimal, expiring transfer is approved."""

    issues: list[str] = []
    if not _PROJECT_ID.fullmatch(project):
        issues.append("project_id_invalid")
    if not _TASK_ID.fullmatch(task_id):
        issues.append("task_id_invalid")
    if not recipient.strip():
        issues.append("recipient_required")
    if not purpose.strip():
        issues.append("purpose_required")
    if not minimal_fragment.strip():
        issues.append("minimal_fragment_required")
    if _parse_future_expiry(expires_at) is None:
        issues.append("expires_at_must_be_future_timezone_aware")

    root = Path(agentlab_root).resolve()
    project_root = root / "projects" / project
    resolved_sources: list[Path] = []
    for index, raw in enumerate(source_paths):
        selected = Path(raw)
        if selected.is_symlink():
            issues.append(f"source_symlink_forbidden:{index}")
            continue
        resolved = selected.resolve()
        try:
            relative = resolved.relative_to(project_root.resolve())
        except ValueError:
            issues.append(f"source_outside_project:{index}")
            continue
        if not relative.parts or relative.parts[0] not in _CANONICAL_ROOTS:
            issues.append(f"source_not_canonical:{relative.as_posix()}")
            continue
        resolved_sources.append(resolved)
    if source_inventory_required and not resolved_sources:
        issues.append("canonical_source_inventory_required")
    if issues:
        return {
            "schema_version": "narrative-outbound-transfer/v1",
            "status": "blocked",
            "execution_allowed": False,
            "issues": issues,
        }

    payload_sha256 = hashlib.sha256(
        minimal_fragment.encode("utf-8")
    ).hexdigest()
    source_inventory = [
        {
            "path": path.relative_to(root).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in resolved_sources
    ]
    scope_identity = {
        "project": project,
        "task_id": task_id,
        "recipient": recipient.strip(),
        "purpose": purpose.strip(),
        "payload_sha256": payload_sha256,
        "expires_at": expires_at,
        "role": role,
        "source_inventory": source_inventory,
        "source_inventory_required": source_inventory_required,
    }
    scope_sha256 = hashlib.sha256(
        json.dumps(
            scope_identity,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    outbound = build_outbound_context_manifest(
        root,
        item_id=f"narrative-{project}-{task_id}-{payload_sha256[:16]}",
        role=role,
        provider_surface=recipient.strip(),
        payload_kind="crown_minimal_fragment",
        payload_text=minimal_fragment,
        source_paths=resolved_sources,
        private_context=True,
        exact_payload=True,
        sealed_context=True,
        execution_workspace_isolated=True,
        approval_required=True,
        approval_granted=None,
        approval_payload_sha256_required=(
            not defer_exact_payload_to_execution
        ),
        approved_payload_sha256=None,
        approval_scope_sha256_required=True,
        approval_scope_contract_valid=True,
        expected_scope_sha256=scope_sha256,
        approved_scope_sha256=None,
        source_inventory_required=source_inventory_required,
    )
    return {
        "schema_version": "narrative-outbound-transfer/v1",
        "status": outbound["status"],
        "execution_allowed": outbound["execution_allowed"],
        "project": project,
        "task_id": task_id,
        "recipient": recipient.strip(),
        "purpose": purpose.strip(),
        "minimal_fragment": {
            "bytes": len(minimal_fragment.encode("utf-8")),
            "sha256": payload_sha256,
            "content_stored_in_contract": False,
        },
        "expires_at": expires_at,
        "request_scope": {
            **scope_identity,
            "sha256": scope_sha256,
        },
        "approval": {
            "required": True,
            "granted": outbound["authorization"]["approval_observed"],
            "payload_sha256_matched": outbound["authorization"][
                "payload_sha256_matched"
            ],
            "scope_sha256_matched": outbound["authorization"][
                "scope_sha256_matched"
            ],
        },
        "outbound_context_manifest": outbound,
        "issues": list(outbound["issues"]),
    }
