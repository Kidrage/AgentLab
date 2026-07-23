from __future__ import annotations

import hashlib
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


def test_trace_cli_records_immutable_memory_receipt(tmp_path: Path) -> None:
    app = typer.Typer()
    register_task_runtime_commands(app, tmp_path, Console(width=120))
    runner = CliRunner()
    profile = (
        '{"kind":"exact_patch","scope":"single_detail","target_count":1,'
        '"canon_impact":"candidate","risk_flags":[]}'
    )
    created = runner.invoke(
        app,
        [
            "task",
            "create",
            "--project",
            "Demo",
            "--task-id",
            "task-trace",
            "--title",
            "Trace one patch",
            "--goal",
            "Keep one detail update traceable.",
            "--input-profile-json",
            profile,
            "--idempotency-key",
            "create-trace",
        ],
    )
    source = (
        tmp_path
        / "projects"
        / "Demo"
        / "runtime"
        / "tasks"
        / "task-trace"
        / "records"
        / "staging"
        / "memory.yml"
    )
    source.parent.mkdir(parents=True)
    memory_file = tmp_path / "projects" / "Demo" / "candidate" / "detail.yml"
    memory_file.parent.mkdir(parents=True, exist_ok=True)
    memory_file.write_text("detail: retained\n", encoding="utf-8")
    memory_path = memory_file.relative_to(tmp_path).as_posix()
    memory_hash = hashlib.sha256(memory_file.read_bytes()).hexdigest()
    source.write_text(
        "schema_version: memory-update-receipt/v1\n"
        "status: pass\n"
        f"updated_paths: [{memory_path}]\n"
        f"content_hashes: {{{memory_path}: {memory_hash}}}\n",
        encoding="utf-8",
    )

    recorded = runner.invoke(
        app,
        [
            "trace",
            "record",
            "--project",
            "Demo",
            "--task-id",
            "task-trace",
            "--record-id",
            "memory-one",
            "--record-type",
            "memory_update",
            "--producer",
            "brain",
            "--producer-role",
            "Supervisor",
            "--path",
            str(source),
            "--idempotency-key",
            "memory-one",
        ],
    )

    assert created.exit_code == 0, created.output
    assert recorded.exit_code == 0, recorded.output
    assert "record_type: memory_update" in recorded.output
    assert "records/immutable/memory-one/" in recorded.output
