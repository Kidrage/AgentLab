from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from feedback_manager import (
    assess_task_feedback_state,
    create_decision_card,
    load_pending_decision_cards,
)
from task_events import append_task_event, load_task_events


def test_task_event_jsonl_round_trip(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    event = append_task_event(
        run_dir,
        "TASK_CREATED",
        stage="queued",
        status="QUEUED",
        severity="INFO",
        message="Task accepted.",
    )

    events = load_task_events(run_dir)
    assert len(events) == 1
    assert events[0]["event"] == "TASK_CREATED"
    assert events[0]["message"] == "Task accepted."
    assert event["status"] == "QUEUED"


def test_decision_card_marks_task_action_required(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    create_decision_card(
        run_dir,
        task_id="task_001",
        card_type="write_permission",
        title="Write approval required",
        reason="Need to edit pyproject.toml.",
        stage="implementation",
        options=[
            {"id": "approve_write", "label": "Approve write", "risk": "medium"},
            {"id": "dry_run", "label": "Dry run only", "risk": "low"},
        ],
    )

    cards = load_pending_decision_cards(run_dir)
    assert len(cards) == 1
    assessment = assess_task_feedback_state(run_dir)
    assert assessment["feedback_status"] == "WAITING_FOR_APPROVAL"
    assert assessment["notification_level"] == "ACTION_REQUIRED"
    assert assessment["pending_decision_count"] == 1
    assert load_task_events(run_dir)[0]["event"] == "APPROVAL_REQUIRED"


def test_watchdog_detects_stale_running_progress(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    old = datetime.now(timezone.utc) - timedelta(seconds=1200)
    (run_dir / "progress.yml").write_text(
        yaml.safe_dump({
            "status": "running",
            "last_event": "TesterAuditor running tests.",
            "last_event_at": old.isoformat(),
        }),
        encoding="utf-8",
    )

    assessment = assess_task_feedback_state(run_dir, stale_after_seconds=600)
    assert assessment["feedback_status"] == "STALE_RUNNING"
    assert assessment["notification_level"] == "BLOCKED"
    assert assessment["last_event_age_seconds"] >= 600
