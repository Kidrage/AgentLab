from __future__ import annotations

from pathlib import Path

from agent_runtime.task_runtime_v2.runtime import TaskRuntime
from web_ui import server


def _redirect_web_ui_root(monkeypatch, root: Path) -> None:
    monkeypatch.setattr(server, "AGENTLAB_ROOT", root)
    monkeypatch.setattr(server._legacy, "AGENTLAB_ROOT", root)


def test_web_ui_task_create_lists_and_controls_runtime_v2(tmp_path: Path, monkeypatch) -> None:
    _redirect_web_ui_root(monkeypatch, tmp_path)

    created = server.handle_create_task(
        {
            "project": "Demo",
            "taskId": "task_0001",
            "requestText": "Build a reliable candidate.",
        }
    )

    assert created["success"] is True
    assert created["authority"] == "task_runtime_v2"
    assert not (tmp_path / "projects" / "Demo" / "runs" / "task_0001").exists()

    runtime = TaskRuntime(tmp_path, project="Demo")
    assert runtime.rebuild_task("task_0001")["task"]["status"] == "ready"

    listing = server.handle_get_tasks("Demo")
    assert listing["tasks"] == [
        {
            "task_id": "task_0001",
            "title": "Build a reliable candidate.",
            "description": "Build a reliable candidate.",
            "status": "ready",
            "priority": "",
            "category": "",
            "depends_on": [],
            "subtasks": [],
            "authority": "task_runtime_v2",
        }
    ]

    paused = server.handle_task_control("Demo", "task_0001", "pause", {"reason": "operator check"})
    assert paused["success"] is True
    assert paused["authority"] == "task_runtime_v2"
    assert runtime.rebuild_task("task_0001")["task"]["status"] == "paused"

    resumed = server.handle_task_control("Demo", "task_0001", "resume", {"reason": "continue"})
    assert resumed["success"] is True
    assert runtime.rebuild_task("task_0001")["task"]["status"] == "ready"

    stopped = server.handle_task_control("Demo", "task_0001", "stop", {"reason": "cancel test"})
    assert stopped["success"] is True
    assert runtime.rebuild_task("task_0001")["task"]["status"] == "cancelled"


def test_web_ui_v2_task_shadows_same_named_legacy_run(tmp_path: Path, monkeypatch) -> None:
    _redirect_web_ui_root(monkeypatch, tmp_path)
    server.handle_create_task(
        {
            "project": "Demo",
            "taskId": "task_0001",
            "requestText": "Canonical v2 task",
        }
    )

    legacy_run = tmp_path / "projects" / "Demo" / "runs" / "task_0001"
    legacy_run.mkdir(parents=True)
    (legacy_run / "state.yml").write_text("status: running\n", encoding="utf-8")
    (legacy_run / "progress.yml").write_text("status: running\n", encoding="utf-8")

    listing = server.handle_get_tasks("Demo")
    assert len(listing["tasks"]) == 1
    assert listing["tasks"][0]["authority"] == "task_runtime_v2"
    assert listing["tasks"][0]["description"] == "Canonical v2 task"

    server.handle_task_control("Demo", "task_0001", "pause", {"reason": "v2 wins"})
    assert (legacy_run / "state.yml").read_text(encoding="utf-8") == "status: running\n"
