"""External project registry CLI commands."""

from __future__ import annotations

from pathlib import Path

import typer
import yaml
from rich.console import Console
from rich.table import Table


def register_external_project_commands(app: typer.Typer, project_root: Path, console: Console) -> None:
    """Register M1 external project registry commands on a sub-application."""

    @app.command("list")
    def external_projects_list() -> None:
        """List registered external projects without executing external code."""
        from agent_runtime.external_projects import load_external_project_registry

        registry = load_external_project_registry(project_root)
        table = Table(title="AgentLab External Projects")
        table.add_column("project_id")
        table.add_column("role")
        table.add_column("enabled")
        table.add_column("stage")
        table.add_column("risk")
        for project in registry.to_sorted_projects():
            table.add_row(
                project.project_id,
                project.role,
                str(project.default_enabled).lower(),
                project.integration_stage,
                project.risk.level,
            )
        console.print(table)

    @app.command("inspect")
    def external_projects_inspect(project: str = typer.Option(..., "--project")) -> None:
        """Inspect one external project registry record."""
        from agent_runtime.external_projects import load_external_project_registry

        registry = load_external_project_registry(project_root)
        record = registry.get(project)
        console.print(yaml.safe_dump(record.to_dict(), sort_keys=False))

    @app.command("capability-map")
    def external_projects_capability_map(
        capability: str | None = typer.Option(None, "--capability"),
    ) -> None:
        """Show external projects mapped to a capability."""
        from agent_runtime.external_projects import load_external_project_registry

        registry = load_external_project_registry(project_root)
        if capability:
            providers = [project.project_id for project in registry.providers_for_capability(capability)]
            console.print(yaml.safe_dump({"capability": capability, "providers": providers}, sort_keys=False))
            return
        console.print(yaml.safe_dump({"capabilities": registry.capability_map()}, sort_keys=False))

    @app.command("risk-report")
    def external_projects_risk_report(out: Path = typer.Option(..., "--out")) -> None:
        """Write a registry-only external project risk report."""
        from agent_runtime.external_projects import (
            load_external_project_registry,
            write_external_project_risk_report,
        )

        registry = load_external_project_registry(project_root)
        yaml_path, md_path = write_external_project_risk_report(registry, out)
        console.print(f"wrote {yaml_path}")
        console.print(f"wrote {md_path}")
