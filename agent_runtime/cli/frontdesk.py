"""Frontend-independent Frontdesk routing commands."""

from __future__ import annotations

from pathlib import Path

import typer
import yaml
from rich.console import Console

from agent_runtime.frontdesk_intent import (
    compile_frontdesk_intent,
    load_frontdesk_intent_policy,
)
from agent_runtime.frontdesk_service import serve_frontdesk
from agent_runtime.frontdesk_evidence import (
    build_grounded_task_report,
    search_tracked_evidence,
)


def register_frontdesk_commands(
    app: typer.Typer,
    agentlab_root: Path,
    console: Console,
) -> None:
    frontdesk_app = typer.Typer(
        help="Compile transport-independent intents and safe route tiers.",
        no_args_is_help=True,
    )

    @frontdesk_app.command("route")
    def route(
        request: str = typer.Option(..., "--request"),
        project: str | None = typer.Option(None, "--project"),
        adapter: str | None = typer.Option(None, "--adapter"),
        project_contract_exists: bool = typer.Option(
            False,
            "--project-contract-exists",
        ),
        explain: bool = typer.Option(False, "--explain"),
    ) -> None:
        """Compile frontdesk-intent/v2 without mutating project files."""
        try:
            result = compile_frontdesk_intent(
                request,
                project=project,
                adapter=adapter,
                project_contract_exists=project_contract_exists,
                policy=load_frontdesk_intent_policy(agentlab_root),
            )
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
        if explain:
            console.print(
                yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip()
            )
        else:
            console.print(result["route_tier"])

    @frontdesk_app.command("serve")
    def serve(
        adapter: str = typer.Option(..., "--adapter"),
        socket_path: Path = typer.Option(..., "--socket"),
        state: Path = typer.Option(..., "--state"),
    ) -> None:
        """Serve Frontdesk intents over one private local Unix socket."""
        if adapter not in {"openclaw", "hermes", "qwen", "generic"}:
            raise typer.BadParameter("unsupported Frontdesk adapter")
        try:
            serve_frontdesk(
                socket_path=socket_path,
                state_path=state,
                agentlab_root=agentlab_root,
                adapter=adapter,
                version="frontdesk-intent/v2",
            )
        except (OSError, ValueError) as exc:
            raise typer.BadParameter(str(exc)) from exc

    @frontdesk_app.command("search")
    def search(
        query: str = typer.Option(..., "--query"),
        paths: list[str] | None = typer.Option(None, "--path"),
        limit: int = typer.Option(20, "--limit", min=1, max=100),
    ) -> None:
        """Search literal text in tracked files and emit line/hash evidence."""
        try:
            result = search_tracked_evidence(
                agentlab_root,
                query,
                paths=paths or (),
                max_results=limit,
            )
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
        console.print(
            yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip()
        )

    @frontdesk_app.command("report")
    def report(
        project: str = typer.Option(..., "--project"),
        task_id: str = typer.Option(..., "--task-id"),
    ) -> None:
        """Compile a conservative task report from canonical evidence files."""
        try:
            result = build_grounded_task_report(agentlab_root, project, task_id)
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc
        console.print(
            yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip()
        )

    app.add_typer(frontdesk_app, name="frontdesk")
