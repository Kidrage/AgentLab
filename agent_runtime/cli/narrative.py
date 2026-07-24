"""Narrative delivery commands for longform writing projects."""

from __future__ import annotations

from pathlib import Path

import typer
import yaml
from rich.console import Console

from agent_runtime.narrative.assembly import (
    NarrativeAssemblyError,
    assemble_candidate_chapters,
)
from agent_runtime.narrative.blueprint_validation import (
    materialize_crown_blueprint,
    seal_crown_blueprint,
    validate_crown_blueprint,
)
from agent_runtime.narrative.state_store import (
    NarrativeStateError,
    NarrativeStateStore,
)
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

    @narrative_app.command("assemble")
    def assemble(
        project: str = typer.Option(..., "--project", help="Project name under projects/."),
        audit_manifest: Path = typer.Option(
            ..., "--audit-manifest", help="Passed continuous-audit manifest."
        ),
        output: Path = typer.Option(..., "--output", help="UTF-8 omnibus TXT path."),
        delivery_manifest: Path = typer.Option(
            ..., "--delivery-manifest", help="Assembly receipt YAML path."
        ),
    ) -> None:
        """Assemble only hash-bound candidate chapters approved by one audit."""
        try:
            result = assemble_candidate_chapters(
                project_root,
                project=project,
                audit_manifest=audit_manifest,
                output_path=output,
                delivery_manifest=delivery_manifest,
            )
        except NarrativeAssemblyError as exc:
            raise typer.BadParameter(str(exc)) from exc
        console.print(yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip())

    @narrative_app.command("validate-blueprint")
    def validate_blueprint(
        project: str = typer.Option("Crown_of_Ash", "--project"),
        chapter_start: int = typer.Option(1, "--chapter-start", min=1),
        chapter_end: int = typer.Option(20, "--chapter-end", min=1),
    ) -> None:
        """Validate AgentLab-authored scale decisions, canon shards, and chapter cards."""
        result = validate_crown_blueprint(
            project_root,
            project=project,
            chapter_start=chapter_start,
            chapter_end=chapter_end,
        )
        console.print(yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip())
        if result["status"] != "pass":
            raise typer.Exit(code=1)

    @narrative_app.command("seal-blueprint")
    def seal_blueprint(
        project: str = typer.Option("Crown_of_Ash", "--project"),
        source_task: str | None = typer.Option(None, "--source-task"),
        source_run_artifact: str | None = typer.Option(
            None,
            "--source-run-artifact",
        ),
        allow_registered_blueprint_drift: bool = typer.Option(
            False,
            "--allow-registered-blueprint-drift",
            help=(
                "Administrative recovery only: reseal an externally audited, "
                "authorized drift. This is not a blueprint update interface."
            ),
        ),
    ) -> None:
        """Hash and register AgentLab-authored blueprint artifacts without editing content."""
        try:
            result = seal_crown_blueprint(
                project_root,
                project=project,
                source_task=source_task,
                source_run_artifact=source_run_artifact,
                allow_registered_blueprint_drift=allow_registered_blueprint_drift,
            )
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
        console.print(yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip())

    @narrative_app.command("materialize-blueprint")
    def materialize_blueprint(
        bundle: Path = typer.Option(..., "--bundle"),
        project: str = typer.Option("Crown_of_Ash", "--project"),
    ) -> None:
        """Initialize an empty production root from a validated blueprint bundle."""
        try:
            result = materialize_crown_blueprint(
                project_root,
                bundle_path=bundle,
                project=project,
            )
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
        console.print(yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip())

    @narrative_app.command("commit-fact-authority")
    def commit_fact_authority(
        project: str = typer.Option(..., "--project", help="Project name under projects/."),
    ) -> None:
        """Commit the one artifact-index-selected fact authority revision."""
        project_dir = project_root / "projects" / project
        store = NarrativeStateStore(
            project_dir / "project_brain",
            project=project,
        )
        try:
            result = store.commit_fact_authority(
                project_dir / "production" / "fact_authority.yml"
            )
        except (OSError, ValueError, NarrativeStateError) as exc:
            raise typer.BadParameter(str(exc)) from exc
        console.print(yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip())

    app.add_typer(narrative_app, name="narrative")
