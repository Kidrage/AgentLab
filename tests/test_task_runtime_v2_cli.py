from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from typer.testing import CliRunner

from agent_runtime.cli.task_runtime_v2 import register_task_runtime_commands


def test_task_runtime_cli_exposes_one_task_lifecycle_and_project_doctor(
    tmp_path: Path,
) -> None:
    app = typer.Typer()
    register_task_runtime_commands(app, tmp_path, Console(width=120))
    runner = CliRunner()

    created = runner.invoke(
        app,
        [
            "task",
            "create",
            "--project",
            "Demo",
            "--task-id",
            "task-one",
            "--title",
            "One business goal",
            "--goal",
            "Keep all work under one Task.",
            "--idempotency-key",
            "request-one",
        ],
    )
    paused = runner.invoke(
        app,
        [
            "task",
            "pause",
            "--project",
            "Demo",
            "--task-id",
            "task-one",
            "--idempotency-key",
            "pause-one",
        ],
    )
    resumed = runner.invoke(
        app,
        [
            "task",
            "resume",
            "--project",
            "Demo",
            "--task-id",
            "task-one",
            "--idempotency-key",
            "resume-one",
        ],
    )
    paused_again = runner.invoke(
        app,
        [
            "task",
            "pause",
            "--project",
            "Demo",
            "--task-id",
            "task-one",
            "--idempotency-key",
            "pause-two",
        ],
    )
    doctor = runner.invoke(app, ["runtime-v2", "doctor", "--project", "Demo"])

    assert created.exit_code == 0, created.output
    assert paused.exit_code == 0, paused.output
    assert "status: paused" in paused.output
    assert resumed.exit_code == 0, resumed.output
    assert "status: running" in resumed.output
    assert paused_again.exit_code == 0, paused_again.output
    assert "status: paused" in paused_again.output
    assert doctor.exit_code == 0, doctor.output
    assert "ok: true" in doctor.output.lower()
