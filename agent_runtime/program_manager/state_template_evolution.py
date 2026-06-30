from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import re

import yaml

from agent_runtime.atomic_io import atomic_write_yaml


VALID_STATUSES = {"candidate", "rejected", "approved", "staging", "validated", "active", "retired"}
ALLOWED_TRANSITIONS = {
    "candidate": {"approved", "rejected"},
    "approved": {"staging"},
    "staging": {"validated"},
    "validated": {"active"},
    "active": {"retired"},
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return slug[:48] or "state-template"


def _candidate_id(name: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    return f"state_template_{stamp}_{_slug(name)}"


def assert_template_transition(from_status: str, to_status: str) -> None:
    allowed = ALLOWED_TRANSITIONS.get(from_status, set())
    if to_status not in allowed:
        raise ValueError(f"Invalid template transition: {from_status} -> {to_status}.")


def state_template_candidates_path(project_brain_dir: Path) -> Path:
    return project_brain_dir / "state_template_candidates.yml"


def load_state_template_candidates(project_brain_dir: Path) -> dict[str, Any]:
    path = state_template_candidates_path(project_brain_dir)
    if not path.exists():
        return {"schema_version": 1, "candidates": []}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return {"schema_version": 1, "candidates": []}
    data.setdefault("schema_version", 1)
    data.setdefault("candidates", [])
    return data


def write_state_template_candidates(project_brain_dir: Path, data: dict[str, Any]) -> None:
    atomic_write_yaml(state_template_candidates_path(project_brain_dir), data)


def derive_state_template_feedback(
    project_brain_dir: Path,
    acceptance_history: dict[str, Any] | None = None,
    task_events: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    candidates = []
    history_entries = (acceptance_history or {}).get("entries") or []
    repeated_state_failures = [
        item for item in history_entries
        if "state" in str(item.get("rationale") or item.get("reason") or "").lower()
        or item.get("state_transition_status") == "failed"
    ]
    if len(repeated_state_failures) >= 2:
        candidates.append(
            build_state_template_candidate(
                project_brain_dir,
                name="repeated-state-validation-gap",
                purpose="Tighten project fact state invariants after repeated validation failures.",
                evidence_refs=[str(item.get("phase_id") or "unknown") for item in repeated_state_failures],
                proposed_changes={"add_or_refine_invariants": True},
            )
        )
    return candidates


def build_state_template_candidate(
    project_brain_dir: Path,
    name: str,
    purpose: str,
    evidence_refs: list[str],
    proposed_changes: dict[str, Any],
) -> dict[str, Any]:
    data = load_state_template_candidates(project_brain_dir)
    candidate = {
        "id": _candidate_id(name),
        "name": name,
        "status": "candidate",
        "purpose": purpose,
        "evidence_refs": evidence_refs,
        "proposed_changes": proposed_changes,
        "created_at": utc_now(),
    }
    data.setdefault("candidates", []).append(candidate)
    write_state_template_candidates(project_brain_dir, data)
    return candidate


def transition_state_template_candidate(project_brain_dir: Path, candidate_id: str, to_status: str) -> dict[str, Any]:
    if to_status not in VALID_STATUSES:
        raise ValueError(f"Unknown template status: {to_status}")
    data = load_state_template_candidates(project_brain_dir)
    for candidate in data.get("candidates") or []:
        if candidate.get("id") == candidate_id:
            assert_template_transition(str(candidate.get("status")), to_status)
            candidate["status"] = to_status
            candidate["updated_at"] = utc_now()
            write_state_template_candidates(project_brain_dir, data)
            return candidate
    raise ValueError(f"Unknown state template candidate: {candidate_id}")
