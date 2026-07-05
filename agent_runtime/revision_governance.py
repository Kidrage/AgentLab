"""Revision governance lane for long-running AgentLab projects."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from agent_runtime.atomic_io import atomic_write_text, atomic_write_yaml
from agent_runtime.program_manager.project_fact_state import (
    apply_state_transition_proposal,
    load_project_fact_snapshot,
)
from agent_runtime.program_manager.state_transition_validator import validate_state_transition_proposal


CHANGE_REQUEST_FILE = "change_request.yml"
STATE_TRANSITION_FILE = "state_transition_proposal.yml"
REVISION_ACCEPTANCE_FILE = "revision_acceptance.yml"
REVISION_LOG_FILE = "revision_log.jsonl"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def project_root(agentlab_root: Path, project: str) -> Path:
    return Path(agentlab_root) / "projects" / project


def run_dir(agentlab_root: Path, project: str, task_id: str) -> Path:
    return project_root(agentlab_root, project) / "runs" / task_id


def project_brain_dir(agentlab_root: Path, project: str) -> Path:
    return project_root(agentlab_root, project) / "project_brain"


def read_yaml(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or default
    return data


def build_revision_intake_artifacts(project: str, task_id: str, prompt: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Convert raw user revision text into a change request and fact proposal."""
    now = utc_now()
    lines = [line.strip("- *\t ") for line in prompt.splitlines() if line.strip()]
    if not lines:
        lines = [prompt.strip()]
    change_items = [
        {
            "id": f"change_{index:03d}",
            "text": line,
            "status": "proposed",
        }
        for index, line in enumerate(lines, start=1)
        if line
    ]
    change_request = {
        "schema_version": 1,
        "project": project,
        "task_id": task_id,
        "created_at": now,
        "source": "user_prompt",
        "raw_prompt": prompt,
        "change_items": change_items,
    }
    proposal = {
        "state_transition_proposal": {
            "schema_version": 1,
            "project": project,
            "task_id": task_id,
            "phase_id": task_id,
            "created_at": now,
            "status": "proposed",
            "source_change_request": CHANGE_REQUEST_FILE,
            "events": [
                {
                    "event_type": "propose_revision",
                    "target_kind": "entity",
                    "target_type": "revision_request",
                    "target_id": item["id"],
                    "to_status": "planned",
                    "evidence_refs": [CHANGE_REQUEST_FILE],
                    "facts": {
                        "text": item["text"],
                        "source": "user_prompt",
                    },
                }
                for item in change_items
            ],
            "requires_conflict_check": True,
            "requires_acceptance_before_merge": True,
        }
    }
    return change_request, proposal


def write_revision_intake(agentlab_root: Path, project: str, task_id: str, prompt: str) -> dict[str, Any]:
    target_dir = run_dir(agentlab_root, project, task_id)
    change_request, proposal = build_revision_intake_artifacts(project, task_id, prompt)
    atomic_write_yaml(target_dir / CHANGE_REQUEST_FILE, change_request)
    atomic_write_yaml(target_dir / STATE_TRANSITION_FILE, proposal)
    return {
        "written": True,
        "change_request_path": str(target_dir / CHANGE_REQUEST_FILE),
        "state_transition_proposal_path": str(target_dir / STATE_TRANSITION_FILE),
        "change_request": change_request,
        "state_transition_proposal": proposal,
    }


def load_revision_artifacts(agentlab_root: Path, project: str, task_id: str) -> dict[str, Any]:
    target_dir = run_dir(agentlab_root, project, task_id)
    return {
        "run_dir": str(target_dir),
        "change_request": read_yaml(target_dir / CHANGE_REQUEST_FILE),
        "state_transition_proposal": read_yaml(target_dir / STATE_TRANSITION_FILE),
        "acceptance": read_yaml(target_dir / REVISION_ACCEPTANCE_FILE),
    }


def check_revision_conflicts(snapshot: dict[str, Any], proposal: dict[str, Any] | None) -> dict[str, Any]:
    """Detect direct conflicts between proposal events and current fact snapshot."""
    if not proposal:
        return {"valid": False, "conflicts": [{"severity": "error", "message": "missing state transition proposal"}]}
    body = proposal.get("state_transition_proposal") or proposal
    conflicts: list[dict[str, str]] = []
    for index, event in enumerate(body.get("events") or []):
        target = _snapshot_target(snapshot, event)
        if not target:
            continue
        prefix = f"events[{index}]"
        previous_status = str(target.get("status") or "")
        from_status = str(event.get("from_status") or "")
        to_status = str(event.get("to_status") or "")
        if from_status and previous_status and from_status != previous_status:
            conflicts.append({
                "severity": "error",
                "path": prefix,
                "message": f"from_status {from_status!r} does not match current status {previous_status!r}",
            })
        if previous_status in {"dead", "retired", "superseded"} and to_status in {"active", "planned"}:
            conflicts.append({
                "severity": "error",
                "path": prefix,
                "message": f"cannot move {previous_status!r} fact to {to_status!r} without an explicit allowed transition",
            })
        existing_facts = target.get("facts") or {}
        proposed_facts = event.get("facts") or {}
        if isinstance(existing_facts, dict) and isinstance(proposed_facts, dict):
            for key, value in proposed_facts.items():
                if key in existing_facts and existing_facts[key] != value:
                    conflicts.append({
                        "severity": "error",
                        "path": f"{prefix}.facts.{key}",
                        "message": "proposed fact conflicts with current snapshot",
                    })
    return {
        "valid": not any(item.get("severity") == "error" for item in conflicts),
        "conflicts": conflicts,
    }


def validate_revision(agentlab_root: Path, project: str, task_id: str) -> dict[str, Any]:
    artifacts = load_revision_artifacts(agentlab_root, project, task_id)
    proposal = artifacts.get("state_transition_proposal")
    brain_dir = project_brain_dir(agentlab_root, project)
    snapshot = load_project_fact_snapshot(brain_dir)
    contract_path = brain_dir / "project_state_contract.yml"
    if contract_path.exists():
        contract = read_yaml(contract_path, {}) or {}
        transition = validate_state_transition_proposal(contract, snapshot, proposal, required=True)
    else:
        body = (proposal or {}).get("state_transition_proposal") or proposal or {}
        events = body.get("events") or []
        transition = {
            "valid": bool(events),
            "verdict": "PASS" if events else "NEEDS_EVIDENCE",
            "errors": [] if events else ["state_transition_proposal.yml has no events"],
            "warnings": ["project_state_contract.yml unavailable"],
        }
    conflicts = check_revision_conflicts(snapshot, proposal)
    valid = bool(transition.get("valid")) and bool(conflicts.get("valid"))
    return {
        "valid": valid,
        "project": project,
        "task_id": task_id,
        "transition": transition,
        "conflict_check": conflicts,
        "artifacts": {
            "change_request_present": artifacts.get("change_request") is not None,
            "state_transition_proposal_present": proposal is not None,
            "acceptance_present": artifacts.get("acceptance") is not None,
        },
    }


def apply_revision(agentlab_root: Path, project: str, task_id: str, *, accepted_by: str = "system") -> dict[str, Any]:
    artifacts = load_revision_artifacts(agentlab_root, project, task_id)
    validation = validate_revision(agentlab_root, project, task_id)
    target_dir = run_dir(agentlab_root, project, task_id)
    if not validation.get("valid"):
        result = {
            "status": "blocked",
            "applied": False,
            "accepted_by": accepted_by,
            "accepted_at": utc_now(),
            "validation": validation,
        }
        atomic_write_yaml(target_dir / REVISION_ACCEPTANCE_FILE, result)
        return result
    proposal = artifacts.get("state_transition_proposal")
    apply_result = apply_state_transition_proposal(project_brain_dir(agentlab_root, project), proposal)
    result = {
        "status": "applied",
        "applied": True,
        "accepted_by": accepted_by,
        "accepted_at": utc_now(),
        "validation": validation,
        "event_ids": apply_result.get("event_ids") or [],
    }
    atomic_write_yaml(target_dir / REVISION_ACCEPTANCE_FILE, result)
    append_revision_log(agentlab_root, project, task_id, result)
    return result


def append_revision_log(agentlab_root: Path, project: str, task_id: str, result: dict[str, Any]) -> None:
    brain_dir = project_brain_dir(agentlab_root, project)
    brain_dir.mkdir(parents=True, exist_ok=True)
    path = brain_dir / REVISION_LOG_FILE
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    entry = {
        "project": project,
        "task_id": task_id,
        "created_at": utc_now(),
        "status": result.get("status"),
        "event_ids": result.get("event_ids") or [],
        "accepted_by": result.get("accepted_by"),
    }
    content = existing
    if content and not content.endswith("\n"):
        content += "\n"
    content += json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n"
    atomic_write_text(path, content)


def revision_dispatch_status(agentlab_root: Path, project: str, task_id: str) -> dict[str, Any]:
    artifacts = load_revision_artifacts(agentlab_root, project, task_id)
    has_change = artifacts.get("change_request") is not None
    has_proposal = artifacts.get("state_transition_proposal") is not None
    acceptance = artifacts.get("acceptance") or {}
    if not has_change and not has_proposal:
        return {"blocked": False, "reason": "no revision governance artifacts present"}
    if not has_change:
        return {"blocked": True, "reason": "state_transition_proposal.yml exists without change_request.yml"}
    if not has_proposal:
        return {"blocked": True, "reason": "change_request.yml exists without state_transition_proposal.yml"}
    if acceptance.get("status") != "applied":
        return {"blocked": True, "reason": "revision proposal has not been accepted and applied"}
    return {"blocked": False, "reason": "revision accepted", "event_ids": acceptance.get("event_ids") or []}


def _snapshot_target(snapshot: dict[str, Any], event: dict[str, Any]) -> dict[str, Any] | None:
    kind = str(event.get("target_kind") or event.get("kind") or "entity")
    collection_key = "entities" if kind == "entity" else "artifacts"
    type_key = "entity_type" if kind == "entity" else "artifact_type"
    id_key = "entity_id" if kind == "entity" else "artifact_id"
    target_type = str(event.get("target_type") or event.get(type_key) or "")
    target_id = str(event.get("target_id") or event.get(id_key) or "")
    if not target_type or not target_id:
        return None
    return (((snapshot.get(collection_key) or {}).get(target_type) or {}).get(target_id) or None)
