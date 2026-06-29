"""Routing and role-assignment CLI commands."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import typer
import yaml
from rich.console import Console


ProjectRootProvider = Path | Callable[[], Path]


def register_routing_commands(app: typer.Typer, project_root: ProjectRootProvider, console: Console) -> None:
    """Register routing inspection and role-assignment commands."""

    def current_project_root() -> Path:
        return project_root() if callable(project_root) else project_root

    @app.command("assign-role")
    def assign_role_cmd(
        role: str = typer.Option(..., "--role", help="AgentLab role to assign."),
        project: str = typer.Option("AgentLab", "--project"),
        phase: str = typer.Option("unknown", "--phase"),
        task_id: str = typer.Option("ad_hoc_route", "--task-id"),
        mode: str = typer.Option("hybrid_local_company", "--mode"),
        tier: str = typer.Option("performance", "--tier"),
        available_worker: list[str] | None = typer.Option(None, "--available-worker"),
        approved_worker: list[str] | None = typer.Option(None, "--approved-worker"),
    ) -> None:
        """Assign one role using capability, availability, cost, risk, and performance policy."""
        from agent_runtime.routing.role_assignment import RoleAssignmentEngine

        root = current_project_root()
        engine = RoleAssignmentEngine(root)
        decision = engine.assign(
            role,
            project_id=project,
            phase_id=phase,
            task_id=task_id,
            mode=mode,
            tier=tier,
            available_workers=available_worker,
            approved_workers=approved_worker,
        )
        from agent_runtime.observability.api import emit_event

        emit_event(
            project_id=project,
            project_dir=root,
            event_type="role_assigned",
            details={
                "decision_path": getattr(decision, "decision_path", ""),
                "rejected_alternatives": getattr(decision, "rejected_alternatives", []),
            },
            worker_id=getattr(decision, "selected_worker", ""),
            role_id=role,
            task_id=task_id,
        )
        console.print(yaml.safe_dump(decision.to_dict(), sort_keys=False, allow_unicode=True))

    @app.command("route-task")
    def route_task_cmd(
        task_packet: Path = typer.Option(..., "--task-packet", help="Task packet YAML to route."),
    ) -> None:
        """Route roles in a task packet and persist route decisions as task evidence."""
        from agent_runtime.routing.worker_router import route_task_packet

        root = current_project_root()
        try:
            result = route_task_packet(task_packet, root)
            from agent_runtime.observability.api import emit_event

            plan = result.get("route_plan", {})
            for d in plan.get("decisions", []):
                r = d.get("role", "unknown")
                emit_event(
                    project_id=plan.get("project_id", "AgentLab"),
                    project_dir=root,
                    event_type="route_decision_created",
                    details={
                        "route_profile": d.get("route_profile"),
                        "rejected_alternatives": d.get("rejected_alternatives"),
                    },
                    worker_id=d.get("selected_worker"),
                    role_id=r,
                    task_id=plan.get("task_id", "unknown_task"),
                )
        except (FileNotFoundError, ValueError, yaml.YAMLError) as exc:
            console.print(f"[red]Error: {exc}[/red]")
            raise typer.Exit(code=1)
        console.print(yaml.safe_dump(result, sort_keys=False, allow_unicode=True))

    @app.command("route-explain")
    def route_explain_cmd(
        decision: Path = typer.Option(..., "--decision", help="Saved route decision YAML."),
    ) -> None:
        """Explain why a worker was selected and why alternatives were rejected."""
        from agent_runtime.routing.renderer import render_route_explanation
        from agent_runtime.routing.route_decision import RouteDecision

        if not decision.exists():
            console.print(f"[red]Error: decision file not found: {decision}[/red]")
            raise typer.Exit(code=1)
        try:
            payload = yaml.safe_load(decision.read_text(encoding="utf-8")) or {}
            route_decision = RouteDecision.from_dict(payload)
        except (TypeError, ValueError, yaml.YAMLError) as exc:
            console.print(f"[red]Error: invalid route decision: {exc}[/red]")
            raise typer.Exit(code=1)
        console.print(render_route_explanation(route_decision))
