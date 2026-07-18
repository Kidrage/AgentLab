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


SCHEMA_VERSION = 1
TERMINAL_STATES = {"completed", "blocked"}
CONTROLLER_STOP_STATES = {"paused"}
ACTION_RUNNING_STATE = {
    "preflight": "preflight",
    "generate_batch": "generating_batch",
    "deterministic_check": "deterministic_check",
    "heavy_audit": "heavy_auditing",
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
    return state


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
    project_root = Path(root) / "projects" / project
    if not project_root.is_dir():
        raise FileNotFoundError(project_root)
    directory = job_dir(root, project, job_id)
    if directory.exists():
        raise FileExistsError(directory)
    directory.mkdir(parents=True)
    recorded_at = _now(now)
    state: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "job_id": job_id,
        "job_type": "crown_narrative_delivery",
        "project": project,
        "status": "queued",
        "revision": 1,
        "created_at": recorded_at,
        "updated_at": recorded_at,
        "candidate_only": True,
        "production_allowed": False,
        "preflight_passed": False,
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
        "capacity_reset_at": None,
        "capacity_resume_count": 0,
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


def _attempt_request(
    root: Path,
    state: dict[str, Any],
    *,
    action: str,
    attempt_id: str,
    idempotency_key: str,
    now: str,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "job_id": state["job_id"],
        "project": state["project"],
        "attempt_id": attempt_id,
        "idempotency_key": idempotency_key,
        "action": action,
        "scheduled_at": now,
        "candidate_only": True,
        "production_allowed": False,
        "batch": dict(state["current_batch"]),
        "config": dict(state["config"]),
        "prior_results": dict(state.get("last_action_results") or {}),
        "agentlab_root": str(Path(root).resolve()),
    }


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
    if state["status"] == "capacity_wait":
        return None
    if state["status"] == "batch_sealed":
        _advance_sealed_batch(state)
    action = _action_for_state(state)
    if action is None:
        if woke_capacity:
            _save_state(root, project, job_id, state, now=timestamp)
        return None

    sequence = int(state.get("attempt_sequence", 0)) + 1
    attempt_id = f"attempt-{sequence:04d}-{action.replace('_', '-')}"
    idempotency_key = f"{job_id}:{attempt_id}"
    attempt_dir = job_dir(root, project, job_id) / "attempts" / attempt_id
    request_path = attempt_dir / "action_request.yml"
    request = _attempt_request(
        root,
        state,
        action=action,
        attempt_id=attempt_id,
        idempotency_key=idempotency_key,
        now=timestamp,
    )
    atomic_write_yaml(request_path, request)
    active = {
        "attempt_id": attempt_id,
        "idempotency_key": idempotency_key,
        "action": action,
        "scheduled_at": timestamp,
        "worker_pid": None,
        "execution_started_at": None,
        "action_request_path": str(request_path),
    }
    state["attempt_sequence"] = sequence
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
    outcome: str,
    exit_code: int,
    result: dict[str, Any],
    capacity_reset_at: str | None = None,
    now: str | None = None,
) -> Path:
    """Atomically record a returned action result without applying it."""
    if outcome not in {"success", "failed_recoverable", "failed", "capacity_wait"}:
        raise ValueError(f"unsupported process outcome: {outcome}")
    path = process_receipt_path(root, project, job_id, attempt_id)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "job_id": job_id,
        "project": project,
        "attempt_id": attempt_id,
        "idempotency_key": idempotency_key,
        "outcome": outcome,
        "exit_code": int(exit_code),
        "completed_at": _now(now),
        "capacity_reset_at": capacity_reset_at,
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


def _requires_heavy_audit(state: dict[str, Any]) -> bool:
    end = int(state["current_batch"]["end"])
    config = state["config"]
    return (
        end >= int(config["end_chapter"])
        or end % int(config["heavy_audit_cadence"]) == 0
    )


def _seal_current_batch(state: dict[str, Any], now: str) -> None:
    batch = dict(state["current_batch"])
    if not any(item.get("number") == batch["number"] for item in state["sealed_batches"]):
        batch["sealed_at"] = now
        state["sealed_batches"].append(batch)
    state["status"] = "batch_sealed"


def _successful_transition(state: dict[str, Any], action: str, result: dict[str, Any], now: str) -> None:
    result_status = str(result.get("status") or "pass").lower()
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
        state["status"] = (
            "awaiting_heavy_audit" if _requires_heavy_audit(state) else "batch_sealed"
        )
        if state["status"] == "batch_sealed":
            _seal_current_batch(state, now)
    elif action == "heavy_audit":
        if bool(result.get("requires_rewrite")):
            state["status"] = "rewrite_required"
        else:
            _seal_current_batch(state, now)
    elif action == "rewrite_batch":
        state["status"] = "deterministic_reaudit"
    elif action == "deterministic_reaudit":
        _seal_current_batch(state, now)
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
    if state.get("status") != "completed":
        return None
    path = job_dir(root, project, job_id) / "completion_receipt.yml"
    if not path.exists():
        atomic_write_yaml(
            path,
            {
                "schema_version": SCHEMA_VERSION,
                "job_id": job_id,
                "project": project,
                "status": "completed",
                "completed_at": now,
                "candidate_only": True,
                "production_modified": False,
                "chapter_range": [
                    state["config"]["start_chapter"],
                    state["config"]["end_chapter"],
                ],
                "sealed_batches": state.get("sealed_batches", []),
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

    event = "COMPLETED" if status == "completed" else "BLOCKED"
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
