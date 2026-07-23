"""Role and worker capability CLI commands."""

from __future__ import annotations

from pathlib import Path

import typer
import yaml
from rich.console import Console
from rich.table import Table


def register_role_capability_commands(app: typer.Typer, project_root: Path, console: Console) -> None:
    """Register role/capability inspection commands on the root CLI app."""

    @app.command("capability-list")
    def capability_list() -> None:
        """List S9 capability fabric records without executing any backend."""
        from agent_runtime.capabilities import create_builtin_registry

        table = Table(title="AgentLab Capability Fabric")
        table.add_column("capability_id")
        table.add_column("status")
        table.add_column("backend")
        table.add_column("risk")
        for record in create_builtin_registry().to_sorted_records():
            table.add_row(record.capability_id, record.status.value, record.backend_type, record.risk_level.value)
        console.print(table)

    @app.command("capability-check")
    def capability_check(
        capability: str = typer.Option(..., "--capability"),
        out: Path | None = typer.Option(None, "--out"),
    ) -> None:
        """Check whether a capability can be selected under default S9 policy."""
        from agent_runtime.capabilities import PermissionGate, create_builtin_registry, write_capability_gap_card

        registry = create_builtin_registry()
        decision = PermissionGate(registry).evaluate(capability)
        console.print(yaml.safe_dump({
            "capability": capability,
            "allowed": decision.allowed,
            "reason": decision.reason,
            "requires_approval": decision.requires_approval,
            "approval_mode": decision.approval_mode,
            "approval_grant": decision.approval_grant,
        }, sort_keys=False))
        if out and decision.reason == "missing_backend":
            path = write_capability_gap_card(
                registry=registry,
                capability_id=capability,
                out_dir=out,
                reason="capability check found no configured backend",
            )
            console.print(f"wrote {path}")

    @app.command("capability-gap")
    def capability_gap(
        capability: str = typer.Option(..., "--capability"),
        out: Path = typer.Option(..., "--out"),
        reason: str = typer.Option("capability requested but backend is unavailable", "--reason"),
    ) -> None:
        """Write a deterministic capability gap decision card."""
        from agent_runtime.capabilities import create_builtin_registry, write_capability_gap_card

        path = write_capability_gap_card(
            registry=create_builtin_registry(),
            capability_id=capability,
            out_dir=out,
            reason=reason,
        )
        console.print(f"wrote {path}")

    @app.command("capabilities")
    def capabilities() -> None:
        """List all defined capabilities in the AgentLab capability schema."""
        from agent_runtime.capabilities.capability_schema import CapabilitySchema
        from agent_runtime.capabilities.renderer import render_capabilities_table

        schema_path = project_root / "config" / "capability_schema.yml"
        schema = CapabilitySchema.load_from_file(schema_path)
        render_capabilities_table(schema.list_capabilities(), console)

    @app.command("role-requirements")
    def role_requirements() -> None:
        """List all AgentLab roles and a summary of their capability requirements."""
        from agent_runtime.capabilities.role_requirements import RoleRequirementsRegistry
        from agent_runtime.capabilities.renderer import render_role_requirements_table

        roles_path = project_root / "config" / "agent_role_requirements.yml"
        registry = RoleRequirementsRegistry.load_from_file(roles_path)
        render_role_requirements_table(registry.list_roles(), console)

    @app.command("role-inspect")
    def role_inspect(
        role: str = typer.Option(..., "--role", help="The name of the role to inspect (e.g. Coder)")
    ) -> None:
        """Inspect the capability requirements for a specific AgentLab role."""
        from agent_runtime.capabilities.role_requirements import RoleRequirementsRegistry
        from agent_runtime.capabilities.renderer import render_role_inspect

        roles_path = project_root / "config" / "agent_role_requirements.yml"
        registry = RoleRequirementsRegistry.load_from_file(roles_path)
        role_req = registry.get_role_requirements(role)
        if not role_req:
            console.print(f"[red]Error: Unknown role '{role}'.[/red]")
            raise typer.Exit(code=1)
        render_role_inspect(role_req, console)

    @app.command("role-compatible-workers")
    def role_compatible_workers(
        role: str = typer.Option(..., "--role", help="The name of the role to find compatible workers for (e.g. RepoScout)")
    ) -> None:
        """Show compatible workers for a specific AgentLab role."""
        from agent_runtime.capabilities.capability_schema import CapabilitySchema
        from agent_runtime.capabilities.compatibility import CompatibilityChecker, WorkerCapabilityRegistry
        from agent_runtime.capabilities.role_requirements import RoleRequirementsRegistry
        from agent_runtime.capabilities.renderer import render_compatible_workers

        schema_path = project_root / "config" / "capability_schema.yml"
        roles_path = project_root / "config" / "agent_role_requirements.yml"
        workers_path = project_root / "config" / "worker_capability_defaults.yml"

        schema = CapabilitySchema.load_from_file(schema_path)
        roles_registry = RoleRequirementsRegistry.load_from_file(roles_path)
        workers_registry = WorkerCapabilityRegistry.load_from_file(workers_path)

        role_req = roles_registry.get_role_requirements(role)
        if not role_req:
            console.print(f"[red]Error: Unknown role '{role}'.[/red]")
            raise typer.Exit(code=1)

        checker = CompatibilityChecker(schema, roles_registry, workers_registry)
        workers = sorted(list(workers_registry.get_all().keys()))

        render_compatible_workers(role_req, workers, checker, console)
