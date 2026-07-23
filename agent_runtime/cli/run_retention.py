"""CLI for deterministic, archive-only project run retention."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
import typer
import yaml

from agent_runtime.run_retention import archive_runs_from_plan, build_run_retention_plan


def register_run_retention_commands(
    app: typer.Typer,
    agentlab_root: Path,
    console: Console,
) -> None:
    retention = typer.Typer(
        help="Plan or apply archive-only retention for inactive project runs.",
        no_args_is_help=True,
    )

    @retention.command("plan")
    def plan(
        project: str = typer.Option(..., "--project"),
        allow_protected_status: bool = typer.Option(
            False,
            "--allow-protected-status",
            help="Include matched running/paused/recoverable runs in the plan.",
        ),
    ) -> None:
        report = build_run_retention_plan(
            agentlab_root,
            project,
            allow_protected_status=allow_protected_status,
        )
        console.print(yaml.safe_dump(report, sort_keys=False, allow_unicode=True).rstrip())

    @retention.command("archive")
    def archive(
        project: str = typer.Option(..., "--project"),
        execute: bool = typer.Option(False, "--execute/--dry-run"),
        allow_protected_status: bool = typer.Option(False, "--allow-protected-status"),
        batch_id: str | None = typer.Option(None, "--batch-id"),
        rebuild_task_index: bool = typer.Option(True, "--rebuild-task-index/--no-rebuild-task-index"),
    ) -> None:
        report = build_run_retention_plan(
            agentlab_root,
            project,
            allow_protected_status=allow_protected_status,
        )
        if not execute:
            console.print(yaml.safe_dump(report, sort_keys=False, allow_unicode=True).rstrip())
            return
        manifest = archive_runs_from_plan(
            agentlab_root,
            report,
            batch_id=batch_id,
        )
        if rebuild_task_index and manifest["entry_count"]:
            from agent_runtime.task_index import rebuild_index

            index = rebuild_index(agentlab_root, project)
            manifest["task_index_task_count"] = index["task_count"]
        console.print(yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True).rstrip())

    app.add_typer(retention, name="run-retention")
