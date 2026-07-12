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

    def production_pack_for_route(root: Path, route_key: str) -> str | None:
        packs_path = root / "config" / "production_packs.yml"
        if not packs_path.exists():
            return None
        data = yaml.safe_load(packs_path.read_text(encoding="utf-8")) or {}
        for pack in data.get("packs", []) or []:
            if route_key in (pack.get("routes") or []):
                return str(pack.get("pack_id") or "")
        return None

    @app.command("route-probe")
    def route_probe_cmd(
        task_text: list[str] = typer.Argument(..., help="Natural-language task text to classify."),
        project: str = typer.Option("AgentLab", "--project", help="Project id used for mission-contract probing."),
        task_id: str = typer.Option("task_route_probe", "--task-id", help="Synthetic task id used for mission-contract probing."),
    ) -> None:
        """Probe task-domain routing from natural language without writing task evidence."""
        from task_router import recommend_route

        root = current_project_root()
        text = " ".join(task_text).strip()
        routing_config_path = root / "config" / "routing_rules.yml"
        routing_config = (
            yaml.safe_load(routing_config_path.read_text(encoding="utf-8"))
            if routing_config_path.exists()
            else {}
        )
        mission = {}
        route = None
        route_source = "task_router"
        try:
            from agent_runtime.brain.mission_contract import build_mission_contract
            from agent_runtime.workflow_plan import _route_from_mission_contract

            mission = build_mission_contract(text, project_id=project, task_id=task_id, agentlab_root=root)
            route = _route_from_mission_contract(mission, routing_config if isinstance(routing_config, dict) else None)
            if route is not None:
                route_source = "mission_contract"
        except Exception as exc:
            mission = {"error": f"{type(exc).__name__}: {exc}"}
            route = None

        if route is None:
            route = recommend_route(text, routing_config if isinstance(routing_config, dict) else None)

        production_pack = None
        try:
            from config_loader import load_agentlab_configs
            from agent_runtime.production_packs import build_production_pack
            from agent_runtime.workflow_plan import _route_for_production_pack

            configs = load_agentlab_configs(root)
            production_pack = build_production_pack(root, mission if isinstance(mission, dict) else {}, route, configs)
            route = _route_for_production_pack(route, production_pack)
        except Exception as exc:
            production_pack = {"error": f"{type(exc).__name__}: {exc}"}

        payload = route.model_dump(mode="json")
        payload["task_text"] = text
        payload["route_source"] = route_source
        payload["mission_route_decision"] = (mission or {}).get("route_decision") if isinstance(mission, dict) else None
        payload["production_pack"] = (
            production_pack.get("pack_id")
            if isinstance(production_pack, dict) and production_pack.get("pack_id")
            else production_pack_for_route(root, route.route_key)
        )
        payload["production_pack_status"] = production_pack.get("status") if isinstance(production_pack, dict) else None
        payload["probe_only"] = True
        payload["evidence_written"] = False
        console.print(yaml.safe_dump({"route_probe": payload}, sort_keys=False, allow_unicode=True), soft_wrap=True)

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
