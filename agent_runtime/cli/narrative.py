"""Narrative delivery commands for longform writing projects."""

from __future__ import annotations

from pathlib import Path

import typer
import yaml
from rich.console import Console

from atomic_io import atomic_write_yaml
from agent_runtime.narrative.assembly import (
    NarrativeAssemblyError,
    assemble_candidate_chapters,
)
from agent_runtime.narrative.blueprint_validation import (
    materialize_crown_blueprint,
    seal_crown_blueprint,
    validate_crown_blueprint,
)
from agent_runtime.narrative.blueprint_lifecycle import (
    publish_blueprint_change,
    seal_project_blueprint,
    validate_project_blueprint,
)
from agent_runtime.narrative.state_store import (
    NarrativeStateError,
    NarrativeStateStore,
)
from agent_runtime.narrative.planning_window import (
    PlanningWindowError,
    activate_planning_window,
    complete_planning_window_chapter,
    propose_planning_window,
    seal_planning_window,
)
from agent_runtime.narrative.task_packet import (
    append_narrative_instruction,
    compile_narrative_task_packet,
)
from agent_runtime.narrative_delivery import (
    run_narrative_doctor,
    validate_narrative_delivery,
    write_chapter_packet,
    write_narrative_delivery_receipt,
)


def register_narrative_commands(app: typer.Typer, project_root: Path, console: Console) -> None:
    narrative_app = typer.Typer(help="Longform narrative delivery commands.", no_args_is_help=True)
    planning_window_app = typer.Typer(
        help="Governed rolling narrative planning-window lifecycle.",
        no_args_is_help=True,
    )

    def blueprint_schema(project: str) -> str:
        authority = (
            project_root
            / "projects"
            / project
            / "production"
            / "blueprint_authority.yml"
        )
        try:
            value = yaml.safe_load(authority.read_text(encoding="utf-8")) or {}
        except (OSError, UnicodeError, yaml.YAMLError):
            return ""
        return str(value.get("schema_version") or "") if isinstance(value, dict) else ""

    def crown_blueprint_range(project: str) -> tuple[int, int]:
        authority = (
            project_root
            / "projects"
            / project
            / "production"
            / "blueprint_authority.yml"
        )
        try:
            value = yaml.safe_load(authority.read_text(encoding="utf-8")) or {}
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            raise ValueError(
                "cannot resolve chapter range from production/blueprint_authority.yml"
            ) from exc
        scope = value.get("scope") if isinstance(value, dict) else None
        chapter_range = (
            scope.get("detailed_chapter_contract_range")
            if isinstance(scope, dict)
            else None
        )
        if (
            not isinstance(chapter_range, list)
            or len(chapter_range) != 2
            or any(
                isinstance(item, bool) or not isinstance(item, int) or item < 1
                for item in chapter_range
            )
            or chapter_range[0] > chapter_range[1]
        ):
            raise ValueError(
                "production/blueprint_authority.yml has no valid detailed chapter range"
            )
        return chapter_range[0], chapter_range[1]

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
        chapter_start: int | None = typer.Option(None, "--chapter-start", min=1),
        chapter_end: int | None = typer.Option(None, "--chapter-end", min=1),
    ) -> None:
        """Validate the selected Crown or project-specific narrative blueprint."""
        if blueprint_schema(project) == "narrative-blueprint-authority/v1":
            result = validate_project_blueprint(
                project_root,
                project=project,
            )
        else:
            try:
                authority_start, authority_end = crown_blueprint_range(project)
            except ValueError as exc:
                raise typer.BadParameter(str(exc)) from exc
            selected_start = (
                authority_start if chapter_start is None else chapter_start
            )
            selected_end = authority_end if chapter_end is None else chapter_end
            if selected_start > selected_end:
                raise typer.BadParameter(
                    "--chapter-start must not be greater than --chapter-end"
                )
            result = validate_crown_blueprint(
                project_root,
                project=project,
                chapter_start=selected_start,
                chapter_end=selected_end,
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
        """Validate and seal the selected Crown or project-specific blueprint."""
        try:
            if blueprint_schema(project) == "narrative-blueprint-authority/v1":
                if not source_task:
                    raise ValueError(
                        "generic project-specific sealing requires --source-task"
                    )
                if source_run_artifact or allow_registered_blueprint_drift:
                    raise ValueError(
                        "generic sealing does not accept Crown recovery options"
                    )
                result = seal_project_blueprint(
                    project_root,
                    project=project,
                    source_task=source_task,
                )
            else:
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

    @narrative_app.command("publish-blueprint-change")
    def publish_blueprint_change_command(
        project: str = typer.Option(..., "--project"),
        manifest: Path = typer.Option(
            ...,
            "--manifest",
            help="Runtime v2 artifacts/blueprint_change_set.yml.",
        ),
        acceptance_receipt: Path = typer.Option(
            ...,
            "--acceptance-receipt",
            help="Hash-bound user and expert acceptance receipt.",
        ),
    ) -> None:
        """CAS-publish one validated blueprint change and archive the previous truth."""
        try:
            result = publish_blueprint_change(
                project_root,
                project=project,
                manifest_path=manifest,
                acceptance_receipt_path=acceptance_receipt,
            )
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
        console.print(
            yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip()
        )

    def load_request(path: Path) -> dict:
        try:
            value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            raise typer.BadParameter(f"cannot read narrative request: {exc}") from exc
        if not isinstance(value, dict):
            raise typer.BadParameter("narrative request must be a mapping")
        return value

    @narrative_app.command("compile-task-packet")
    def compile_task_packet_command(
        project: str = typer.Option(..., "--project"),
        task_id: str = typer.Option(..., "--task-id"),
        request: Path = typer.Option(
            ...,
            "--request",
            help="Structured narrative request YAML.",
        ),
    ) -> None:
        """Create one append-only Runtime v2 narrative Task and expert DAG."""
        try:
            result = compile_narrative_task_packet(
                project_root,
                project=project,
                task_id=task_id,
                request=load_request(request),
            )
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
        console.print(
            yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip()
        )

    @narrative_app.command("append-task-instruction")
    def append_task_instruction_command(
        project: str = typer.Option(..., "--project"),
        task_id: str = typer.Option(..., "--task-id"),
        instruction_id: str = typer.Option(..., "--instruction-id"),
        request: Path = typer.Option(
            ...,
            "--request",
            help="Structured narrative request YAML.",
        ),
    ) -> None:
        """Append a prompt event without overwriting prior narrative instructions."""
        try:
            result = append_narrative_instruction(
                project_root,
                project=project,
                task_id=task_id,
                instruction_id=instruction_id,
                request=load_request(request),
            )
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
        console.print(
            yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip()
        )

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

    @planning_window_app.command("propose")
    def propose_planning_window_command(
        project: str = typer.Option(..., "--project"),
        output: Path = typer.Option(..., "--output"),
        locked_size: int = typer.Option(10, "--locked-size", min=8, max=10),
    ) -> None:
        """Build a candidate window from current hash-bound chapter contracts."""
        try:
            result = propose_planning_window(
                project_root,
                project=project,
                locked_size=locked_size,
            )
            atomic_write_yaml(output, result)
        except (OSError, PlanningWindowError) as exc:
            raise typer.BadParameter(str(exc)) from exc
        console.print(yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip())

    @planning_window_app.command("seal")
    def seal_planning_window_command(
        proposal: Path = typer.Option(..., "--proposal"),
        supersede_reason: str | None = typer.Option(
            None,
            "--supersede-reason",
        ),
    ) -> None:
        """Seal a proposal as the sole current planning window."""
        try:
            raw = yaml.safe_load(proposal.read_text(encoding="utf-8")) or {}
            if not isinstance(raw, dict):
                raise PlanningWindowError("proposal must be a mapping")
            result = seal_planning_window(
                project_root,
                proposal=raw,
                supersede_reason=supersede_reason,
            )
        except (OSError, UnicodeError, yaml.YAMLError, PlanningWindowError) as exc:
            raise typer.BadParameter(str(exc)) from exc
        console.print(yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip())

    @planning_window_app.command("activate")
    def activate_planning_window_command(
        project: str = typer.Option(..., "--project"),
    ) -> None:
        """Activate the sole sealed planning window."""
        try:
            result = activate_planning_window(project_root, project=project)
        except PlanningWindowError as exc:
            raise typer.BadParameter(str(exc)) from exc
        console.print(yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip())

    @planning_window_app.command("complete")
    def complete_planning_window_command(
        project: str = typer.Option(..., "--project"),
        chapter: int = typer.Option(..., "--chapter", min=1),
    ) -> None:
        """Accept the next locked chapter and roll the window forward."""
        try:
            result = complete_planning_window_chapter(
                project_root,
                project=project,
                chapter=chapter,
            )
        except PlanningWindowError as exc:
            raise typer.BadParameter(str(exc)) from exc
        console.print(yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip())

    narrative_app.add_typer(planning_window_app, name="planning-window")
    app.add_typer(narrative_app, name="narrative")
