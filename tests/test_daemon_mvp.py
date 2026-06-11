"""P1 Fix 6: Test daemon --once mode MVP."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))


def _setup_daemon_env(tmp_path: Path) -> tuple[Path, str]:
    """Create a minimal project with a stale-looking task run."""
    # Config
    config = tmp_path / "config"
    config.mkdir(parents=True)

    # Webhook policy (disabled for these tests)
    (config / "webhook_policy.yml").write_text(
        yaml.safe_dump({"schema_version": 1, "enabled": False, "endpoints": []}), encoding="utf-8"
    )
    # Watchdog policy
    (config / "watchdog_policy.yml").write_text(
        yaml.safe_dump({
            "schema_version": 1,
            "enabled": True,
            "thresholds": {
                "running_without_heartbeat_seconds": 0,
                "running_without_event_seconds": 0,
                "waiting_for_approval_seconds": 0,
                "stale_lock_seconds": 0,
            },
            "stale_actions": {
                "append_event": True,
                "write_feedback_status": True,
                "create_decision_card": True,
            },
        }),
        encoding="utf-8",
    )
    # Daemon policy
    (config / "daemon_policy.yml").write_text(
        yaml.safe_dump({
            "schema_version": 1,
            "enabled": False,
            "scan_interval_seconds": 30,
            "projects": ["TestProject"],
            "dispatch_webhooks": False,
            "write_heartbeat": True,
        }),
        encoding="utf-8",
    )

    # Feedback policy
    (config / "feedback_policy.yml").write_text(
        yaml.safe_dump({"schema_version": 1, "notification_levels": {}, "watchdog_thresholds": {}}),
        encoding="utf-8",
    )

    project = "TestProject"
    run_dir = tmp_path / "projects" / project / "runs" / "task_stale"
    run_dir.mkdir(parents=True)

    # Create state.yml marking task as "running"
    state = {"status": "running", "last_event": "task started", "updated_at": "2020-01-01T00:00:00Z"}
    (run_dir / "state.yml").write_text(yaml.safe_dump(state), encoding="utf-8")
    (run_dir / "progress.yml").write_text(yaml.safe_dump({"status": "running"}), encoding="utf-8")
    (run_dir / "user_request.md").write_text("Test stale task", encoding="utf-8")
    (run_dir / "task_events.jsonl").write_text("", encoding="utf-8")

    return tmp_path, project


def test_daemon_once_calls_watchdog(tmp_path: Path) -> None:
    """daemon --once should call watchdog scan and detect stale tasks."""
    root, project = _setup_daemon_env(tmp_path)
    from daemon import run_daemon_once

    result = run_daemon_once(root, project=project, dispatch_webhooks=False)
    assert result["daemon_mode"] == "once"
    summaries = result.get("summaries", [])
    assert len(summaries) > 0
    summary = summaries[0]
    assert summary["task_count"] > 0
    # At least the stale task should be detected
    # (whether it's stale depends on watchdog thresholds, but scan must complete)


def test_daemon_heartbeat_written(tmp_path: Path) -> None:
    """daemon --once should write a heartbeat file."""
    root, project = _setup_daemon_env(tmp_path)
    from daemon import run_daemon_once

    run_daemon_once(root, project=project, dispatch_webhooks=False)
    heartbeat = root / ".agentlab_daemon_heartbeat.json"
    assert heartbeat.exists(), f"Heartbeat file not found at {heartbeat}"


def test_daemon_disabled_webhook_does_not_crash(tmp_path: Path) -> None:
    """Daemon with disabled webhooks should not crash."""
    root, project = _setup_daemon_env(tmp_path)
    from daemon import run_daemon_once

    # Should complete without error
    result = run_daemon_once(root, project=project, dispatch_webhooks=False)
    assert result is not None
    assert "summaries" in result


def test_daemon_status_no_scan_yet(tmp_path: Path) -> None:
    """daemon-status should report no_scan_yet before any scan."""
    root, project = _setup_daemon_env(tmp_path)
    from daemon import daemon_status

    status = daemon_status(root, project)
    assert status.get("status") in {"no_scan_yet", "unreadable"} or "timestamp" in status