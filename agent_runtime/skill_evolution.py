"""Skill evolution scaffolding for AgentLab.

This module intentionally avoids network access and installation. It defines the
local registry, request queue, trace-to-skill candidate files, cost preview
shape, and complete skill lifecycle (pending_user_approval → approved → staging →
validated → active → retired).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import re
import shutil

import yaml

from atomic_io import atomic_write_yaml, safe_read_yaml
from cost_tracker import estimate_cost


DEFAULT_TOKEN_PHASES = {
    "discovery_tokens": 8000,
    "source_reading_tokens": 60000,
    "distillation_tokens": 16000,
    "adaptation_tokens": 12000,
    "validation_tokens": 24000,
    "audit_tokens": 6000,
    "storage_indexing_tokens": 1000,
}

VALID_STATUSES = {
    "pending_user_approval",
    "rejected",
    "approved",
    "staging",
    "validated",
    "active",
    "retired",
}

ALLOWED_TRANSITIONS = {
    "pending_user_approval": {"approved", "rejected"},
    "approved": {"staging"},
    "staging": {"validated"},
    "validated": {"active"},
    "active": {"retired"},
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return slug[:48] or "skill"


def _timestamp_id(prefix: str, name: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    return f"{prefix}_{stamp}_{_slug(name)}"


def _assert_transition(from_status: str, to_status: str) -> None:
    allowed = ALLOWED_TRANSITIONS.get(from_status, set())
    if to_status not in allowed:
        raise ValueError(
            f"Invalid transition: '{from_status}' → '{to_status}'. "
            f"Allowed transitions from '{from_status}': {sorted(allowed) if allowed else 'none'}."
        )


# ── registry paths ───────────────────────────────────────────────

def skill_registry_path(agentlab_root: Path) -> Path:
    return agentlab_root / "skills" / "registry.yml"


def skill_staging_dir(agentlab_root: Path) -> Path:
    return agentlab_root / "skills" / "staging"


def skill_active_dir(agentlab_root: Path) -> Path:
    return agentlab_root / "skills" / "active"


def skill_retired_dir(agentlab_root: Path) -> Path:
    return agentlab_root / "skills" / "retired"


# ── registry I/O ─────────────────────────────────────────────────

def default_skill_registry() -> dict[str, Any]:
    now = utc_now()
    return {
        "schema_version": 1,
        "skills": [],
        "retired_skills": [],
        "metadata": {
            "owner": "AgentLab",
            "status": "local_lifecycle_mvp",
            "created_at": now,
            "updated_at": now,
            "notes": "Local skill lifecycle MVP. External search and real sandbox execution are not implemented.",
        },
    }


def load_skill_registry(agentlab_root: Path) -> dict[str, Any]:
    data = safe_read_yaml(skill_registry_path(agentlab_root), default={}) or {}
    if not isinstance(data, dict) or not data:
        data = default_skill_registry()
    data.setdefault("schema_version", 1)
    data.setdefault("skills", [])
    data.setdefault("retired_skills", [])
    data.setdefault("metadata", {})
    return data


def write_skill_registry(agentlab_root: Path, registry: dict[str, Any]) -> Path:
    registry.setdefault("metadata", {})["updated_at"] = utc_now()
    path = skill_registry_path(agentlab_root)
    atomic_write_yaml(path, registry)
    return path


def save_skill_registry(agentlab_root: Path, registry: dict[str, Any]) -> Path:
    return write_skill_registry(agentlab_root, registry)


def ensure_skill_registry(agentlab_root: Path) -> Path:
    path = skill_registry_path(agentlab_root)
    if not path.exists():
        save_skill_registry(agentlab_root, default_skill_registry())
    return path


# ── request paths ────────────────────────────────────────────────

def skill_request_dir(agentlab_root: Path, project: str) -> Path:
    return agentlab_root / "projects" / project / "skill_requests"


def skill_candidate_dir(agentlab_root: Path, project: str, task_id: str) -> Path:
    return agentlab_root / "projects" / project / "runs" / task_id / "skill_candidates"


# ── cost estimation ──────────────────────────────────────────────

def estimate_skill_learning_cost(
    agentlab_root: Path,
    *,
    provider: str = "deepseek",
    model: str = "deepseek-v4-pro",
    validation_runs: int = 3,
    token_phases: dict[str, int] | None = None,
) -> dict[str, Any]:
    phases = dict(DEFAULT_TOKEN_PHASES)
    if token_phases:
        phases.update({k: int(v) for k, v in token_phases.items() if v is not None})

    validation_tokens = max(0, phases.get("validation_tokens", 0)) * max(1, validation_runs)
    input_tokens = (
        phases.get("discovery_tokens", 0)
        + phases.get("source_reading_tokens", 0)
        + int(validation_tokens * 0.7)
        + phases.get("storage_indexing_tokens", 0)
    )
    output_tokens = (
        phases.get("distillation_tokens", 0)
        + phases.get("adaptation_tokens", 0)
        + int(validation_tokens * 0.3)
        + phases.get("audit_tokens", 0)
    )
    cost = estimate_cost(agentlab_root, model, input_tokens, output_tokens, provider=provider)
    return {
        "provider": provider,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "validation_runs": validation_runs,
        "estimated_cost": cost.get("estimated_cost"),
        "cost_currency": cost.get("cost_currency"),
        "exact_cost_available": cost.get("exact_cost_available"),
        "pricing_source": cost.get("pricing_source"),
        "token_phases": phases,
    }


# ── skill adoption request ───────────────────────────────────────

def build_skill_adoption_request(
    agentlab_root: Path,
    *,
    project: str,
    skill_name: str,
    source: str,
    purpose: str,
    source_type: str = "manual",
    provider: str = "deepseek",
    model: str = "deepseek-v4-pro",
    validation_runs: int = 3,
    risk: dict[str, Any] | None = None,
    applies_to: list[str] | None = None,
) -> dict[str, Any]:
    cost_preview = estimate_skill_learning_cost(
        agentlab_root,
        provider=provider,
        model=model,
        validation_runs=validation_runs,
    )
    request_id = _timestamp_id("skill_req", skill_name)
    return {
        "schema_version": 1,
        "id": request_id,
        "project": project,
        "created_at": utc_now(),
        "source": {
            "type": source_type,
            "uri": source,
        },
        "skill_name": skill_name,
        "purpose": purpose,
        "risk": {
            "has_scripts": False,
            "requires_network": source_type in {"github", "skill_hub"},
            "modifies_files": True,
            "permission_level": "medium",
            **(risk or {}),
        },
        "expected_benefit": {
            "applies_to": applies_to or [],
            "expected_token_saving": "unknown",
            "expected_quality_gain": "unknown",
        },
        "cost_preview": cost_preview,
        "status": "pending_user_approval",
    }


def write_skill_adoption_request(agentlab_root: Path, request: dict[str, Any]) -> Path:
    project = request["project"]
    request_id = request.get("id") or _timestamp_id("skill_req", request.get("skill_name", "skill"))
    request["id"] = request_id
    path = skill_request_dir(agentlab_root, project) / f"{request_id}.yml"
    atomic_write_yaml(path, request)
    try:
        from webhook_dispatcher import dispatch_event

        dispatch_event(
            agentlab_root,
            event="SKILL_REQUEST_PENDING",
            project=project,
            summary=f"Skill request pending: {request.get('skill_name', request_id)}",
            reason=request.get("purpose", ""),
            links={"skill_request": str(path)},
        )
    except Exception:
        pass
    return path


# ── load / list skill requests ───────────────────────────────────

def load_skill_requests(
    agentlab_root: Path,
    project: str,
    *,
    status: str | None = None,
) -> list[dict[str, Any]]:
    root = skill_request_dir(agentlab_root, project)
    if not root.exists():
        return []
    requests: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.yml")):
        data = safe_read_yaml(path, default={}) or {}
        if not isinstance(data, dict):
            continue
        data.setdefault("_path", str(path))
        if status is None or data.get("status") == status:
            requests.append(data)
    return requests


def list_skill_requests(agentlab_root: Path, project: str) -> list[dict[str, Any]]:
    """List all skill adoption requests for a project."""
    return load_skill_requests(agentlab_root, project)


def _load_single_skill_request(agentlab_root: Path, project: str, request_id: str) -> dict[str, Any]:
    """Load a single skill request by id.  Raises FileNotFoundError if missing."""
    path = skill_request_dir(agentlab_root, project) / f"{request_id}.yml"
    if not path.exists():
        raise FileNotFoundError(f"Skill request not found: {request_id} at {path}")
    data = safe_read_yaml(path, default={}) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Corrupt skill request file: {path}")
    data["_path"] = str(path)
    return data


def _save_skill_request(agentlab_root: Path, request: dict[str, Any]) -> Path:
    """Save a skill request dict back to its file.  Expects _path or project+id."""
    project = request["project"]
    request_id = request.get("id")
    if not request_id:
        raise ValueError("Skill request is missing 'id' field.")
    path = skill_request_dir(agentlab_root, project) / f"{request_id}.yml"
    atomic_write_yaml(path, request)
    return path


# ── lifecycle transitions ────────────────────────────────────────

def approve_skill_request(agentlab_root: Path, project: str, request_id: str) -> dict[str, Any]:
    """Approve a pending skill request, moving it from pending_user_approval → approved."""
    req = _load_single_skill_request(agentlab_root, project, request_id)
    current = req.get("status", "")
    _assert_transition(current, "approved")
    req["status"] = "approved"
    req["approved_at"] = utc_now()
    _save_skill_request(agentlab_root, req)
    return req


def reject_skill_request(agentlab_root: Path, project: str, request_id: str, reason: str) -> dict[str, Any]:
    """Reject a pending skill request, moving it from pending_user_approval → rejected."""
    req = _load_single_skill_request(agentlab_root, project, request_id)
    current = req.get("status", "")
    _assert_transition(current, "rejected")
    req["status"] = "rejected"
    req["rejected_at"] = utc_now()
    req["rejection_reason"] = reason
    _save_skill_request(agentlab_root, req)
    return req


def stage_skill_request(agentlab_root: Path, project: str, request_id: str) -> dict[str, Any]:
    """Move an approved request into the staging area (approved → staging).

    Creates the staging directory: skills/staging/<skill_id>/
    with metadata.yml and adapted_skill.md.
    The skill_id is derived from the request's skill_name.
    """
    req = _load_single_skill_request(agentlab_root, project, request_id)
    current = req.get("status", "")
    _assert_transition(current, "staging")

    skill_name = req.get("skill_name", "unnamed")
    skill_id = _timestamp_id("skill", skill_name)

    # Create staging directory
    staging_root = skill_staging_dir(agentlab_root)
    staging_dir = staging_root / skill_id
    staging_dir.mkdir(parents=True, exist_ok=True)

    # Write metadata.yml
    metadata = {
        "schema_version": 1,
        "skill_id": skill_id,
        "skill_name": skill_name,
        "name": req.get("name") or skill_name,
        "source": req.get("source", {}),
        "purpose": req.get("purpose", ""),
        "summary": req.get("summary") or req.get("purpose", ""),
        "triggers": req.get("triggers") or req.get("expected_benefit", {}).get("applies_to", []) or [skill_name],
        "applies_to": req.get("applies_to") or req.get("expected_benefit", {}).get("applies_to", []),
        "load_tokens": req.get("load_tokens", req.get("token_profile", {}).get("load_cost_tokens", 1200)),
        "expected_saving_tokens": req.get("expected_saving_tokens", 3000),
        "risk_level": req.get("risk_level") or req.get("risk", {}).get("permission_level", "medium"),
        "permissions": req.get("permissions") or req.get("risk", {}),
        "confidence": req.get("confidence", 0.5),
        "project": project,
        "request_id": request_id,
        "staged_at": utc_now(),
        "status": "staging",
    }
    atomic_write_yaml(staging_dir / "metadata.yml", metadata)

    # Write adapted_skill.md (a lightweight adaptation placeholder)
    adapted_md = (
        f"# Adapted Skill: {skill_name}\n\n"
        f"Skill ID: {skill_id}\n\n"
        f"Source: {req.get('source', {}).get('uri', 'unknown')}\n\n"
        f"Purpose: {req.get('purpose', '')}\n\n"
        f"## Adaptation Notes\n\n"
        f"This skill was staged from request {request_id}.\n"
        f"Real GitHub search and package parsing are not yet implemented.\n"
    )
    (staging_dir / "adapted_skill.md").write_text(adapted_md, encoding="utf-8")

    # Write validation_plan.yml placeholder
    validation_plan = {
        "schema_version": 1,
        "skill_id": skill_id,
        "checks": ["metadata_completeness", "adapted_skill_readable"],
        "mode": "fake_sandbox",
        "created_at": utc_now(),
    }
    atomic_write_yaml(staging_dir / "validation_plan.yml", validation_plan)

    # Update request
    req["status"] = "staging"
    req["staged_at"] = utc_now()
    req["skill_id"] = skill_id
    _save_skill_request(agentlab_root, req)

    return {
        "request_id": request_id,
        "skill_id": skill_id,
        "staging_dir": str(staging_dir),
        "status": "staging",
    }


def validate_staged_skill(agentlab_root: Path, skill_id: str, fake_sandbox: bool = True) -> dict[str, Any]:
    """Run fake sandbox validation on a staged skill (staging → validated).

    Does NOT execute external code.  Reads metadata.yml and adapted_skill.md,
    creates sandbox_report.yml, marks the staged skill as validated.
    """
    staging_dir = skill_staging_dir(agentlab_root) / skill_id
    if not staging_dir.exists():
        raise FileNotFoundError(f"Staging directory not found: {staging_dir}")

    metadata_path = staging_dir / "metadata.yml"
    adapted_path = staging_dir / "adapted_skill.md"

    if not metadata_path.exists():
        raise FileNotFoundError(f"metadata.yml missing in staging: {staging_dir}")
    if not adapted_path.exists():
        raise FileNotFoundError(f"adapted_skill.md missing in staging: {staging_dir}")

    metadata = safe_read_yaml(metadata_path, default={}) or {}
    current_status = metadata.get("status", "")
    if current_status not in {"staging", ""}:
        raise ValueError(
            f"Cannot validate skill in status '{current_status}'. "
            f"Only staged skills can be validated."
        )

    checked_files = []
    risk_level = "low"

    # Read files for completeness check (no execution)
    try:
        adapted_content = adapted_path.read_text(encoding="utf-8")
        checked_files.append({"file": "adapted_skill.md", "readable": True, "size_bytes": len(adapted_content)})
        if len(adapted_content.strip()) < 10:
            risk_level = "high"
    except Exception:
        checked_files.append({"file": "adapted_skill.md", "readable": False, "error": "unreadable"})
        risk_level = "high"

    try:
        _ = safe_read_yaml(metadata_path)
        checked_files.append({"file": "metadata.yml", "parsable": True})
    except Exception:
        checked_files.append({"file": "metadata.yml", "parsable": False, "error": "unparsable"})
        risk_level = "high"

    sandbox_report = {
        "schema_version": 1,
        "skill_id": skill_id,
        "validated": True,
        "mode": "fake_sandbox" if fake_sandbox else "sandbox",
        "checked_files": checked_files,
        "risk_level": risk_level,
        "created_at": utc_now(),
        "notes": "Fake sandbox validation — no external code was executed.",
    }
    atomic_write_yaml(staging_dir / "sandbox_report.yml", sandbox_report)

    # Update metadata status
    metadata["status"] = "validated"
    metadata["validated_at"] = utc_now()
    atomic_write_yaml(metadata_path, metadata)

    # Update the original skill request status if we can find it
    request_id = metadata.get("request_id", "")
    project = metadata.get("project", "")
    if request_id and project:
        try:
            req = _load_single_skill_request(agentlab_root, project, request_id)
            if req.get("status") == "staging":
                req["status"] = "validated"
                req["validated_at"] = utc_now()
                _save_skill_request(agentlab_root, req)
        except FileNotFoundError:
            pass  # request file may have been moved/deleted

    return {
        "skill_id": skill_id,
        "status": "validated",
        "sandbox_report": str(staging_dir / "sandbox_report.yml"),
        "risk_level": risk_level,
        "checked_files_count": len(checked_files),
    }


def promote_skill(agentlab_root: Path, skill_id: str) -> dict[str, Any]:
    """Promote a validated skill to active (validated → active).

    Copies normalized skill content into skills/active/<skill_id>/,
    creates SKILL.md, validation_report.yml, empty usage_ledger.yml,
    updates skills/registry.yml, sets status to active.
    """
    staging_dir = skill_staging_dir(agentlab_root) / skill_id
    if not staging_dir.exists():
        raise FileNotFoundError(f"Staging directory not found: {staging_dir}")

    metadata_path = staging_dir / "metadata.yml"
    metadata = safe_read_yaml(metadata_path, default={}) or {}
    current_status = metadata.get("status", "")

    # Must be validated
    if current_status != "validated":
        raise ValueError(
            f"Cannot promote skill in status '{current_status}'. "
            f"Only validated skills can be promoted to active."
        )

    # Read adapted_skill.md content
    adapted_path = staging_dir / "adapted_skill.md"
    adapted_content = adapted_path.read_text(encoding="utf-8") if adapted_path.exists() else ""

    # Read sandbox report
    sandbox_path = staging_dir / "sandbox_report.yml"
    sandbox_report = safe_read_yaml(sandbox_path, default={}) or {}

    skill_name = metadata.get("skill_name", skill_id)

    # Create active directory
    active_dir = skill_active_dir(agentlab_root) / skill_id
    active_dir.mkdir(parents=True, exist_ok=True)

    # Write SKILL.md
    skill_md_content = (
        f"# Skill: {skill_name}\n\n"
        f"Skill ID: {skill_id}\n\n"
        f"## Description\n\n"
        f"{metadata.get('purpose', '')}\n\n"
        f"## Adapted Content\n\n"
        f"{adapted_content}\n"
    )
    (active_dir / "SKILL.md").write_text(skill_md_content, encoding="utf-8")

    # Write metadata.yml in active
    active_metadata = {
        "schema_version": 1,
        "skill_id": skill_id,
        "skill_name": skill_name,
        "name": metadata.get("name") or skill_name,
        "promoted_at": utc_now(),
        "source": metadata.get("source", {}),
        "purpose": metadata.get("purpose", ""),
        "summary": metadata.get("summary") or metadata.get("purpose", ""),
        "triggers": metadata.get("triggers", []),
        "applies_to": metadata.get("applies_to", []),
        "load_tokens": metadata.get("load_tokens", 1200),
        "expected_saving_tokens": metadata.get("expected_saving_tokens", 3000),
        "risk_level": metadata.get("risk_level", "medium"),
        "permissions": metadata.get("permissions", {}),
        "confidence": metadata.get("confidence", 0.5),
        "status": "active",
    }
    atomic_write_yaml(active_dir / "metadata.yml", active_metadata)

    # Write validation_report.yml
    validation_report = {
        "schema_version": 1,
        "skill_id": skill_id,
        "validation_date": utc_now(),
        "sandbox_report": sandbox_report,
        "checks_passed": True,
    }
    atomic_write_yaml(active_dir / "validation_report.yml", validation_report)

    # Write empty usage_ledger.yml
    usage_ledger = {
        "schema_version": 1,
        "skill_id": skill_id,
        "entries": [],
    }
    atomic_write_yaml(active_dir / "usage_ledger.yml", usage_ledger)

    # Update registry
    registry = load_skill_registry(agentlab_root)
    registry.setdefault("skills", [])

    # Remove any existing entry for this skill_id
    registry["skills"] = [s for s in registry["skills"] if s.get("skill_id") != skill_id]
    registry["skills"].append({
        "skill_id": skill_id,
        "skill_name": skill_name,
        "name": metadata.get("name") or skill_name,
        "status": "active",
        "triggers": metadata.get("triggers", []),
        "applies_to": metadata.get("applies_to", []),
        "summary": metadata.get("summary") or metadata.get("purpose", ""),
        "load_tokens": metadata.get("load_tokens", 1200),
        "expected_saving_tokens": metadata.get("expected_saving_tokens", 3000),
        "risk_level": metadata.get("risk_level", "medium"),
        "permissions": metadata.get("permissions", {}),
        "confidence": metadata.get("confidence", 0.5),
        "promoted_at": utc_now(),
    })
    write_skill_registry(agentlab_root, registry)

    # Update staging metadata
    metadata["status"] = "active"
    metadata["promoted_at"] = utc_now()
    atomic_write_yaml(metadata_path, metadata)
    try:
        from webhook_dispatcher import dispatch_event

        dispatch_event(
            agentlab_root,
            event="SKILL_PROMOTED",
            project=metadata.get("project", "AgentLab"),
            summary=f"Skill promoted: {skill_name}",
            reason=metadata.get("purpose", ""),
            links={"active_skill": str(active_dir)},
        )
    except Exception:
        pass

    return {
        "skill_id": skill_id,
        "skill_name": skill_name,
        "status": "active",
        "active_dir": str(active_dir),
    }


def retire_skill(agentlab_root: Path, skill_id: str, reason: str) -> dict[str, Any]:
    """Retire an active skill (active → retired).

    Moves skill content into skills/retired/<skill_id>/ and updates the registry.
    """
    active_dir = skill_active_dir(agentlab_root) / skill_id
    if not active_dir.exists():
        raise FileNotFoundError(f"Active skill directory not found: {active_dir}")

    # Verify the skill is currently active in registry
    registry = load_skill_registry(agentlab_root)
    skill_entry = None
    for s in registry.get("skills", []):
        if s.get("skill_id") == skill_id:
            skill_entry = s
            break

    if skill_entry is None:
        raise ValueError(f"Skill '{skill_id}' not found in registry. Cannot retire.")

    current_status = skill_entry.get("status", "")
    _assert_transition(current_status, "retired")

    # Create retired directory
    retired_dir = skill_retired_dir(agentlab_root) / skill_id
    retired_dir.mkdir(parents=True, exist_ok=True)

    # Copy active skill content to retired
    for item in active_dir.iterdir():
        dest = retired_dir / item.name
        if item.is_file():
            shutil.copy2(item, dest)
        elif item.is_dir():
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(item, dest)

    # Write retired_at.yml
    retired_record = {
        "schema_version": 1,
        "skill_id": skill_id,
        "skill_name": skill_entry.get("skill_name", skill_id),
        "retired_at": utc_now(),
        "reason": reason,
        "previous_status": current_status,
    }
    atomic_write_yaml(retired_dir / "retired_at.yml", retired_record)

    # Update registry: move from skills to retired_skills
    registry["skills"] = [s for s in registry.get("skills", []) if s.get("skill_id") != skill_id]
    registry.setdefault("retired_skills", [])
    registry["retired_skills"].append({
        "skill_id": skill_id,
        "skill_name": skill_entry.get("skill_name", skill_id),
        "retired_at": utc_now(),
        "reason": reason,
    })
    write_skill_registry(agentlab_root, registry)

    return {
        "skill_id": skill_id,
        "status": "retired",
        "reason": reason,
        "retired_dir": str(retired_dir),
    }


# ── trace skill candidate ────────────────────────────────────────

def build_trace_skill_candidate(
    *,
    project: str,
    task_id: str,
    name: str,
    evidence: list[str],
    trigger: str,
    steps: list[str],
    estimated_future_value: str = "unknown",
) -> dict[str, Any]:
    candidate_id = _timestamp_id("skill_cand", name)
    return {
        "schema_version": 1,
        "id": candidate_id,
        "project": project,
        "name": name,
        "created_from_task": task_id,
        "created_at": utc_now(),
        "evidence": evidence,
        "proposed_skill": {
            "trigger": trigger,
            "steps": steps,
        },
        "estimated_future_value": estimated_future_value,
        "status": "pending_review",
    }


def write_trace_skill_candidate(agentlab_root: Path, candidate: dict[str, Any]) -> Path:
    project = candidate["project"]
    task_id = candidate["created_from_task"]
    candidate_id = candidate.get("id") or _timestamp_id("skill_cand", candidate.get("name", "skill"))
    candidate["id"] = candidate_id
    path = skill_candidate_dir(agentlab_root, project, task_id) / f"{candidate_id}.yml"
    atomic_write_yaml(path, candidate)
    try:
        from webhook_dispatcher import dispatch_event

        dispatch_event(
            agentlab_root,
            event="SKILL_CANDIDATE_READY",
            project=project,
            task_id=task_id,
            summary=f"Skill candidate ready: {candidate.get('name', candidate_id)}",
            reason=(candidate.get("proposed_skill") or {}).get("trigger", ""),
            links={"skill_candidate": str(path)},
        )
    except Exception:
        pass
    return path


# ── summary ──────────────────────────────────────────────────────

def summarize_skill_system(agentlab_root: Path, project: str) -> dict[str, Any]:
    registry = load_skill_registry(agentlab_root)
    requests = load_skill_requests(agentlab_root, project)

    active_skills = [s for s in registry.get("skills", []) if s.get("status") == "active"]
    pending_requests = [r for r in requests if r.get("status") == "pending_user_approval"]
    staging_requests = [r for r in requests if r.get("status") == "staging"]
    validated_requests = [r for r in requests if r.get("status") == "validated"]

    # Count staging dirs
    staging_dir = skill_staging_dir(agentlab_root)
    staging_count = 0
    if staging_dir.exists():
        staging_count = len([d for d in staging_dir.iterdir() if d.is_dir()])

    return {
        "registry_path": str(skill_registry_path(agentlab_root)),
        "skill_count": len(registry.get("skills", [])),
        "active_skill_count": len(active_skills),
        "retired_skill_count": len(registry.get("retired_skills", [])),
        "request_queue": str(skill_request_dir(agentlab_root, project)),
        "pending_request_count": len(pending_requests),
        "staging_request_count": len(staging_requests),
        "validated_request_count": len(validated_requests),
        "staging_dir_count": staging_count,
        "requests": requests,
    }
