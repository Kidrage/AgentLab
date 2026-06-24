"""M2-5 Config Center CLI — config-list, config-get, config-diff, config-validate."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from agent_runtime.config_center.diff import project_diff
from agent_runtime.config_center.profile import load_profiles, get_active_profile
from agent_runtime.config_center.renderer import (
    console,
    render_config_list,
    render_config_get,
    render_diff,
    render_profiles,
    render_validation,
)
from agent_runtime.config_center.resolver import resolve_all_keys, resolve_key
from agent_runtime.config_center.validator import load_schema, validate_config_dry

app = typer.Typer(help="M2-5 Config Center commands.", no_args_is_help=True)


def _agentlab_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_schema_keys(root: Path) -> dict:
    """Load schema keys dict for secret-metadata propagation."""
    schema = load_schema(root / "config" / "config_center.yml")
    return schema.keys


@app.command("config-list")
def config_list(
    project: Optional[str] = typer.Option(None, "--project", help="Project name for project-level overrides"),
    limit: Optional[int] = typer.Option(None, "--limit", help="Max number of keys to display (no limit by default)"),
    show_all: bool = typer.Option(False, "--all", help="Show all keys (overrides --limit)"),
) -> None:
    """List all resolved config keys with source-layer metadata."""
    root = _agentlab_root()
    schema_keys = _load_schema_keys(root)

    effective_limit: int | None = None
    if show_all:
        effective_limit = None
    elif limit is not None:
        effective_limit = limit

    resolved, truncated, total = resolve_all_keys(
        root,
        project_name=project,
        limit=effective_limit,
        schema_keys=schema_keys,
    )
    if not resolved:
        console.print("[yellow]No config keys discovered.[/yellow]")
        return
    render_config_list(resolved)

    if truncated:
        console.print(
            f"\n[yellow]Showing {len(resolved)} of {total} config keys. "
            f"Use --all or --limit N to view more.[/yellow]"
        )

    # Show active profile if set
    active = get_active_profile(root)
    if active:
        console.print(f"\n[dim]Active profile: [bold]{active}[/bold][/dim]")


@app.command("config-get")
def config_get(
    key: str = typer.Option(..., "--key", help="Dotted config key path, e.g. routing_policy.default_budget"),
    project: Optional[str] = typer.Option(None, "--project", help="Project name for project-level overrides"),
) -> None:
    """Get a single config value with full source-layer metadata."""
    root = _agentlab_root()
    schema_keys = _load_schema_keys(root)
    cv = resolve_key(root, key, project_name=project, schema_keys=schema_keys)
    if cv is None:
        console.print(f"[red]Key '{key}' not found in any config layer.[/red]")
        raise typer.Exit(code=1)
    render_config_get(key, cv)


@app.command("config-diff")
def config_diff(
    project: str = typer.Option(..., "--project", help="Project name to diff against base config"),
) -> None:
    """Show config overrides for a project vs. the base config."""
    root = _agentlab_root()
    diff = project_diff(root, project)
    render_diff(diff)


@app.command("config-validate")
def config_validate(
    project: Optional[str] = typer.Option(None, "--project", help="Project name to validate"),
) -> None:
    """Validate the resolved config against the schema."""
    root = _agentlab_root()
    errors = validate_config_dry(root, project_name=project)
    if errors:
        render_validation(errors)
        raise typer.Exit(code=1)
    render_validation([])


@app.command("config-profiles")
def config_profiles() -> None:
    """List available config profiles."""
    root = _agentlab_root()
    profiles = load_profiles(root)
    if not profiles:
        console.print("[yellow]No config profiles defined.[/yellow]")
        return
    active = get_active_profile(root)
    render_profiles(profiles)
    if active:
        console.print(f"\n[dim]Active profile: [bold]{active}[/bold][/dim]")
