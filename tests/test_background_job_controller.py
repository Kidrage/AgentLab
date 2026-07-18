from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import yaml

from agent_runtime.background_job_controller import (
    controller_cycle,
    consume_process_receipt,
    create_crown_delivery_job,
    load_job_state,
    launch_active_attempt,
    mark_attempt_started,
    pause_job,
    recover_orphaned_attempt,
    retry_blocked_job,
    resume_job,
    schedule_next_attempt,
    write_process_receipt,
)


NOW = "2026-07-17T15:00:00+00:00"


def _create_job(
    root: Path,
    *,
    end_chapter: int = 20,
    heavy_audit_cadence: int = 10,
) -> dict:
    (root / "projects" / "Crown_of_Ash").mkdir(parents=True)
    return create_crown_delivery_job(
        root,
        project="Crown_of_Ash",
        job_id="crown-200-v3",
        eval_id="crown_corrected_200_v3_writer",
        start_chapter=1,
        end_chapter=end_chapter,
        batch_size=10,
        heavy_audit_cadence=heavy_audit_cadence,
        writer_worker="claude_writer",
        chapter_state_plan="runs/shared/chapter_state_plan.yml",
        now=NOW,
    )


def _complete_active(
    root: Path,
    *,
    outcome: str = "success",
    result: dict | None = None,
    capacity_reset_at: str | None = None,
    retry_at: str | None = None,
) -> dict:
    state = load_job_state(root, "Crown_of_Ash", "crown-200-v3")
    active = state["active_attempt"]
    write_process_receipt(
        root,
        project="Crown_of_Ash",
        job_id="crown-200-v3",
        attempt_id=active["attempt_id"],
        idempotency_key=active["idempotency_key"],
        outcome=outcome,
        exit_code=0 if outcome == "success" else 1,
        result=result or {},
        capacity_reset_at=capacity_reset_at,
        retry_at=retry_at,
        now=NOW,
    )
    return consume_process_receipt(
        root,
        project="Crown_of_Ash",
        job_id="crown-200-v3",
        now=NOW,
    )


def _pass_preflight(root: Path) -> None:
    attempt = schedule_next_attempt(
        root, project="Crown_of_Ash", job_id="crown-200-v3", now=NOW
    )
    assert attempt["action"] == "preflight"
    state = _complete_active(root, result={"status": "pass"})
    assert state["status"] == "queued"
    assert state["preflight_passed"] is True


def _reach_heavy_audit(root: Path) -> None:
    _pass_preflight(root)
    generation = schedule_next_attempt(
        root, project="Crown_of_Ash", job_id="crown-200-v3", now=NOW
    )
    assert generation["action"] == "generate_batch"
    state = _complete_active(root, result={"status": "pass"})
    assert state["status"] == "deterministic_check"

    deterministic = schedule_next_attempt(
        root, project="Crown_of_Ash", job_id="crown-200-v3", now=NOW
    )
    assert deterministic["action"] == "deterministic_check"
    state = _complete_active(root, result={"status": "pass"})
    assert state["status"] == "awaiting_heavy_audit"


def test_create_job_writes_project_scoped_authoritative_state(tmp_path: Path) -> None:
    state = _create_job(tmp_path)

    job_dir = (
        tmp_path
        / "projects"
        / "Crown_of_Ash"
        / "background_jobs"
        / "crown-200-v3"
    )
    assert state["status"] == "queued"
    assert state["candidate_only"] is True
    assert state["production_allowed"] is False
    assert state["current_batch"] == {"number": 1, "start": 1, "end": 10}
    assert (job_dir / "job_state.yml").is_file()
    assert (job_dir / "job_events.jsonl").is_file()


def test_event_log_appends_without_rereading_history(tmp_path: Path) -> None:
    _create_job(tmp_path)
    event_path = (
        tmp_path
        / "projects/Crown_of_Ash/background_jobs/crown-200-v3/job_events.jsonl"
    )
    read_text = Path.read_text

    def reject_event_history_read(path: Path, *args, **kwargs):
        if path == event_path:
            raise AssertionError("event history must not be reread for append")
        return read_text(path, *args, **kwargs)

    with patch.object(Path, "read_text", reject_event_history_read):
        schedule_next_attempt(
            tmp_path, project="Crown_of_Ash", job_id="crown-200-v3", now=NOW
        )

    events = [json.loads(line) for line in read_text(event_path).splitlines()]
    assert [event["event_type"] for event in events] == [
        "JOB_CREATED",
        "ATTEMPT_SCHEDULED",
    ]


def test_receipt_drives_generate_check_then_heavy_audit_in_order(tmp_path: Path) -> None:
    _create_job(tmp_path)
    _reach_heavy_audit(tmp_path)

    attempt = schedule_next_attempt(
        tmp_path, project="Crown_of_Ash", job_id="crown-200-v3", now=NOW
    )
    assert attempt["action"] == "heavy_audit"
    request = yaml.safe_load(Path(attempt["action_request_path"]).read_text())
    assert request["batch"] == {"number": 1, "start": 1, "end": 10}


def test_pause_stops_scheduling_and_resume_restores_exact_state(tmp_path: Path) -> None:
    _create_job(tmp_path)

    paused = pause_job(
        tmp_path, project="Crown_of_Ash", job_id="crown-200-v3", now=NOW
    )
    assert paused["status"] == "paused"
    assert paused["paused_from_status"] == "queued"
    assert schedule_next_attempt(
        tmp_path, project="Crown_of_Ash", job_id="crown-200-v3", now=NOW
    ) is None

    resumed = resume_job(
        tmp_path, project="Crown_of_Ash", job_id="crown-200-v3", now=NOW
    )
    assert resumed["status"] == "queued"
    assert resumed["pause_requested"] is False
    assert schedule_next_attempt(
        tmp_path, project="Crown_of_Ash", job_id="crown-200-v3", now=NOW
    )["action"] == "preflight"


def test_pause_during_worker_waits_for_receipt_then_keeps_next_state_paused(
    tmp_path: Path,
) -> None:
    _create_job(tmp_path)
    attempt = schedule_next_attempt(
        tmp_path, project="Crown_of_Ash", job_id="crown-200-v3", now=NOW
    )
    pause_job(tmp_path, project="Crown_of_Ash", job_id="crown-200-v3", now=NOW)
    write_process_receipt(
        tmp_path,
        project="Crown_of_Ash",
        job_id="crown-200-v3",
        attempt_id=attempt["attempt_id"],
        idempotency_key=attempt["idempotency_key"],
        outcome="success",
        exit_code=0,
        result={"status": "pass"},
        now=NOW,
    )

    state = consume_process_receipt(
        tmp_path, project="Crown_of_Ash", job_id="crown-200-v3", now=NOW
    )
    assert state["status"] == "paused"
    assert state["paused_from_status"] == "queued"
    assert state["preflight_passed"] is True
    assert state["active_attempt"] is None

    resumed = resume_job(
        tmp_path, project="Crown_of_Ash", job_id="crown-200-v3", now=NOW
    )
    assert resumed["status"] == "queued"
    next_attempt = schedule_next_attempt(
        tmp_path, project="Crown_of_Ash", job_id="crown-200-v3", now=NOW
    )
    assert next_attempt["action"] == "generate_batch"


def test_receipt_is_consumed_once_after_controller_restart(tmp_path: Path) -> None:
    _create_job(tmp_path)
    _pass_preflight(tmp_path)
    schedule_next_attempt(
        tmp_path, project="Crown_of_Ash", job_id="crown-200-v3", now=NOW
    )
    before = load_job_state(tmp_path, "Crown_of_Ash", "crown-200-v3")
    active = before["active_attempt"]
    write_process_receipt(
        tmp_path,
        project="Crown_of_Ash",
        job_id="crown-200-v3",
        attempt_id=active["attempt_id"],
        idempotency_key=active["idempotency_key"],
        outcome="success",
        exit_code=0,
        result={"status": "pass"},
        now=NOW,
    )

    first = consume_process_receipt(
        tmp_path, project="Crown_of_Ash", job_id="crown-200-v3", now=NOW
    )
    event_path = (
        tmp_path
        / "projects/Crown_of_Ash/background_jobs/crown-200-v3/job_events.jsonl"
    )
    event_count = len(event_path.read_text().splitlines())
    second = consume_process_receipt(
        tmp_path, project="Crown_of_Ash", job_id="crown-200-v3", now=NOW
    )

    assert first["status"] == "deterministic_check"
    assert second["revision"] == first["revision"]
    assert len(event_path.read_text().splitlines()) == event_count
    assert first["processed_receipt_keys"][-1] == active["idempotency_key"]
    assert first["processed_receipt_keys"].count(active["idempotency_key"]) == 1


def test_dead_worker_without_receipt_becomes_recoverable_and_retries(tmp_path: Path) -> None:
    _create_job(tmp_path)
    _pass_preflight(tmp_path)
    attempt = schedule_next_attempt(
        tmp_path, project="Crown_of_Ash", job_id="crown-200-v3", now=NOW
    )
    mark_attempt_started(
        tmp_path,
        project="Crown_of_Ash",
        job_id="crown-200-v3",
        attempt_id=attempt["attempt_id"],
        worker_pid=999_999,
        now=NOW,
    )

    state = recover_orphaned_attempt(
        tmp_path,
        project="Crown_of_Ash",
        job_id="crown-200-v3",
        pid_is_alive=lambda _pid: False,
        now=NOW,
    )
    assert state["status"] == "failed_recoverable"
    assert state["active_attempt"] is None

    retry = schedule_next_attempt(
        tmp_path, project="Crown_of_Ash", job_id="crown-200-v3", now=NOW
    )
    assert retry["action"] == "generate_batch"
    assert retry["attempt_id"] != attempt["attempt_id"]


def test_capacity_wait_resumes_once_after_observed_reset(tmp_path: Path) -> None:
    _create_job(tmp_path)
    _pass_preflight(tmp_path)
    first = schedule_next_attempt(
        tmp_path, project="Crown_of_Ash", job_id="crown-200-v3", now=NOW
    )
    state = _complete_active(
        tmp_path,
        outcome="capacity_wait",
        result={"status": "blocked", "reason": "quota_exhausted"},
        capacity_reset_at="2026-07-17T16:00:00+00:00",
    )
    assert state["status"] == "capacity_wait"

    assert schedule_next_attempt(
        tmp_path,
        project="Crown_of_Ash",
        job_id="crown-200-v3",
        now="2026-07-17T15:59:59+00:00",
    ) is None
    resumed = schedule_next_attempt(
        tmp_path,
        project="Crown_of_Ash",
        job_id="crown-200-v3",
        now="2026-07-17T16:00:01+00:00",
    )
    assert resumed["action"] == "generate_batch"
    assert resumed["attempt_id"] != first["attempt_id"]
    state = load_job_state(tmp_path, "Crown_of_Ash", "crown-200-v3")
    assert state["capacity_resume_count"] == 1
    assert state["capacity_reset_at"] is None


def test_transient_retry_wait_resumes_without_spending_failure_retry(tmp_path: Path) -> None:
    _create_job(tmp_path)
    _pass_preflight(tmp_path)
    first = schedule_next_attempt(
        tmp_path, project="Crown_of_Ash", job_id="crown-200-v3", now=NOW
    )
    state = _complete_active(
        tmp_path,
        outcome="retry_wait",
        result={"status": "blocked", "reason": "network_required"},
        retry_at="2026-07-17T15:15:00+00:00",
    )

    assert state["status"] == "retry_wait"
    assert state["retry_counts"].get("generate_batch") is None
    assert schedule_next_attempt(
        tmp_path,
        project="Crown_of_Ash",
        job_id="crown-200-v3",
        now="2026-07-17T15:14:59+00:00",
    ) is None

    resumed = schedule_next_attempt(
        tmp_path,
        project="Crown_of_Ash",
        job_id="crown-200-v3",
        now="2026-07-17T15:15:01+00:00",
    )
    assert resumed["action"] == "generate_batch"
    assert resumed["attempt_id"] != first["attempt_id"]
    state = load_job_state(tmp_path, "Crown_of_Ash", "crown-200-v3")
    assert state["retry_resume_count"] == 1
    assert state["retry_at"] is None


def test_blocking_heavy_audit_requires_rewrite_then_deterministic_reaudit(
    tmp_path: Path,
) -> None:
    _create_job(tmp_path)
    _reach_heavy_audit(tmp_path)
    schedule_next_attempt(
        tmp_path, project="Crown_of_Ash", job_id="crown-200-v3", now=NOW
    )
    state = _complete_active(
        tmp_path,
        result={"status": "pass", "requires_rewrite": True},
    )
    assert state["status"] == "rewrite_required"

    rewrite = schedule_next_attempt(
        tmp_path, project="Crown_of_Ash", job_id="crown-200-v3", now=NOW
    )
    assert rewrite["action"] == "rewrite_batch"
    state = _complete_active(tmp_path, result={"status": "pass"})
    assert state["status"] == "deterministic_reaudit"

    reaudit = schedule_next_attempt(
        tmp_path, project="Crown_of_Ash", job_id="crown-200-v3", now=NOW
    )
    assert reaudit["action"] == "deterministic_reaudit"
    state = _complete_active(tmp_path, result={"status": "pass"})
    assert state["status"] == "batch_sealed"


def test_final_acceptance_writes_completion_receipt(tmp_path: Path) -> None:
    _create_job(tmp_path, end_chapter=10)
    _reach_heavy_audit(tmp_path)
    schedule_next_attempt(
        tmp_path, project="Crown_of_Ash", job_id="crown-200-v3", now=NOW
    )
    state = _complete_active(
        tmp_path, result={"status": "pass", "requires_rewrite": False}
    )
    assert state["status"] == "batch_sealed"

    final = schedule_next_attempt(
        tmp_path, project="Crown_of_Ash", job_id="crown-200-v3", now=NOW
    )
    assert final["action"] == "final_acceptance"
    state = _complete_active(tmp_path, result={"status": "pass"})
    assert state["status"] == "completed"

    receipt_path = (
        tmp_path
        / "projects/Crown_of_Ash/background_jobs/crown-200-v3/completion_receipt.yml"
    )
    receipt = yaml.safe_load(receipt_path.read_text())
    assert receipt["status"] == "completed"
    assert receipt["candidate_only"] is True
    assert receipt["production_modified"] is False
    events = [
        json.loads(line)
        for line in (
            tmp_path
            / "projects/Crown_of_Ash/background_jobs/crown-200-v3/job_events.jsonl"
        ).read_text().splitlines()
    ]
    assert [event["event_type"] for event in events].count("JOB_COMPLETED") == 1


def test_terminal_receipt_dispatches_existing_operator_feedback_once(
    tmp_path: Path,
) -> None:
    _create_job(tmp_path, end_chapter=10)
    _reach_heavy_audit(tmp_path)
    schedule_next_attempt(
        tmp_path, project="Crown_of_Ash", job_id="crown-200-v3", now=NOW
    )
    _complete_active(tmp_path, result={"status": "pass", "requires_rewrite": False})
    schedule_next_attempt(
        tmp_path, project="Crown_of_Ash", job_id="crown-200-v3", now=NOW
    )

    with patch(
        "agent_runtime.webhook_dispatcher.dispatch_event",
        return_value={"ok": True, "enabled": False, "deliveries": []},
    ) as dispatch:
        state = _complete_active(tmp_path, result={"status": "pass"})
        consume_process_receipt(
            tmp_path, project="Crown_of_Ash", job_id="crown-200-v3", now=NOW
        )

    assert state["status"] == "completed"
    assert dispatch.call_count == 1
    assert dispatch.call_args.kwargs["event"] == "COMPLETED"
    feedback_path = (
        tmp_path
        / "projects/Crown_of_Ash/background_jobs/crown-200-v3/operator_feedback.yml"
    )
    feedback = yaml.safe_load(feedback_path.read_text())
    assert feedback["status"] == "pass"
    assert feedback["feedback_id"] == "crown-200-v3:completed"


def test_blocked_result_writes_blocked_operator_feedback(tmp_path: Path) -> None:
    _create_job(tmp_path)
    schedule_next_attempt(
        tmp_path, project="Crown_of_Ash", job_id="crown-200-v3", now=NOW
    )

    with patch(
        "agent_runtime.webhook_dispatcher.dispatch_event",
        return_value={"ok": True, "enabled": False, "deliveries": []},
    ) as dispatch:
        state = _complete_active(
            tmp_path,
            result={"status": "blocked", "reason": "validated_plan_missing"},
        )

    assert state["status"] == "blocked"
    assert dispatch.call_args.kwargs["event"] == "BLOCKED"
    feedback_path = (
        tmp_path
        / "projects/Crown_of_Ash/background_jobs/crown-200-v3/operator_feedback.yml"
    )
    feedback = yaml.safe_load(feedback_path.read_text())
    assert feedback["status"] == "pass"
    assert feedback["reason"] == "validated_plan_missing"


def test_launch_uses_isolated_worker_and_records_pid(tmp_path: Path) -> None:
    _create_job(tmp_path)
    attempt = schedule_next_attempt(
        tmp_path, project="Crown_of_Ash", job_id="crown-200-v3", now=NOW
    )
    observed: dict = {}

    class Process:
        pid = 43210

    def fake_popen(command, **kwargs):
        observed["command"] = command
        observed["kwargs"] = kwargs
        return Process()

    launched = launch_active_attempt(
        tmp_path,
        project="Crown_of_Ash",
        job_id="crown-200-v3",
        python_executable="/test/python",
        popen_factory=fake_popen,
        now=NOW,
    )
    assert observed["command"][:3] == [
        "/test/python",
        "-m",
        "agent_runtime.background_job_worker",
    ]
    assert observed["kwargs"]["start_new_session"] is True
    python_path = observed["kwargs"]["env"]["PYTHONPATH"].split(":")
    assert python_path[:2] == [str(tmp_path), str(tmp_path / "agent_runtime")]
    assert launched["worker_pid"] == 43210
    state = load_job_state(tmp_path, "Crown_of_Ash", "crown-200-v3")
    assert state["active_attempt"]["attempt_id"] == attempt["attempt_id"]
    assert state["active_attempt"]["worker_pid"] == 43210


def test_retry_blocked_reopens_exhausted_action_after_explicit_repair(
    tmp_path: Path,
) -> None:
    _create_job(tmp_path)
    _reach_heavy_audit(tmp_path)
    for attempt_number in range(4):
        attempt = schedule_next_attempt(
            tmp_path,
            project="Crown_of_Ash",
            job_id="crown-200-v3",
            now=NOW,
        )
        assert attempt["action"] == "heavy_audit"
        state = _complete_active(
            tmp_path,
            outcome="failed_recoverable",
            result={"status": "failed", "reason": f"runtime failure {attempt_number}"},
        )

    assert state["status"] == "blocked"
    reopened = retry_blocked_job(
        tmp_path,
        project="Crown_of_Ash",
        job_id="crown-200-v3",
        repair_reason="fixed detached worker import path",
        now=NOW,
    )

    assert reopened["status"] == "failed_recoverable"
    assert reopened["retry_counts"]["heavy_audit"] == 0
    assert reopened["last_error"] is None
    retry = schedule_next_attempt(
        tmp_path,
        project="Crown_of_Ash",
        job_id="crown-200-v3",
        now=NOW,
    )
    assert retry["action"] == "heavy_audit"


def test_controller_cycle_consumes_returned_receipt_before_scheduling_next(
    tmp_path: Path,
) -> None:
    _create_job(tmp_path)
    attempt = schedule_next_attempt(
        tmp_path, project="Crown_of_Ash", job_id="crown-200-v3", now=NOW
    )
    write_process_receipt(
        tmp_path,
        project="Crown_of_Ash",
        job_id="crown-200-v3",
        attempt_id=attempt["attempt_id"],
        idempotency_key=attempt["idempotency_key"],
        outcome="success",
        exit_code=0,
        result={"status": "pass"},
        now=NOW,
    )

    cycle = controller_cycle(
        tmp_path,
        project="Crown_of_Ash",
        job_id="crown-200-v3",
        execute=False,
        now=NOW,
    )
    assert cycle["status"] == "generating_batch"
    assert cycle["active_attempt"]["action"] == "generate_batch"
    assert cycle["active_attempt"]["worker_pid"] is None
