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


def test_task_cli_previews_and_records_strict_input_tier(tmp_path: Path) -> None:
    app = typer.Typer()
    register_task_runtime_commands(app, tmp_path, Console(width=120))
    runner = CliRunner()
    profile = (
        '{"kind":"prose_build","scope":"multi_chapter","target_count":0,'
        '"canon_impact":"canonical","risk_flags":["longform_continuity"]}'
    )

    preview = runner.invoke(
        app,
        ["task", "classify", "--input-profile-json", profile],
    )
    created = runner.invoke(
        app,
        [
            "task",
            "create",
            "--project",
            "Demo",
            "--task-id",
            "task-prose",
            "--title",
            "First governed prose build",
            "--goal",
            "Let the Brain choose and govern the first prose build.",
            "--input-profile-json",
            profile,
            "--idempotency-key",
            "request-prose",
        ],
    )

    assert preview.exit_code == 0, preview.output
    assert "tier: L3" in preview.output
    assert "route: governed_pipeline" in preview.output
    assert created.exit_code == 0, created.output
    assert "input_classification:" in created.output
    assert "brain_decision_required: true" in created.output.lower()
