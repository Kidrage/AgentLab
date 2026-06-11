"""Skill evolution scaffolding for AgentLab.

This module intentionally avoids network access and installation. It defines the
local registry, request queue, trace-to-skill candidate files, and cost preview
shape that later implementation can plug into.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import re

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


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return slug[:48] or "skill"


def _timestamp_id(prefix: str, name: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    return f"{prefix}_{stamp}_{_slug(name)}"


def skill_registry_path(agentlab_root: Path) -> Path:
    return agentlab_root / "skills" / "registry.yml"


def default_skill_registry() -> dict[str, Any]:
    now = utc_now()
    return {
        "schema_version": 1,
        "skills": [],
        "retired_skills": [],
        "metadata": {
            "owner": "AgentLab",
            "status": "scaffold",
            "created_at": now,
            "updated_at": now,
            "notes": "Skills are not installed automatically.",
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


def save_skill_registry(agentlab_root: Path, registry: dict[str, Any]) -> Path:
    registry.setdefault("metadata", {})["updated_at"] = utc_now()
    path = skill_registry_path(agentlab_root)
    atomic_write_yaml(path, registry)
    return path


def ensure_skill_registry(agentlab_root: Path) -> Path:
    path = skill_registry_path(agentlab_root)
    if not path.exists():
        save_skill_registry(agentlab_root, default_skill_registry())
    return path


def skill_request_dir(agentlab_root: Path, project: str) -> Path:
    return agentlab_root / "projects" / project / "skill_requests"


def skill_candidate_dir(agentlab_root: Path, project: str, task_id: str) -> Path:
    return agentlab_root / "projects" / project / "runs" / task_id / "skill_candidates"


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
    return path


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
    return path


def summarize_skill_system(agentlab_root: Path, project: str) -> dict[str, Any]:
    registry = load_skill_registry(agentlab_root)
    requests = load_skill_requests(agentlab_root, project)
    active_skills = [s for s in registry.get("skills", []) if s.get("status", "active") == "active"]
    pending_requests = [r for r in requests if r.get("status") == "pending_user_approval"]
    return {
        "registry_path": str(skill_registry_path(agentlab_root)),
        "skill_count": len(registry.get("skills", [])),
        "active_skill_count": len(active_skills),
        "retired_skill_count": len(registry.get("retired_skills", [])),
        "request_queue": str(skill_request_dir(agentlab_root, project)),
        "pending_request_count": len(pending_requests),
        "requests": requests,
    }
