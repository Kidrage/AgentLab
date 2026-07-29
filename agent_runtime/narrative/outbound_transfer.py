"""Approval contract for sending minimal Crown context to an external service."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
import hashlib
import json
import re

from agent_runtime.outbound_context import build_outbound_context_manifest

_PROJECT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,127}$")
_TASK_ID = re.compile(r"^task[_-][A-Za-z0-9][A-Za-z0-9_-]{0,80}$")
_CANONICAL_ROOTS = frozenset(
    {"production", "project_brain", "runs", "runtime"}
)


def _parse_future_expiry(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed if parsed > datetime.now(timezone.utc) else None


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
