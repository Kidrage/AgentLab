"""CLI surface for durable AgentLab background jobs."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
import typer
import yaml

from agent_runtime.background_job_controller import (
    controller_cycle,
    create_crown_delivery_job,
    launch_controller_service,
    load_job_state,
    pause_job,
    retry_blocked_job,
    resume_job,
    run_controller_loop,
)


def register_background_job_commands(
    app: typer.Typer,
    agentlab_root: Path,
    console: Console,
) -> None:
    jobs = typer.Typer(
        help="Durable receipt-driven background job controller.",
        no_args_is_help=True,
    )

    @jobs.command("create-crown")
    def create_crown(
        job_id: str = typer.Option(..., "--job-id"),
        eval_id: str = typer.Option(..., "--eval-id"),
        start_chapter: int = typer.Option(..., "--start-chapter", min=1),
        end_chapter: int = typer.Option(..., "--end-chapter", min=1),
        writer_worker: str = typer.Option(..., "--writer-worker"),
        chapter_state_plan: str = typer.Option(..., "--chapter-state-plan"),
        project: str = typer.Option("Crown_of_Ash", "--project"),
        batch_size: int = typer.Option(10, "--batch-size", min=1),
        heavy_audit_cadence: int = typer.Option(10, "--heavy-audit-cadence", min=1),
        writer_budget: str = typer.Option("frugal", "--writer-budget"),
    ) -> None:
        state = create_crown_delivery_job(
            agentlab_root,
            project=project,
            job_id=job_id,
            eval_id=eval_id,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
            batch_size=batch_size,
            heavy_audit_cadence=heavy_audit_cadence,
            writer_worker=writer_worker,
            chapter_state_plan=chapter_state_plan,
            writer_budget=writer_budget,
        )
        console.print(yaml.safe_dump(state, sort_keys=False, allow_unicode=True).rstrip())

    @jobs.command("status")
    def status(
        job_id: str = typer.Option(..., "--job-id"),
        project: str = typer.Option("Crown_of_Ash", "--project"),
    ) -> None:
        state = load_job_state(agentlab_root, project, job_id)
        console.print(yaml.safe_dump(state, sort_keys=False, allow_unicode=True).rstrip())

    @jobs.command("tick")
    def tick(
        job_id: str = typer.Option(..., "--job-id"),
        project: str = typer.Option("Crown_of_Ash", "--project"),
        execute: bool = typer.Option(
            False,
            "--execute/--no-execute",
            help="Launch the scheduled worker. Default only advances local receipts.",
        ),
    ) -> None:
        result = controller_cycle(
            agentlab_root,
            project=project,
            job_id=job_id,
            execute=execute,
        )
        console.print(yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip())

    @jobs.command("pause")
    def pause(
        job_id: str = typer.Option(..., "--job-id"),
        project: str = typer.Option("Crown_of_Ash", "--project"),
    ) -> None:
        state = pause_job(agentlab_root, project=project, job_id=job_id)
        console.print(yaml.safe_dump(state, sort_keys=False, allow_unicode=True).rstrip())

    @jobs.command("resume")
    def resume(
        job_id: str = typer.Option(..., "--job-id"),
        project: str = typer.Option("Crown_of_Ash", "--project"),
    ) -> None:
        state = resume_job(agentlab_root, project=project, job_id=job_id)
        console.print(yaml.safe_dump(state, sort_keys=False, allow_unicode=True).rstrip())

    @jobs.command("retry-blocked")
    def retry_blocked(
        job_id: str = typer.Option(..., "--job-id"),
        repair_reason: str = typer.Option(..., "--repair-reason"),
        project: str = typer.Option("Crown_of_Ash", "--project"),
    ) -> None:
        state = retry_blocked_job(
            agentlab_root,
            project=project,
            job_id=job_id,
            repair_reason=repair_reason,
        )
        console.print(yaml.safe_dump(state, sort_keys=False, allow_unicode=True).rstrip())

    @jobs.command("run")
    def run(
        job_id: str = typer.Option(..., "--job-id"),
        project: str = typer.Option("Crown_of_Ash", "--project"),
        execute: bool = typer.Option(
            False,
            "--execute/--no-execute",
            help="Required before any provider-backed worker can launch.",
        ),
        detach: bool = typer.Option(True, "--detach/--foreground"),
        poll_seconds: float = typer.Option(5.0, "--poll-seconds", min=0.05),
    ) -> None:
        if not execute:
            raise typer.BadParameter("background execution requires explicit --execute")
        result = (
            launch_controller_service(
                agentlab_root,
                project=project,
                job_id=job_id,
                poll_seconds=poll_seconds,
            )
            if detach
            else run_controller_loop(
                agentlab_root,
                project=project,
                job_id=job_id,
                poll_seconds=poll_seconds,
            )
        )
        console.print(yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip())

    app.add_typer(jobs, name="background-job")
