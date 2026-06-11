"""Post-task Trace-to-Skill learning review."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from atomic_io import atomic_write_yaml, safe_read_yaml
from skill_evolution import build_skill_adoption_request, skill_candidate_dir, write_skill_adoption_request, write_trace_skill_candidate
from state_store import utc_now
from task_events import load_task_events


def learning_review_path(run_dir: Path) -> Path:
    return run_dir / "learning_review.yml"


def _read_lower(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8").lower()
    except OSError:
        return ""


def _detect_patterns(run_dir: Path) -> list[dict[str, Any]]:
    events = load_task_events(run_dir)
    event_names = [str(e.get("event", "")) for e in events]
    blocked_events = [e for e in events if e.get("event") == "NODE_BLOCKED"]
    decision_events = [e for e in events if e.get("event") == "USER_DECISION_RECORDED"]
    patterns: list[dict[str, Any]] = []

    if blocked_events and decision_events:
        patterns.append({
            "type": "blocked_then_resolved",
            "evidence": [f"{len(blocked_events)} blocked event(s)", f"{len(decision_events)} user decision event(s)"],
            "trigger": "When a task is blocked and later resolved by a user decision.",
            "steps": ["Read decision_cards", "Read USER_DECISION_REQUIRED archive", "Resume after approval"],
            "future_value": "medium",
        })
    elif blocked_events:
        patterns.append({
            "type": "blocked_event",
            "evidence": [str(e.get("message", "blocked")) for e in blocked_events[:3]],
            "trigger": "When a task enters a blocked state.",
            "steps": ["Read task_events.jsonl", "Classify block_type", "Create or resolve decision card"],
            "future_value": "medium",
        })

    validation_text = _read_lower(run_dir / "07_validation_report.md")
    if (
        "validation_failed" in event_names
        or "required validation command failed" in validation_text
        or "failed_required" in validation_text
        or "1 failed" in validation_text
    ):
        patterns.append({
            "type": "validation_failure",
            "evidence": ["Validation report or event indicates failed validation."],
            "trigger": "When validation commands fail or validation_report records a failure.",
            "steps": ["Read execution_log.yml", "Map failed command_id", "Repair validation failure", "Rerun required command"],
            "future_value": "high",
        })

    if any("RECOVERY" in name or "RESUME" in name for name in event_names):
        patterns.append({
            "type": "recovery_action",
            "evidence": [name for name in event_names if "RECOVERY" in name or "RESUME" in name][:5],
            "trigger": "When a task requires a recovery or resume action.",
            "steps": ["Read resume_plan.yml", "Inspect lifecycle failed node", "Resume from checkpoint"],
            "future_value": "medium",
        })

    if len(decision_events) >= 2:
        patterns.append({
            "type": "repeated_approval_pattern",
            "evidence": [f"{len(decision_events)} approvals recorded."],
            "trigger": "When similar user approvals repeat in one task.",
            "steps": ["Summarize approval pattern", "Propose lower-friction policy or reusable decision card"],
            "future_value": "medium",
        })

    implementation = _read_lower(run_dir / "06_implementation_report.md")
    archive = _read_lower(run_dir / "09_archive_update.md")
    if "repo-specific repair" in implementation or "repair procedure" in implementation or "repo-specific repair" in archive:
        patterns.append({
            "type": "new_repo_specific_repair_procedure",
            "evidence": ["Implementation/archive report mentions a repo-specific repair procedure."],
            "trigger": "When this repository needs the same repair procedure again.",
            "steps": ["Load repo-specific notes", "Apply documented repair sequence", "Run repo validation"],
            "future_value": "high",
        })

    if any((e.get("payload") or {}).get("block_type") == "artifact_gate" for e in blocked_events) or "artifact gate" in implementation:
        patterns.append({
            "type": "artifact_contract_workaround",
            "evidence": ["Artifact gate or artifact contract workaround detected."],
            "trigger": "When artifact contract checks fail or need a workaround.",
            "steps": ["Read artifact_manifest.yml", "Repair missing evidence", "Rerun artifact-check"],
            "future_value": "high",
        })

    return patterns


def run_learning_review(
    agentlab_root: Path,
    project: str,
    task_id: str,
    *,
    create_candidates: bool = True,
) -> dict[str, Any]:
    run_dir = agentlab_root / "projects" / project / "runs" / task_id
    patterns = _detect_patterns(run_dir)
    candidate_paths: list[str] = []
    candidates: list[dict[str, Any]] = []
    if create_candidates:
        for pattern in patterns:
            candidate = {
                **_candidate_from_pattern(project, task_id, pattern),
                "pattern_type": pattern["type"],
            }
            path = write_trace_skill_candidate(agentlab_root, candidate)
            candidate_paths.append(str(path))
            candidates.append(candidate)

    review = {
        "schema_version": 1,
        "project": project,
        "task_id": task_id,
        "created_at": utc_now(),
        "patterns": patterns,
        "candidate_count": len(candidate_paths),
        "candidate_paths": candidate_paths,
        "status": "candidates_created" if candidate_paths else "reviewed_no_candidate",
    }
    atomic_write_yaml(learning_review_path(run_dir), review)
    return review


def _candidate_from_pattern(project: str, task_id: str, pattern: dict[str, Any]) -> dict[str, Any]:
    from skill_evolution import build_trace_skill_candidate

    return build_trace_skill_candidate(
        project=project,
        task_id=task_id,
        name=f"{pattern['type']}_skill",
        evidence=pattern.get("evidence", []),
        trigger=pattern.get("trigger", ""),
        steps=pattern.get("steps", []),
        estimated_future_value=pattern.get("future_value", "unknown"),
    )


def list_skill_candidates(agentlab_root: Path, project: str, task_id: str) -> list[dict[str, Any]]:
    root = skill_candidate_dir(agentlab_root, project, task_id)
    if not root.exists():
        return []
    candidates = []
    for path in sorted(root.glob("*.yml")):
        data = safe_read_yaml(path, default={}) or {}
        if isinstance(data, dict):
            data.setdefault("_path", str(path))
            candidates.append(data)
    return candidates


def _load_candidate(agentlab_root: Path, project: str, task_id: str, candidate_id: str) -> tuple[dict[str, Any], Path]:
    for candidate in list_skill_candidates(agentlab_root, project, task_id):
        if candidate.get("id") == candidate_id:
            return candidate, Path(candidate["_path"])
    raise FileNotFoundError(f"Skill candidate not found: {candidate_id}")


def approve_skill_candidate(agentlab_root: Path, project: str, task_id: str, candidate_id: str) -> dict[str, Any]:
    candidate, path = _load_candidate(agentlab_root, project, task_id, candidate_id)
    proposed = candidate.get("proposed_skill", {}) or {}
    request = build_skill_adoption_request(
        agentlab_root,
        project=project,
        skill_name=candidate.get("name", candidate_id),
        source=f"trace://{project}/{task_id}/{candidate_id}",
        purpose=f"Self-learned from task trace: {proposed.get('trigger', '')}",
        source_type="self_learned",
        risk={"has_scripts": False, "requires_network": False, "modifies_files": False, "permission_level": "low"},
        applies_to=[candidate.get("pattern_type", "trace_to_skill")],
    )
    request["created_from_candidate"] = candidate_id
    request["triggers"] = [proposed.get("trigger", "")]
    request["summary"] = request["purpose"]
    request["risk_level"] = "low"
    request["permissions"] = {"can_read_repo": True, "can_modify_files": False, "can_run_shell": False}
    request["confidence"] = 0.5
    request_path = write_skill_adoption_request(agentlab_root, request)

    candidate["status"] = "approved"
    candidate["approved_at"] = utc_now()
    candidate["skill_request_id"] = request["id"]
    candidate["skill_request_path"] = str(request_path)
    atomic_write_yaml(path, candidate)
    return candidate


def reject_skill_candidate(agentlab_root: Path, project: str, task_id: str, candidate_id: str, reason: str) -> dict[str, Any]:
    candidate, path = _load_candidate(agentlab_root, project, task_id, candidate_id)
    candidate["status"] = "rejected"
    candidate["rejected_at"] = utc_now()
    candidate["rejection_reason"] = reason
    atomic_write_yaml(path, candidate)
    return candidate
