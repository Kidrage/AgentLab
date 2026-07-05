"""Narrative delivery commands for longform writing projects."""

from __future__ import annotations

from pathlib import Path

import typer
import yaml
from rich.console import Console

from agent_runtime.narrative_delivery import (
    run_narrative_doctor,
    validate_narrative_delivery,
    write_chapter_packet,
    write_narrative_delivery_receipt,
)


def register_narrative_commands(app: typer.Typer, project_root: Path, console: Console) -> None:
    narrative_app = typer.Typer(help="Longform narrative delivery commands.", no_args_is_help=True)

    @narrative_app.command("doctor")
    def doctor(
        project: str = typer.Option(..., "--project", help="Project name under projects/."),
    ) -> None:
        """Audit narrative project readiness and recent chapter delivery receipts."""
        result = run_narrative_doctor(project_root, project)
        console.print(yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip())
        if result.get("status") != "pass":
            raise typer.Exit(code=1)

    @narrative_app.command("prepare-chapter")
    def prepare_chapter(
        project: str = typer.Option(..., "--project", help="Project name under projects/."),
        chapter: int = typer.Option(..., "--chapter", min=1, help="Chapter number."),
        task_id: str = typer.Option(..., "--task-id", help="Run id under projects/<Project>/runs/."),
    ) -> None:
        """Write a chapter packet from current production facts and prior chapters."""
        result = write_chapter_packet(project_root, project, task_id, chapter)
        console.print(yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip())

    @narrative_app.command("review")
    def review(
        project: str = typer.Option(..., "--project", help="Project name under projects/."),
        task_id: str = typer.Option(..., "--task-id", help="Run id under projects/<Project>/runs/."),
        write_receipt: bool = typer.Option(True, "--write-receipt/--no-write-receipt", help="Write narrative_delivery_receipt.yml."),
    ) -> None:
        """Validate narrative delivery outputs and block failed fiction reviews."""
        run_dir = project_root / "projects" / project / "runs" / task_id
        result = write_narrative_delivery_receipt(run_dir) if write_receipt else validate_narrative_delivery(run_dir)
        console.print(yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip())
        valid = result.get("delivery_check", result).get("valid")
        if not valid:
            raise typer.Exit(code=1)

    app.add_typer(narrative_app, name="narrative")
