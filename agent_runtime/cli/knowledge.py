"""Governed knowledge-system operator commands."""

from __future__ import annotations

import os
from pathlib import Path

import typer
import yaml
from rich.console import Console

from agent_runtime.knowledge_system import (
    KnowledgeTaskRequest,
    activate_knowledge_mode,
    build_knowledge_base,
    knowledge_status,
    prepare_task,
    validate_knowledge_stage,
)
from agent_runtime.policies import resolve_agentlab_root


def register_knowledge_commands(app: typer.Typer, project_root: Path, console: Console) -> None:
    knowledge = typer.Typer(
        help="Build, inspect, validate, and activate governed AgentLab knowledge spaces.",
        no_args_is_help=True,
    )

    @knowledge.command("build")
    def build(
        project: list[str] | None = typer.Option(None, "--project", help="Project to index; repeatable."),
        all_projects: bool = typer.Option(False, "--all-projects", help="Discover and index every project."),
        domain: list[str] | None = typer.Option(
            None,
            "--domain",
            help="Optional PROJECT=DOMAIN override; repeatable.",
        ),
    ) -> None:
        """Build local system, project, and domain shards inside AgentLab."""
        try:
            overrides = _domain_overrides(domain or [])
            result = build_knowledge_base(
                _root(project_root),
                projects=project or (),
                include_all_projects=all_projects,
                project_domains=overrides,
            )
        except ValueError as exc:
            _fail(console, exc)
        console.print(yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip())

    @knowledge.command("status")
    def status() -> None:
        """Show configured rollout mode and shard health/counts."""
        result = knowledge_status(_root(project_root))
        console.print(yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip())

    @knowledge.command("activate")
    def activate(
        mode: str = typer.Option(..., "--mode", help="Next rollout mode: off, shadow, assist, enforce."),
        actor: str = typer.Option(..., "--actor", help="Auditable operator identity."),
        reason: str = typer.Option(..., "--reason", help="Auditable activation reason."),
    ) -> None:
        """Advance one validated stage or roll back to a safer mode."""
        try:
            result = activate_knowledge_mode(
                _root(project_root),
                mode,
                actor=actor,
                reason=reason,
            )
        except ValueError as exc:
            _fail(console, exc)
        console.print(yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip())

    @knowledge.command("validate")
    def validate(
        project: str = typer.Option(..., "--project", help="Project knowledge space."),
        task_id: str = typer.Option(..., "--task-id", help="Validation task id."),
        request: str = typer.Option(..., "--request", help="Representative retrieval request."),
        domain: str = typer.Option(..., "--domain", help="Representative task domain."),
    ) -> None:
        """Validate the active stage against representative governed evidence."""
        try:
            result = validate_knowledge_stage(
                _root(project_root),
                project=project,
                task_id=task_id,
                request_text=request,
                domain=domain,
            )
        except ValueError as exc:
            _fail(console, exc)
        console.print(yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip())
        if result["status"] != "PASS":
            raise typer.Exit(code=1)

    @knowledge.command("search")
    def search(
        project: str = typer.Option(..., "--project", help="Project knowledge space."),
        task_id: str = typer.Option(..., "--task-id", help="Auditable task id."),
        query: str = typer.Option(..., "--query", help="Knowledge request."),
        domain: str = typer.Option(..., "--domain", help="Task domain."),
    ) -> None:
        """Build an auditable task retrieval view using the active rollout mode."""
        try:
            result = prepare_task(
                KnowledgeTaskRequest(
                    agentlab_root=_root(project_root),
                    project=project,
                    task_id=task_id,
                    request_text=query,
                    domain=domain,
                )
            ).as_dict()
        except ValueError as exc:
            _fail(console, exc)
        console.print(yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip())
        if result["status"] != "READY":
            raise typer.Exit(code=1)

    @knowledge.command("doctor")
    def doctor() -> None:
        """Fail unless the knowledge system is active, local, built, and evidence-bearing."""
        root = _root(project_root)
        result = knowledge_status(root)
        checks = {
            "storage_inside_agentlab": result["storage_inside_agentlab"],
            "knowledge_spaces_built": result["space_count"] > 0,
            "knowledge_spaces_fresh": all(
                space["status"] == "active" for space in result["spaces"]
            ),
            "eligible_evidence_present": result["eligible_record_count"] > 0,
            "active_for_tasks": result["mode"] in {"shadow", "assist", "enforce"},
            "build_receipt_present": (
                root / result["runtime_path"] / "receipts" / "latest_build.json"
            ).is_file(),
        }
        report = {
            "status": "PASS" if all(checks.values()) else "FAIL",
            "mode": result["mode"],
            "checks": checks,
            "space_count": result["space_count"],
            "record_count": result["record_count"],
            "eligible_record_count": result["eligible_record_count"],
        }
        console.print(yaml.safe_dump(report, sort_keys=False, allow_unicode=True).rstrip())
        if report["status"] != "PASS":
            raise typer.Exit(code=1)

    app.add_typer(knowledge, name="knowledge")


def _root(project_root: Path) -> Path:
    configured = Path(os.environ.get("AGENTLAB_ROOT") or project_root)
    return resolve_agentlab_root(configured)


def _domain_overrides(values: list[str]) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for value in values:
        project, separator, domain = value.partition("=")
        if not separator or not project.strip() or not domain.strip():
            raise ValueError(f"invalid --domain override {value!r}; expected PROJECT=DOMAIN")
        overrides[project.strip()] = domain.strip()
    return overrides


def _fail(console: Console, exc: Exception) -> None:
    console.print(f"[red]Error:[/red] {exc}")
    raise typer.Exit(code=1)
