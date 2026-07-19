"""Durable, token-free orchestration for long-running AgentLab jobs.

The controller records intent and consumes process receipts.  It does not
implement Writer, Reviewer, or audit behavior; workers execute those existing
primitives and return a receipt for this reducer to apply exactly once.
"""

from __future__ import annotations

from datetime import datetime, timezone
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any, Callable

from agent_runtime.atomic_io import (
    atomic_write_yaml,
    safe_read_yaml,
)
from agent_runtime.narrative.jobs.identity import (
    NarrativeJobIdentity,
    lease_expiry,
)
from agent_runtime.narrative.jobs.crown_adapter import upgrade_crown_job_state
from agent_runtime.narrative.audit.gate import SealDecision, evaluate_narrative_seal
from agent_runtime.narrative.efficiency.planning import (
    compute_incremental_audit_window,
    plan_chapter_execution,
    select_batch_plan,
)
from agent_runtime.narrative.jobs.lifecycle import next_after_heavy_audit, record_audit_batch_result


SCHEMA_VERSION = 2
TERMINAL_STATES = {"completed", "completed_clean", "completed_with_findings", "blocked"}
CONTROLLER_STOP_STATES = {"paused", "decision_required"}
ACTION_RUNNING_STATE = {
    "preflight": "preflight",
    "generate_batch": "generating_batch",
    "deterministic_check": "deterministic_check",
    "heavy_audit": "heavy_auditing",
    "revision_support_scribe": "revision_support_scribe",
    "revision_support_verifier": "revision_support_verifier",
    "rewrite_batch": "rewriting",
    "deterministic_reaudit": "deterministic_reaudit",
    "final_acceptance": "final_acceptance",
}
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def _now(value: str | None = None) -> str:
    return value or datetime.now(timezone.utc).isoformat()


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _validate_id(value: str, label: str) -> str:
    if not SAFE_ID.fullmatch(value):
        raise ValueError(f"invalid {label}: {value!r}")
    return value


def _runtime_subprocess_env(root: Path) -> dict[str, str]:
    """Preserve both package and legacy direct-module imports in detached workers."""
    resolved_root = Path(root).resolve()
    entries = [str(resolved_root), str(resolved_root / "agent_runtime")]
    existing = os.environ.get("PYTHONPATH")
    if existing:
        entries.extend(existing.split(os.pathsep))
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(dict.fromkeys(entry for entry in entries if entry))
    return env


def job_dir(root: Path, project: str, job_id: str) -> Path:
    _validate_id(project, "project")
    _validate_id(job_id, "job_id")
    return Path(root) / "projects" / project / "background_jobs" / job_id


def job_state_path(root: Path, project: str, job_id: str) -> Path:
    return job_dir(root, project, job_id) / "job_state.yml"


def load_job_state(root: Path, project: str, job_id: str) -> dict[str, Any]:
    path = job_state_path(root, project, job_id)
    state = safe_read_yaml(path)
    if not isinstance(state, dict):
        raise FileNotFoundError(path)
    return upgrade_crown_job_state(state)


def _save_state(
    root: Path,
    project: str,
    job_id: str,
    state: dict[str, Any],
    *,
    now: str | None = None,
) -> dict[str, Any]:
    state["updated_at"] = _now(now)
    state["revision"] = int(state.get("revision", 0)) + 1
    atomic_write_yaml(job_state_path(root, project, job_id), state)
    return state


def _append_event(
    root: Path,
    project: str,
    job_id: str,
    event_type: str,
    *,
    status: str,
    now: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    path = job_dir(root, project, job_id) / "job_events.jsonl"
    event = {
        "schema_version": SCHEMA_VERSION,
        "event_id": f"evt-{_now(now)}-{event_type}",
        "event_type": event_type,
        "recorded_at": _now(now),
        "job_id": job_id,
        "project": project,
        "status": status,
        "payload": payload or {},
    }
    line = json.dumps(event, ensure_ascii=False, sort_keys=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _initial_batch(start_chapter: int, end_chapter: int, batch_size: int) -> dict[str, int]:
    return {
        "number": 1,
        "start": start_chapter,
        "end": min(end_chapter, start_chapter + batch_size - 1),
    }


def create_crown_delivery_job(
    root: Path,
    *,
    project: str,
    job_id: str,
    eval_id: str,
    start_chapter: int,
    end_chapter: int,
    batch_size: int = 10,
    heavy_audit_cadence: int = 10,
    writer_worker: str,
    chapter_state_plan: str,
    writer_budget: str = "frugal",
    suite: str = "crown-longform-reset-v1",
    max_retries_per_action: int = 3,
    transient_retry_seconds: int = 900,
    attempt_lease_seconds: int = 3600,
    candidate_set_id: str | None = None,
    source_job_id: str | None = None,
    source_run_id: str | None = None,
    triggered_by_audit_id: str | None = None,
    risk_signals: dict[int, list[str]] | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    """Create one project-scoped, candidate-only Crown delivery job."""
    _validate_id(project, "project")
    _validate_id(job_id, "job_id")
    _validate_id(eval_id, "eval_id")
    if start_chapter < 1 or end_chapter < start_chapter:
        raise ValueError("invalid chapter range")
    if batch_size < 1 or heavy_audit_cadence < 1:
        raise ValueError("batch size and heavy audit cadence must be positive")
    if max_retries_per_action < 0:
        raise ValueError("max retries must not be negative")
    if transient_retry_seconds < 1:
        raise ValueError("transient retry seconds must be positive")
    if attempt_lease_seconds < 1:
        raise ValueError("attempt lease seconds must be positive")
    project_root = Path(root) / "projects" / project
    if not project_root.is_dir():
        raise FileNotFoundError(project_root)
    directory = job_dir(root, project, job_id)
    if directory.exists():
        raise FileExistsError(directory)
    directory.mkdir(parents=True)
    recorded_at = _now(now)
    identity = NarrativeJobIdentity(
        job_kind="narrative_generation",
        run_mode="generate_candidate",
        candidate_set_id=candidate_set_id,
        source_job_id=source_job_id,
        source_run_id=source_run_id,
        triggered_by_audit_id=triggered_by_audit_id,
    )
    state: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "job_id": job_id,
        "job_type": "crown_narrative_delivery",
        **identity.to_dict(),
        "project": project,
        "status": "queued",
        "revision": 1,
        "created_at": recorded_at,
        "updated_at": recorded_at,
        "candidate_only": True,
        "production_allowed": False,
        "preflight_passed": False,
        "narrative_execution_plan": plan_chapter_execution(
            range(start_chapter, end_chapter + 1),
            risk_signals=risk_signals,
        ),
        "config": {
            "eval_id": eval_id,
            "suite": suite,
            "start_chapter": start_chapter,
            "end_chapter": end_chapter,
            "batch_size": batch_size,
            "heavy_audit_cadence": heavy_audit_cadence,
            "writer_worker": writer_worker,
            "chapter_state_plan": chapter_state_plan,
            "writer_budget": writer_budget,
            "max_retries_per_action": max_retries_per_action,
            "transient_retry_seconds": transient_retry_seconds,
            "attempt_lease_seconds": attempt_lease_seconds,
            "required_audits": [
                "fiction_review",
                "continuity_failure_report",
                "narrative_quality_scorecard",
            ],
            "narrative_adapter": "crown",
            "allow_writer_cli_fallback": False,
        },
        "current_batch": _initial_batch(start_chapter, end_chapter, batch_size),
        "sealed_batches": [],
        "active_attempt": None,
        "attempt_sequence": 0,
        "processed_receipt_keys": [],
        "retry_counts": {},
        "retry_action": None,
        "last_action_results": {},
        "automatic_rewrite_count": 0,
        "automatic_rewrite_exhausted": False,
        "decision_reason": None,
        "independent_reaudit_required": False,
        "revision_audit_window": None,
        "capacity_reset_at": None,
        "capacity_resume_count": 0,
        "retry_at": None,
        "retry_resume_count": 0,
        "pause_requested": False,
        "paused_from_status": None,
        "paused_at": None,
        "last_error": None,
    }
    atomic_write_yaml(directory / "job_state.yml", state)
    _append_event(
        root,
        project,
        job_id,
        "JOB_CREATED",
        status="queued",
        now=recorded_at,
        payload={"current_batch": state["current_batch"]},
    )
    return state


def _action_for_state(state: dict[str, Any]) -> str | None:
    status = state["status"]
    if status == "queued":
        return "generate_batch" if state.get("preflight_passed") else "preflight"
    if status == "deterministic_check":
        return "deterministic_check"
    if status == "awaiting_heavy_audit":
        return "heavy_audit"
    if status == "awaiting_revision_scribe":
        return "revision_support_scribe"
    if status == "awaiting_revision_verifier":
        return "revision_support_verifier"
    if status == "rewrite_required":
        return "rewrite_batch"
    if status == "deterministic_reaudit":
        return "deterministic_reaudit"
    if status == "final_acceptance":
        return "final_acceptance"
    if status == "failed_recoverable":
        return state.get("retry_action")
    return None


def _advance_sealed_batch(state: dict[str, Any]) -> None:
    batch = state["current_batch"]
    config = state["config"]
    if int(batch["end"]) >= int(config["end_chapter"]):
        state["status"] = "final_acceptance"
        return
    start = int(batch["end"]) + 1
    state["current_batch"] = {
        "number": int(batch["number"]) + 1,
        "start": start,
        "end": min(int(config["end_chapter"]), start + int(config["batch_size"]) - 1),
    }
    state["automatic_rewrite_count"] = 0
    state["automatic_rewrite_exhausted"] = False
    state["decision_reason"] = None
    state["independent_reaudit_required"] = False
    state["revision_audit_window"] = None
    state["status"] = "queued"


def _wake_capacity_if_due(state: dict[str, Any], now: str) -> bool:
    if state.get("status") != "capacity_wait":
        return False
    reset_at = state.get("capacity_reset_at")
    if not reset_at or _parse_timestamp(now) < _parse_timestamp(str(reset_at)):
        return False
    state["status"] = "failed_recoverable"
    state["capacity_reset_at"] = None
    state["capacity_resume_count"] = int(state.get("capacity_resume_count", 0)) + 1
    return True


def _wake_retry_if_due(state: dict[str, Any], now: str) -> bool:
    if state.get("status") != "retry_wait":
        return False
    retry_at = state.get("retry_at")
    if not retry_at or _parse_timestamp(now) < _parse_timestamp(str(retry_at)):
        return False
    state["status"] = "failed_recoverable"
    state["retry_at"] = None
    state["retry_resume_count"] = int(state.get("retry_resume_count", 0)) + 1
    return True


def _attempt_request(
    root: Path,
    state: dict[str, Any],
    *,
    action: str,
    attempt_id: str,
    idempotency_key: str,
    now: str,
    lease_token: str,
    lease_expires_at: str,
) -> dict[str, Any]:
    parent_identity = NarrativeJobIdentity.from_mapping(state)
    prior_audit = (state.get("last_action_results") or {}).get("heavy_audit") or {}
    if action == "rewrite_batch":
        identity = NarrativeJobIdentity(
            "narrative_revision",
            "targeted_rewrite",
            candidate_set_id=parent_identity.candidate_set_id,
            source_job_id=str(state["job_id"]),
            source_run_id=str(prior_audit.get("run_dir")) if prior_audit.get("run_dir") else None,
            triggered_by_audit_id=str(prior_audit.get("task_id")) if prior_audit.get("task_id") else None,
        )
    elif action in {
        "heavy_audit",
        "revision_support_scribe",
        "revision_support_verifier",
    } and state.get("job_kind") != "narrative_audit":
        identity = NarrativeJobIdentity(
            "narrative_audit",
            "independent_reaudit"
            if state.get("independent_reaudit_required")
            else "audit_only",
            candidate_set_id=parent_identity.candidate_set_id,
            source_job_id=str(state["job_id"]),
            source_run_id=str(prior_audit.get("run_dir")) if prior_audit.get("run_dir") else None,
            triggered_by_audit_id=str(prior_audit.get("task_id")) if prior_audit.get("task_id") else None,
        )
    else:
        identity = parent_identity
    identity = identity.for_attempt(attempt_id=attempt_id, lease_token=lease_token)
    batch = dict(state["current_batch"])
    persisted_plan = state.get("narrative_execution_plan")
    if not isinstance(persisted_plan, dict):
        persisted_plan = plan_chapter_execution(
            range(int(batch["start"]), int(batch["end"]) + 1)
        )
    request = {
        "schema_version": SCHEMA_VERSION,
        "job_id": state["job_id"],
        "project": state["project"],
        "parent_job_kind": parent_identity.job_kind,
        "parent_run_mode": parent_identity.run_mode,
        "attempt_id": attempt_id,
        **identity.to_dict(),
        "idempotency_key": idempotency_key,
        "action": action,
        "scheduled_at": now,
        "lease_expires_at": lease_expires_at,
        "candidate_only": True,
        "production_allowed": False,
        "batch": batch,
        "narrative_execution_plan": select_batch_plan(
            persisted_plan,
            start_chapter=int(batch["start"]),
            end_chapter=int(batch["end"]),
        ),
        "config": dict(state["config"]),
        "prior_results": dict(state.get("last_action_results") or {}),
        "require_independent_reaudit": bool(state.get("independent_reaudit_required")),
        "agentlab_root": str(Path(root).resolve()),
    }
    if action in {"deterministic_reaudit", "heavy_audit"} and isinstance(
        state.get("revision_audit_window"), dict
    ):
        request["audit_window"] = dict(state["revision_audit_window"])
    return request


def schedule_next_attempt(
    root: Path,
    *,
    project: str,
    job_id: str,
    now: str | None = None,
) -> dict[str, Any] | None:
    """Persist one next action. Scheduling never invokes a provider."""
    timestamp = _now(now)
    state = load_job_state(root, project, job_id)
    if state.get("pause_requested") or state.get("status") in CONTROLLER_STOP_STATES:
        return None
    if state.get("active_attempt"):
        return dict(state["active_attempt"])
    if state["status"] in TERMINAL_STATES:
        _ensure_completion_receipt(root, project, job_id, state, now=timestamp)
        return None
    woke_capacity = _wake_capacity_if_due(state, timestamp)
    woke_retry = _wake_retry_if_due(state, timestamp)
    if state["status"] in {"capacity_wait", "retry_wait"}:
        return None
    if state["status"] == "batch_sealed":
        _advance_sealed_batch(state)
    action = _action_for_state(state)
    if action is None:
        if woke_capacity or woke_retry:
            _save_state(root, project, job_id, state, now=timestamp)
        return None

    sequence = int(state.get("attempt_sequence", 0)) + 1
    attempt_id = f"attempt-{sequence:04d}-{action.replace('_', '-')}"
    idempotency_key = f"{job_id}:{attempt_id}"
    lease_token = f"{job_id}:lease-{sequence:04d}"
    lease_expires_at = lease_expiry(
        timestamp,
        int(state.get("config", {}).get("attempt_lease_seconds") or 3600),
    )
    attempt_dir = job_dir(root, project, job_id) / "attempts" / attempt_id
    request_path = attempt_dir / "action_request.yml"
    request = _attempt_request(
        root,
        state,
        action=action,
        attempt_id=attempt_id,
        idempotency_key=idempotency_key,
        now=timestamp,
        lease_token=lease_token,
        lease_expires_at=lease_expires_at,
    )
    atomic_write_yaml(request_path, request)
    active = {
        "attempt_id": attempt_id,
        "idempotency_key": idempotency_key,
        "lease_token": lease_token,
        "lease_expires_at": lease_expires_at,
        "action": action,
        "scheduled_at": timestamp,
        "worker_pid": None,
        "execution_started_at": None,
        "action_request_path": str(request_path),
    }
    state["attempt_sequence"] = sequence
    state["attempt_id"] = attempt_id
    state["lease_token"] = lease_token
    state["active_attempt"] = active
    state["status"] = ACTION_RUNNING_STATE[action]
    _save_state(root, project, job_id, state, now=timestamp)
    _append_event(
        root,
        project,
        job_id,
        "ATTEMPT_SCHEDULED",
        status=state["status"],
        now=timestamp,
        payload={"attempt_id": attempt_id, "action": action},
    )
    return active


def mark_attempt_started(
    root: Path,
    *,
    project: str,
    job_id: str,
    attempt_id: str,
    worker_pid: int,
    now: str | None = None,
) -> dict[str, Any]:
    timestamp = _now(now)
    state = load_job_state(root, project, job_id)
    active = state.get("active_attempt") or {}
    if active.get("attempt_id") != attempt_id:
        raise ValueError("attempt is not active")
    active["worker_pid"] = int(worker_pid)
    active["execution_started_at"] = timestamp
    state["active_attempt"] = active
    request_path = Path(active["action_request_path"])
    request = safe_read_yaml(request_path, default={}) or {}
    request["worker_pid"] = int(worker_pid)
    request["execution_started_at"] = timestamp
    atomic_write_yaml(request_path, request)
    return _save_state(root, project, job_id, state, now=timestamp)


def process_receipt_path(
    root: Path,
    project: str,
    job_id: str,
    attempt_id: str,
) -> Path:
    _validate_id(attempt_id, "attempt_id")
    return job_dir(root, project, job_id) / "attempts" / attempt_id / "process_receipt.yml"


def write_process_receipt(
    root: Path,
    *,
    project: str,
    job_id: str,
    attempt_id: str,
    idempotency_key: str,
    lease_token: str,
    outcome: str,
    exit_code: int,
    result: dict[str, Any],
    capacity_reset_at: str | None = None,
    retry_at: str | None = None,
    now: str | None = None,
) -> Path:
    """Atomically record a returned action result without applying it."""
    if outcome not in {
        "success",
        "failed_recoverable",
        "failed",
        "capacity_wait",
        "retry_wait",
    }:
        raise ValueError(f"unsupported process outcome: {outcome}")
    path = process_receipt_path(root, project, job_id, attempt_id)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "job_id": job_id,
        "project": project,
        "attempt_id": attempt_id,
        "idempotency_key": idempotency_key,
        "lease_token": lease_token,
        "outcome": outcome,
        "exit_code": int(exit_code),
        "completed_at": _now(now),
        "capacity_reset_at": capacity_reset_at,
        "retry_at": retry_at,
        "result": result,
    }
    existing = safe_read_yaml(path)
    if existing is not None:
        comparable = dict(existing)
        if comparable != payload:
            raise FileExistsError(f"conflicting receipt already exists: {path}")
        return path
    atomic_write_yaml(path, payload)
    return path


def _seal_current_batch(state: dict[str, Any], now: str) -> None:
    batch = dict(state["current_batch"])
    if not any(item.get("number") == batch["number"] for item in state["sealed_batches"]):
        batch["sealed_at"] = now
        state["sealed_batches"].append(batch)
    state["status"] = "batch_sealed"


def _successful_transition(state: dict[str, Any], action: str, result: dict[str, Any], now: str) -> None:
    result_status = str(result.get("status") or "pass").lower()
    if result_status == "decision_required":
        state["status"] = "decision_required"
        state["decision_reason"] = result.get("reason") or "revision_decision_required"
        return
    if result_status not in {"pass", "completed", "ready", "success"}:
        state["status"] = "blocked"
        state["last_error"] = result.get("reason") or f"{action} returned {result_status}"
        return
    if action == "preflight":
        state["preflight_passed"] = True
        state["status"] = "queued"
    elif action == "generate_batch":
        state["status"] = "deterministic_check"
    elif action == "deterministic_check":
        state["status"] = "awaiting_heavy_audit"
    elif action == "heavy_audit":
        configured_audits = tuple(
            str(item)
            for item in state.get("config", {}).get(
                "required_audits",
                ["fiction_review", "continuity_failure_report"],
            )
        )
        revision_window = state.get("revision_audit_window")
        required_quality_chapters = (
            tuple(int(item) for item in revision_window.get("audit_chapters") or [])
            if isinstance(revision_window, dict)
            else tuple(
                range(
                    int(state["current_batch"]["start"]),
                    int(state["current_batch"]["end"]) + 1,
                )
            )
        )
        if "narrative_quality_scorecard" not in configured_audits:
            required_quality_chapters = ()
        decision = evaluate_narrative_seal(
            fiction_review=result.get("fiction_review") if isinstance(result.get("fiction_review"), dict) else None,
            continuity_failure_report=(
                result.get("continuity_failure_report_data")
                if isinstance(result.get("continuity_failure_report_data"), dict)
                else result.get("continuity_failure_report")
                if isinstance(result.get("continuity_failure_report"), dict)
                else None
            ),
            narrative_quality_scorecard=(
                result.get("narrative_quality_scorecard")
                if isinstance(result.get("narrative_quality_scorecard"), dict)
                else None
            ),
            candidate_sha256=str(result.get("candidate_sha256"))
            if result.get("candidate_sha256")
            else None,
            audit_source_integrity=(
                result.get("audit_source_integrity")
                if isinstance(result.get("audit_source_integrity"), dict)
                else None
            ),
            required_audits=configured_audits,
            require_independent_reaudit=bool(state.get("independent_reaudit_required")),
            independent_reaudit=(
                result.get("independent_reaudit")
                if isinstance(result.get("independent_reaudit"), dict)
                else None
            ),
            tiered_audit=(
                result.get("tiered_audit")
                if isinstance(result.get("tiered_audit"), dict)
                else None
            ),
            required_quality_chapters=required_quality_chapters,
        ).to_dict()
        transition = next_after_heavy_audit(
            job_kind=str(state.get("job_kind") or ""),
            decision=SealDecision.from_mapping(decision),
            automatic_rewrite_count=int(state.get("automatic_rewrite_count") or 0),
        )
        if state.get("job_kind") == "narrative_audit":
            findings: list[dict[str, Any]] = []
            for document_name in (
                "fiction_review",
                "continuity_failure_report_data",
                "narrative_quality_scorecard",
            ):
                document = result.get(document_name)
                if not isinstance(document, dict):
                    continue
                for key in ("findings", "failures"):
                    for finding in document.get(key) or []:
                        findings.append(
                            {
                                "audit": document_name,
                                "finding": finding,
                            }
                        )
            record_audit_batch_result(
                state,
                decision=SealDecision.from_mapping(decision),
                findings=findings,
                now=now,
            )
            return
        if transition.seal_candidate:
            _seal_current_batch(state, now)
            state["independent_reaudit_required"] = False
        else:
            if (
                transition.status == "rewrite_required"
                and result.get("task_id")
                and result.get("run_dir")
                and not result.get("rewrite_proposal")
            ):
                state["status"] = "awaiting_revision_scribe"
            else:
                state["status"] = transition.status
        state["automatic_rewrite_exhausted"] = transition.automatic_rewrite_exhausted
        if transition.reason:
            state["decision_reason"] = transition.reason
            if transition.status == "blocked":
                state["last_error"] = transition.reason
    elif action == "rewrite_batch":
        state["automatic_rewrite_count"] = int(state.get("automatic_rewrite_count") or 0) + 1
        batch = state["current_batch"]
        state["revision_audit_window"] = compute_incremental_audit_window(
            changed_chapters=result.get("changed_chapters") or [],
            available_chapters=range(int(batch["start"]), int(batch["end"]) + 1),
            fact_dependencies=result.get("fact_dependencies") or {},
            full_reaudit_reason=(
                str(result.get("full_reaudit_reason"))
                if result.get("full_reaudit_reason")
                else None
            ),
        )
        state["status"] = "deterministic_reaudit"
    elif action == "revision_support_scribe":
        state["status"] = "awaiting_revision_verifier"
    elif action == "revision_support_verifier":
        state["status"] = "rewrite_required"
    elif action == "deterministic_reaudit":
        state["independent_reaudit_required"] = True
        state["status"] = "awaiting_heavy_audit"
    elif action == "final_acceptance":
        state["status"] = "completed"


def _ensure_completion_receipt(
    root: Path,
    project: str,
    job_id: str,
    state: dict[str, Any],
    *,
    now: str,
) -> Path | None:
    if state.get("status") not in {"completed", "completed_clean", "completed_with_findings"}:
        return None
    path = job_dir(root, project, job_id) / "completion_receipt.yml"
    if not path.exists():
        atomic_write_yaml(
            path,
            {
                "schema_version": SCHEMA_VERSION,
                "job_id": job_id,
                "project": project,
                "status": state["status"],
                "completed_at": now,
                "candidate_only": True,
                "production_modified": False,
                "chapter_range": [
                    state["config"]["start_chapter"],
                    state["config"]["end_chapter"],
                ],
                "sealed_batches": state.get("sealed_batches", []),
                "audited_batches": state.get("audited_batches", []),
                "findings": state.get("findings", []),
                "processed_receipt_keys": state.get("processed_receipt_keys", []),
            },
        )
    return path


def _ensure_terminal_feedback(
    root: Path,
    project: str,
    job_id: str,
    state: dict[str, Any],
    *,
    now: str,
) -> Path | None:
    status = str(state.get("status") or "")
    if status not in TERMINAL_STATES:
        return None
    directory = job_dir(root, project, job_id)
    path = directory / "operator_feedback.yml"
    existing = safe_read_yaml(path)
    if isinstance(existing, dict) and existing.get("status") in {"pass", "warn"}:
        return path

    event = "COMPLETED" if status.startswith("completed") else "BLOCKED"
    feedback_id = f"{job_id}:{status}"
    receipt: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "feedback_id": feedback_id,
        "status": "pending",
        "event": event,
        "job_id": job_id,
        "project": project,
        "recorded_at": now,
        "job_status": status,
        "candidate_only": bool(state.get("candidate_only")),
        "production_modified": False,
        "reason": state.get("last_error"),
    }
    atomic_write_yaml(path, receipt)
    _append_event(
        root,
        project,
        job_id,
        f"JOB_{event}",
        status=status,
        now=now,
        payload={"operator_feedback": "operator_feedback.yml", "feedback_id": feedback_id},
    )

    try:
        from agent_runtime.webhook_dispatcher import dispatch_event

        links = {"job_state": str(job_state_path(root, project, job_id))}
        completion = directory / "completion_receipt.yml"
        if completion.is_file():
            links["completion_receipt"] = str(completion)
        dispatch = dispatch_event(
            Path(root),
            event=event,
            project=project,
            task_id=job_id,
            stage="background_job",
            severity="info" if status == "completed" else "error",
            summary=f"Background job {job_id} {status}",
            reason=str(state.get("last_error") or ""),
            links=links,
        )
        receipt["status"] = "pass" if dispatch.get("ok") else "warn"
        receipt["dispatch"] = dispatch
    except Exception as exc:  # Local receipt remains the authoritative feedback.
        receipt["status"] = "warn"
        receipt["dispatch_error"] = f"{type(exc).__name__}: {exc}"
    atomic_write_yaml(path, receipt)
    return path


def consume_process_receipt(
    root: Path,
    *,
    project: str,
    job_id: str,
    now: str | None = None,
) -> dict[str, Any]:
    """Apply the active attempt receipt exactly once to authoritative state."""
    timestamp = _now(now)
    state = load_job_state(root, project, job_id)
    active = state.get("active_attempt")
    if not active:
        _ensure_completion_receipt(root, project, job_id, state, now=timestamp)
        _ensure_terminal_feedback(root, project, job_id, state, now=timestamp)
        return state
    receipt_path = process_receipt_path(
        root, project, job_id, str(active["attempt_id"])
    )
    receipt = safe_read_yaml(receipt_path)
    if not isinstance(receipt, dict):
        return state
    key = str(receipt.get("idempotency_key") or "")
    if key != active.get("idempotency_key"):
        raise ValueError("receipt idempotency key does not match active attempt")
    if receipt.get("lease_token") != active.get("lease_token"):
        raise ValueError("receipt lease token does not match active attempt")
    if _parse_timestamp(str(receipt.get("completed_at") or "")) > _parse_timestamp(
        str(active.get("lease_expires_at") or "")
    ):
        raise ValueError("receipt arrived after attempt lease expired")
    if key in state.get("processed_receipt_keys", []):
        return state

    action = str(active["action"])
    state.setdefault("processed_receipt_keys", []).append(key)
    state["active_attempt"] = None
    outcome = str(receipt.get("outcome") or "failed")
    result = receipt.get("result") if isinstance(receipt.get("result"), dict) else {}
    if outcome == "success":
        state.setdefault("last_action_results", {})[action] = result
        state["retry_action"] = None
        state["last_error"] = None
        _successful_transition(state, action, result, timestamp)
    elif outcome == "capacity_wait":
        reset_at = receipt.get("capacity_reset_at")
        if not reset_at:
            state["status"] = "blocked"
            state["last_error"] = "capacity receipt did not include capacity_reset_at"
        else:
            _parse_timestamp(str(reset_at))
            state["status"] = "capacity_wait"
            state["capacity_reset_at"] = str(reset_at)
            state["retry_action"] = action
            state["last_error"] = result.get("reason") or "capacity_wait"
    elif outcome == "retry_wait":
        retry_at = receipt.get("retry_at")
        if not retry_at:
            state["status"] = "blocked"
            state["last_error"] = "retry receipt did not include retry_at"
        else:
            _parse_timestamp(str(retry_at))
            state["status"] = "retry_wait"
            state["retry_at"] = str(retry_at)
            state["retry_action"] = action
            state["last_error"] = result.get("reason") or "transient_failure"
    else:
        counts = state.setdefault("retry_counts", {})
        counts[action] = int(counts.get(action, 0)) + 1
        state["retry_action"] = action
        state["last_error"] = result.get("reason") or f"{action} process failed"
        if counts[action] > int(state["config"]["max_retries_per_action"]):
            state["status"] = "blocked"
        else:
            state["status"] = "failed_recoverable"

    if state.get("pause_requested") and state["status"] not in TERMINAL_STATES:
        state["paused_from_status"] = state["status"]
        state["status"] = "paused"
        state["paused_at"] = timestamp

    _save_state(root, project, job_id, state, now=timestamp)
    _append_event(
        root,
        project,
        job_id,
        "RECEIPT_CONSUMED",
        status=state["status"],
        now=timestamp,
        payload={
            "attempt_id": active["attempt_id"],
            "action": action,
            "outcome": outcome,
            "idempotency_key": key,
        },
    )
    if state["status"] in TERMINAL_STATES:
        _ensure_completion_receipt(root, project, job_id, state, now=timestamp)
        _ensure_terminal_feedback(root, project, job_id, state, now=timestamp)
    return state


def _default_pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def recover_orphaned_attempt(
    root: Path,
    *,
    project: str,
    job_id: str,
    pid_is_alive: Callable[[int], bool] = _default_pid_is_alive,
    now: str | None = None,
) -> dict[str, Any]:
    """Convert a dead receipt-less worker into a normal recoverable receipt."""
    timestamp = _now(now)
    state = load_job_state(root, project, job_id)
    active = state.get("active_attempt")
    if not active:
        return state
    receipt = process_receipt_path(root, project, job_id, active["attempt_id"])
    if receipt.exists():
        return consume_process_receipt(
            root, project=project, job_id=job_id, now=timestamp
        )
    pid = active.get("worker_pid")
    if pid is None or pid_is_alive(int(pid)):
        return state
    write_process_receipt(
        root,
        project=project,
        job_id=job_id,
        attempt_id=active["attempt_id"],
        idempotency_key=active["idempotency_key"],
        lease_token=active["lease_token"],
        outcome="failed_recoverable",
        exit_code=1,
        result={"status": "failed", "reason": "worker_exited_without_receipt"},
        now=timestamp,
    )
    return consume_process_receipt(
        root, project=project, job_id=job_id, now=timestamp
    )


class BackgroundJobBusy(RuntimeError):
    """Raised when another controller owns the same job tick."""


@contextmanager
def _controller_lock(root: Path, project: str, job_id: str):
    path = job_dir(root, project, job_id) / ".controller.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise BackgroundJobBusy(f"background job is already controlled: {job_id}") from exc
        handle.seek(0)
        handle.truncate()
        handle.write(f"pid: {os.getpid()}\n")
        handle.flush()
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def pause_job(
    root: Path,
    *,
    project: str,
    job_id: str,
    now: str | None = None,
) -> dict[str, Any]:
    """Pause scheduling without killing an already-running worker.

    A returned worker receipt is still consumed exactly once. Its resulting
    next state is saved in ``paused_from_status`` and resumed explicitly.
    """
    timestamp = _now(now)
    with _controller_lock(root, project, job_id):
        state = load_job_state(root, project, job_id)
        if state["status"] in TERMINAL_STATES:
            return state
        if state.get("pause_requested") and state.get("status") == "paused":
            return state
        if state.get("status") != "paused":
            state["paused_from_status"] = state["status"]
        state["pause_requested"] = True
        state["paused_at"] = timestamp
        state["status"] = "paused"
        _save_state(root, project, job_id, state, now=timestamp)
        _append_event(
            root,
            project,
            job_id,
            "JOB_PAUSED",
            status="paused",
            now=timestamp,
            payload={
                "resume_status": state.get("paused_from_status"),
                "active_attempt": state.get("active_attempt"),
            },
        )
        return state


def resume_job(
    root: Path,
    *,
    project: str,
    job_id: str,
    now: str | None = None,
) -> dict[str, Any]:
    """Resume a user-paused job from its exact reducer state."""
    timestamp = _now(now)
    with _controller_lock(root, project, job_id):
        state = load_job_state(root, project, job_id)
        if state["status"] in TERMINAL_STATES:
            return state
        if not state.get("pause_requested") and state.get("status") != "paused":
            return state
        resume_status = str(state.get("paused_from_status") or "queued")
        state["status"] = resume_status
        state["pause_requested"] = False
        state["paused_from_status"] = None
        state["paused_at"] = None
        _save_state(root, project, job_id, state, now=timestamp)
        _append_event(
            root,
            project,
            job_id,
            "JOB_RESUMED",
            status=resume_status,
            now=timestamp,
            payload={"active_attempt": state.get("active_attempt")},
        )
        return state


def retry_blocked_job(
    root: Path,
    *,
    project: str,
    job_id: str,
    repair_reason: str,
    now: str | None = None,
) -> dict[str, Any]:
    """Reopen one exhausted action after an explicit runtime/config repair."""
    if not repair_reason.strip():
        raise ValueError("repair_reason is required")
    timestamp = _now(now)
    with _controller_lock(root, project, job_id):
        state = load_job_state(root, project, job_id)
        retry_action = str(state.get("retry_action") or "")
        if state.get("status") != "blocked":
            raise ValueError("job is not blocked")
        if state.get("active_attempt"):
            raise ValueError("blocked job still has an active attempt")
        if retry_action not in ACTION_RUNNING_STATE:
            raise ValueError("blocked job has no retryable action")

        previous_error = state.get("last_error")
        retry_counts = dict(state.get("retry_counts") or {})
        retry_counts[retry_action] = 0
        state["retry_counts"] = retry_counts
        state["status"] = "failed_recoverable"
        state["retry_at"] = None
        state["last_error"] = None
        _save_state(root, project, job_id, state, now=timestamp)

        feedback_path = job_dir(root, project, job_id) / "operator_feedback.yml"
        feedback = safe_read_yaml(feedback_path)
        if isinstance(feedback, dict):
            feedback["status"] = "superseded"
            feedback["superseded_at"] = timestamp
            feedback["superseded_reason"] = repair_reason.strip()
            atomic_write_yaml(feedback_path, feedback)
        _append_event(
            root,
            project,
            job_id,
            "BLOCKED_JOB_REOPENED_AFTER_REPAIR",
            status=state["status"],
            now=timestamp,
            payload={
                "retry_action": retry_action,
                "previous_error": previous_error,
                "repair_reason": repair_reason.strip(),
            },
        )
        return state


def launch_active_attempt(
    root: Path,
    *,
    project: str,
    job_id: str,
    python_executable: str | None = None,
    popen_factory: Callable[..., Any] = subprocess.Popen,
    now: str | None = None,
) -> dict[str, Any]:
    """Launch the active attempt as a detached receipt-writing worker."""
    timestamp = _now(now)
    state = load_job_state(root, project, job_id)
    active = state.get("active_attempt")
    if not active:
        raise ValueError("job has no active attempt")
    if active.get("worker_pid") is not None:
        return dict(active)
    attempt_dir = job_dir(root, project, job_id) / "attempts" / active["attempt_id"]
    attempt_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = attempt_dir / "worker_stdout.log"
    stderr_path = attempt_dir / "worker_stderr.log"
    command = [
        python_executable or sys.executable,
        "-m",
        "agent_runtime.background_job_worker",
        "--root",
        str(Path(root).resolve()),
        "--project",
        project,
        "--job-id",
        job_id,
        "--attempt-id",
        active["attempt_id"],
    ]
    with stdout_path.open("ab") as stdout, stderr_path.open("ab") as stderr:
        process = popen_factory(
            command,
            cwd=str(Path(root).resolve()),
            env=_runtime_subprocess_env(root),
            stdout=stdout,
            stderr=stderr,
            start_new_session=True,
            close_fds=True,
        )
    state = mark_attempt_started(
        root,
        project=project,
        job_id=job_id,
        attempt_id=active["attempt_id"],
        worker_pid=int(process.pid),
        now=timestamp,
    )
    active = dict(state["active_attempt"])
    active["worker_stdout_path"] = str(stdout_path)
    active["worker_stderr_path"] = str(stderr_path)
    _append_event(
        root,
        project,
        job_id,
        "WORKER_LAUNCHED",
        status=state["status"],
        now=timestamp,
        payload={
            "attempt_id": active["attempt_id"],
            "action": active["action"],
            "worker_pid": int(process.pid),
        },
    )
    return active


def _write_controller_heartbeat(
    root: Path,
    project: str,
    job_id: str,
    state: dict[str, Any],
    *,
    now: str,
) -> None:
    atomic_write_yaml(
        job_dir(root, project, job_id) / "controller_heartbeat.yml",
        {
            "schema_version": SCHEMA_VERSION,
            "controller_pid": os.getpid(),
            "recorded_at": now,
            "job_id": job_id,
            "project": project,
            "status": state["status"],
            "active_attempt": state.get("active_attempt"),
            "pause_requested": bool(state.get("pause_requested")),
        },
    )


def controller_cycle(
    root: Path,
    *,
    project: str,
    job_id: str,
    execute: bool = False,
    pid_is_alive: Callable[[int], bool] = _default_pid_is_alive,
    popen_factory: Callable[..., Any] = subprocess.Popen,
    python_executable: str | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    """Consume one returned result, schedule one action, and optionally launch it."""
    timestamp = _now(now)
    with _controller_lock(root, project, job_id):
        state = recover_orphaned_attempt(
            root,
            project=project,
            job_id=job_id,
            pid_is_alive=pid_is_alive,
            now=timestamp,
        )
        state = consume_process_receipt(
            root, project=project, job_id=job_id, now=timestamp
        )
        active = state.get("active_attempt")
        if not active and state["status"] not in TERMINAL_STATES:
            schedule_next_attempt(
                root, project=project, job_id=job_id, now=timestamp
            )
            state = load_job_state(root, project, job_id)
            active = state.get("active_attempt")
        if (
            execute
            and active
            and active.get("worker_pid") is None
            and not state.get("pause_requested")
        ):
            launch_active_attempt(
                root,
                project=project,
                job_id=job_id,
                python_executable=python_executable,
                popen_factory=popen_factory,
                now=timestamp,
            )
            state = load_job_state(root, project, job_id)
        _write_controller_heartbeat(
            root, project, job_id, state, now=timestamp
        )
        return {
            "job_id": job_id,
            "project": project,
            "status": state["status"],
            "revision": state["revision"],
            "active_attempt": state.get("active_attempt"),
            "capacity_reset_at": state.get("capacity_reset_at"),
            "retry_at": state.get("retry_at"),
            "pause_requested": bool(state.get("pause_requested")),
            "stopped": state["status"] in CONTROLLER_STOP_STATES,
            "terminal": state["status"] in TERMINAL_STATES,
        }


def run_controller_loop(
    root: Path,
    *,
    project: str,
    job_id: str,
    poll_seconds: float = 5.0,
    max_cycles: int | None = None,
) -> dict[str, Any]:
    """Run the receipt controller until completion, block, or cycle limit."""
    cycles = 0
    while max_cycles is None or cycles < max_cycles:
        result = controller_cycle(
            root, project=project, job_id=job_id, execute=True
        )
        cycles += 1
        if result["terminal"] or result["stopped"]:
            return result
        delay = max(0.05, poll_seconds)
        reset_at = result.get("capacity_reset_at")
        if result["status"] == "capacity_wait" and reset_at:
            remaining = (_parse_timestamp(reset_at) - datetime.now(timezone.utc)).total_seconds()
            delay = max(0.05, min(delay, max(0.05, remaining)))
        retry_at = result.get("retry_at")
        if result["status"] == "retry_wait" and retry_at:
            remaining = (_parse_timestamp(retry_at) - datetime.now(timezone.utc)).total_seconds()
            delay = max(0.05, min(delay, max(0.05, remaining)))
        time.sleep(delay)
    return controller_cycle(
        root, project=project, job_id=job_id, execute=False
    )


def launch_controller_service(
    root: Path,
    *,
    project: str,
    job_id: str,
    poll_seconds: float = 5.0,
    python_executable: str | None = None,
    popen_factory: Callable[..., Any] = subprocess.Popen,
) -> dict[str, Any]:
    """Detach one controller service; workers remain independently receipted."""
    directory = job_dir(root, project, job_id)
    stdout_path = directory / "controller_stdout.log"
    stderr_path = directory / "controller_stderr.log"
    command = [
        python_executable or sys.executable,
        "-m",
        "agent_runtime.background_job_service",
        "--root",
        str(Path(root).resolve()),
        "--project",
        project,
        "--job-id",
        job_id,
        "--poll-seconds",
        str(poll_seconds),
    ]
    with stdout_path.open("ab") as stdout, stderr_path.open("ab") as stderr:
        process = popen_factory(
            command,
            cwd=str(Path(root).resolve()),
            env=_runtime_subprocess_env(root),
            stdout=stdout,
            stderr=stderr,
            start_new_session=True,
            close_fds=True,
        )
    record = {
        "schema_version": SCHEMA_VERSION,
        "controller_pid": int(process.pid),
        "launched_at": _now(),
        "project": project,
        "job_id": job_id,
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
    }
    atomic_write_yaml(directory / "controller_service.yml", record)
    return record
