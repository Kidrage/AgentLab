from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agent_runtime.feedback_manager import create_decision_card, resolve_decision_card
from agent_runtime.legacy_runtime_guard import (
    LegacyRuntimeAuthorityError,
    legacy_run_shadowed_by_v2,
    runtime_v2_identity_path,
)
from agent_runtime.progress_tracker import create_progress, save_progress
from agent_runtime.state_store import TaskEvents, save_state
from agent_runtime.task_events import append_task_event
from agent_runtime.task_runtime_v2.runtime import TaskRuntime
from agent_runtime.watchdog import inspect_task, scan_project


def _legacy_run(root: Path, task_id: str = "task_0001") -> Path:
    run_dir = root / "projects" / "Demo" / "runs" / task_id
    run_dir.mkdir(parents=True)
    (run_dir / "state.yml").write_text(
        yaml.safe_dump(
            {
                "project": "Demo",
                "task_id": task_id,
                "status": "running",
                "last_event": "legacy running",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (run_dir / "progress.yml").write_text(
        yaml.safe_dump(
            {
                "project": "Demo",
                "task_id": task_id,
                "status": "running",
                "current_stage": "legacy",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return run_dir


def _create_v2(root: Path, task_id: str = "task_0001") -> TaskRuntime:
    runtime = TaskRuntime(root, project="Demo")
    runtime.create_task(
        task_id=task_id,
        title="Authoritative v2 task",
        user_goal="Prove Runtime v2 owns this task identity.",
        idempotency_key=f"create-{task_id}",
    )
    return runtime


def test_guard_recognizes_only_canonical_legacy_run_layout(tmp_path: Path) -> None:
    run_dir = tmp_path / "projects" / "Demo" / "runs" / "task_0001"

    assert runtime_v2_identity_path(run_dir) == (
        tmp_path / "projects" / "Demo" / "runtime" / "tasks" / "task_0001"
    )
    assert runtime_v2_identity_path(tmp_path / "fixtures" / "task_0001") is None
    assert legacy_run_shadowed_by_v2(run_dir) is False

    _create_v2(tmp_path)

    assert legacy_run_shadowed_by_v2(run_dir) is True


def test_state_and_progress_writers_fail_closed_without_mutating_legacy_bytes(
    tmp_path: Path,
) -> None:
    run_dir = _legacy_run(tmp_path)
    state_path = run_dir / "state.yml"
    progress_path = run_dir / "progress.yml"
    state_before = state_path.read_bytes()
    progress_before = progress_path.read_bytes()
    _create_v2(tmp_path)

    state_payload = {"project": "Demo", "task_id": "task_0001", "status": "paused"}
    progress_payload = {"project": "Demo", "task_id": "task_0001", "status": "paused"}

    with pytest.raises(LegacyRuntimeAuthorityError, match="Task Runtime v2 is authoritative"):
        save_state(run_dir, state_payload)
    with pytest.raises(LegacyRuntimeAuthorityError, match="Task Runtime v2 is authoritative"):
        save_progress(run_dir, progress_payload)
    with pytest.raises(LegacyRuntimeAuthorityError, match="Task Runtime v2 is authoritative"):
        create_progress(run_dir, "Demo", "task_0001", ["Supervisor"])

    assert state_path.read_bytes() == state_before
    assert progress_path.read_bytes() == progress_before
    assert "updated_at" not in state_payload
    assert "last_event_at" not in progress_payload


def test_legacy_event_writers_fail_closed_when_v2_identity_exists(tmp_path: Path) -> None:
    run_dir = _legacy_run(tmp_path)
    _create_v2(tmp_path)

    with pytest.raises(LegacyRuntimeAuthorityError):
        append_task_event(
            run_dir,
            "LEGACY_EVENT",
            status="RUNNING",
            message="must not be appended",
        )
    with pytest.raises(LegacyRuntimeAuthorityError):
        TaskEvents("task_0001", run_dir=run_dir).record_event({"event": "legacy"})

    assert not (run_dir / "task_events.jsonl").exists()


def test_decision_create_and_resolution_cannot_mutate_shadowed_legacy_run(
    tmp_path: Path,
) -> None:
    run_dir = _legacy_run(tmp_path)
    decision_dir = run_dir / "decision_cards"
    decision_dir.mkdir()
    decision_path = decision_dir / "decision_existing.yml"
    decision_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "id": "decision_existing",
                "task_id": "task_0001",
                "status": "pending_user_approval",
                "recommended_action": "approve_resume",
                "options": [{"id": "approve_resume", "label": "Approve"}],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    existing_before = decision_path.read_bytes()
    _create_v2(tmp_path)

    with pytest.raises(LegacyRuntimeAuthorityError):
        create_decision_card(
            run_dir,
            task_id="task_0001",
            card_type="legacy_shadow",
            title="Must not exist",
            reason="v2 already owns the identity",
            options=[{"id": "ok", "label": "OK"}],
        )
    with pytest.raises(LegacyRuntimeAuthorityError):
        resolve_decision_card(
            run_dir,
            "decision_existing",
            option_id="approve_resume",
            resolution="approved",
        )

    assert decision_path.read_bytes() == existing_before
    assert sorted(path.name for path in decision_dir.glob("*.yml")) == [
        "decision_existing.yml"
    ]
    assert not (run_dir / "task_events.jsonl").exists()
    assert not (run_dir / "feedback_status.json").exists()


def test_watchdog_marks_shadowed_legacy_run_inert_and_emits_no_legacy_activity(
    tmp_path: Path,
) -> None:
    run_dir = _legacy_run(tmp_path)
    _create_v2(tmp_path)

    status = inspect_task(tmp_path, "Demo", "task_0001")
    summary = scan_project(tmp_path, "Demo")

    assert status["authority"] == "task_runtime_v2"
    assert status["shadowed_by_v2"] is True
    assert status["raw_status"] == "legacy_shadowed"
    assert status["is_stale"] is False
    assert summary["shadowed_legacy_count"] == 1
    assert summary["stale_count"] == 0
    assert not (run_dir / "task_events.jsonl").exists()
    assert not (run_dir / "decision_cards").exists()
    assert not (run_dir / "feedback_status.json").exists()
