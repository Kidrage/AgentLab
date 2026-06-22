"""Console rendering helpers for AgentLab capabilities and roles."""

from rich.console import Console
from rich.table import Table
from agent_runtime.capabilities.capability_schema import CapabilityDefinition
from agent_runtime.capabilities.role_requirements import RoleRequirementDefinition
from agent_runtime.capabilities.compatibility import CompatibilityChecker


def render_capabilities_table(capabilities: list[CapabilityDefinition], console: Console) -> None:
    """Render a table of all capabilities."""
    table = Table(title="AgentLab Capabilities Schema")
    table.add_column("Capability ID", style="cyan")
    table.add_column("Display Name")
    table.add_column("Description")
    table.add_column("Risk Level", style="bold")

    for cap in capabilities:
        risk_style = "green"
        if cap.risk_level.lower() == "high":
            risk_style = "red"
        elif cap.risk_level.lower() == "medium":
            risk_style = "yellow"

        table.add_row(
            cap.capability_id,
            cap.display_name,
            cap.description,
            f"[{risk_style}]{cap.risk_level.upper()}[/{risk_style}]"
        )
    console.print(table)


def render_role_requirements_table(roles: list[RoleRequirementDefinition], console: Console) -> None:
    """Render a summary table of all roles and their capability count."""
    table = Table(title="AgentLab Roles & Requirements Summary")
    table.add_column("Role", style="cyan")
    table.add_column("Required Caps Count", justify="right")
    table.add_column("Preferred Caps Count", justify="right")
    table.add_column("Forbidden Caps Count", justify="right")
    table.add_column("Risk Ceiling")

    for role in roles:
        table.add_row(
            role.role_id,
            str(len(role.required_capabilities)),
            str(len(role.preferred_capabilities)),
            str(len(role.forbidden_capabilities)),
            role.default_risk_ceiling.upper()
        )
    console.print(table)


def render_role_inspect(role_req: RoleRequirementDefinition, console: Console) -> None:
    """Render detailed information for a specific role."""
    console.print(f"\n[bold cyan]Role Inspection: {role_req.role_id}[/bold cyan]")
    console.print(f"  [bold]Risk Ceiling:[/bold] {role_req.default_risk_ceiling.upper()}")
    
    console.print("\n  [bold green]Required Capabilities:[/bold green]")
    if role_req.required_capabilities:
        for cap in role_req.required_capabilities:
            console.print(f"    - {cap}")
    else:
        console.print("    None")

    console.print("\n  [bold yellow]Preferred Capabilities:[/bold yellow]")
    if role_req.preferred_capabilities:
        for cap in role_req.preferred_capabilities:
            console.print(f"    - {cap}")
    else:
        console.print("    None")

    console.print("\n  [bold red]Forbidden Capabilities:[/bold red]")
    if role_req.forbidden_capabilities:
        for cap in role_req.forbidden_capabilities:
            console.print(f"    - {cap}")
    else:
        console.print("    None")

    console.print("\n  [bold magenta]Human Approval Required For:[/bold magenta]")
    if role_req.human_approval_required_for:
        for cap in role_req.human_approval_required_for:
            console.print(f"    - {cap}")
    else:
        console.print("    None")
    console.print("")


def render_compatible_workers(
    role_req: RoleRequirementDefinition,
    workers: list[str],
    checker: CompatibilityChecker,
    console: Console
) -> None:
    """Render a table showing which workers are compatible with a role."""
    table = Table(title=f"Worker Compatibility Matrix for Role: {role_req.role_id}")
    table.add_column("Worker ID", style="cyan")
    table.add_column("Compatible", style="bold")
    table.add_column("Approval Required", style="bold")
    table.add_column("Details/Reasons")

    for worker_id in workers:
        is_comp, reason = checker.is_compatible(worker_id, role_req.role_id)
        comp_str = "[green]YES[/green]" if is_comp else "[red]NO[/red]"
        
        if is_comp:
            req_app, reasons = checker.requires_approval_for_assignment(worker_id, role_req.role_id)
            app_str = f"[yellow]YES (caps: {', '.join(reasons)})[/yellow]" if req_app else "[green]NO[/green]"
            details = "All checks passed."
        else:
            app_str = "-"
            details = reason

        table.add_row(worker_id, comp_str, app_str, details)
    console.print(table)
