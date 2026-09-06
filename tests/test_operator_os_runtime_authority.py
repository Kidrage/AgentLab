from __future__ import annotations

from pathlib import Path

import yaml

from agent_runtime.operator_os.action_runtime import execute_operator_action
from agent_runtime.task_runtime_v2.runtime import TaskRuntime


def _task_request(action: str, task_id: str = "task-one") -> dict[str, object]:
    return {
        "action": action,
        "target_type": "task",
        "target_id": task_id,
        "project": "Demo",
        "actor": "operator-test",
        "reason": f"test {action}",
        "requested_effects": [],
        "source_surface": "pytest",
    }


def _write_legacy_run(root: Path, task_id: str = "task-one") -> Path:
    run_dir = root / "projects" / "Demo" / "runs" / task_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "state.yml").write_text("status: running\nmarker: legacy\n", encoding="utf-8")
    (run_dir / "progress.yml").write_text("status: running\nmarker: legacy\n", encoding="utf-8")
    return run_dir


def test_operator_task_action_prefers_v2_and_does_not_touch_legacy_run(tmp_path: Path) -> None:
    runtime = TaskRuntime(tmp_path, project="Demo")
    runtime.create_task(
        task_id="task-one",
        title="One goal",
        user_goal="Keep one canonical task authority.",
        idempotency_key="create-one",
    )
    legacy_run = _write_legacy_run(tmp_path)

    result = execute_operator_action(tmp_path, _task_request("pause"))

    assert result["success"] is True
    assert result["runtime_result"]["authority"] == "task_runtime_v2"
    assert runtime.rebuild_task("task-one")["task"]["status"] == "paused"
    legacy_state = yaml.safe_load((legacy_run / "state.yml").read_text(encoding="utf-8"))
    legacy_progress = yaml.safe_load((legacy_run / "progress.yml").read_text(encoding="utf-8"))
    assert legacy_state == {"status": "running", "marker": "legacy"}
    assert legacy_progress == {"status": "running", "marker": "legacy"}


def test_operator_task_action_fails_closed_when_v2_identity_is_corrupt(tmp_path: Path) -> None:
    task_dir = tmp_path / "projects" / "Demo" / "runtime" / "tasks" / "task-one"
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "events.jsonl").write_text("not-json\n", encoding="utf-8")
    legacy_run = _write_legacy_run(tmp_path)

    result = execute_operator_action(tmp_path, _task_request("pause"))

    assert result["success"] is False
    assert result["runtime_status"] == "task_runtime_v2_unavailable"
    assert result["runtime_result"]["authority"] == "task_runtime_v2"
    legacy_state = yaml.safe_load((legacy_run / "state.yml").read_text(encoding="utf-8"))
    assert legacy_state == {"status": "running", "marker": "legacy"}


def test_operator_task_action_keeps_legacy_compat_for_legacy_only_task(tmp_path: Path) -> None:
    legacy_run = _write_legacy_run(tmp_path)

    result = execute_operator_action(tmp_path, _task_request("pause"))

    assert result["success"] is True
    assert result["runtime_result"]["authority"] == "legacy_runs_compat"
    legacy_state = yaml.safe_load((legacy_run / "state.yml").read_text(encoding="utf-8"))
    assert legacy_state["status"] == "paused"
    assert legacy_state["last_operator_action"] == "pause"
