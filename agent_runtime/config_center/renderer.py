"""Rich renderers for M2-5 Config Center CLI output."""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from agent_runtime.config_center.diff import ConfigDiff, DiffEntry
from agent_runtime.config_center.schema import ConfigValue
from agent_runtime.config_center.secrets_redaction import (
    REDACTED_PLACEHOLDER,
    is_secret_key,
)

console = Console()


def _safe_repr(value: Any, key: str = "", cv_is_secret: bool = False) -> str:
    """Render a value for display, redacting secrets.

    Redaction combines:
    1. Schema metadata (``ConfigValue.is_secret``)
    2. Key-name heuristics (e.g. ``*_api_key``, ``*_secret``)
    """
    last_seg = key.rsplit(".", 1)[-1] if key else ""
    if cv_is_secret or is_secret_key(last_seg):
        return REDACTED_PLACEHOLDER
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float)):
        return str(value)
    if value is None:
        return "<none>"
    if isinstance(value, str) and len(value) > 80:
        return value[:77] + "..."
    return str(value)


def render_config_list(resolved: dict[str, ConfigValue]) -> None:
    """Render a table of all config keys with source-layer metadata."""
    table = Table(title="Config Center — Resolved Configuration", expand=False)
    table.add_column("Key", style="cyan", no_wrap=False)
    table.add_column("Value", style="green", no_wrap=False)
    table.add_column("Source Layer", style="yellow")
    table.add_column("Secret", style="magenta")
    table.add_column("Overridden", style="dim")

    for key, cv in sorted(resolved.items()):
        # Redact secret values using both schema metadata and key-name heuristics
        display_value = _safe_repr(cv.value, key, cv_is_secret=cv.is_secret)
        secret_marker = "🔒" if cv.is_secret else ""
        overridden = ", ".join(o.name.lower() for o in cv.overridden_from) if cv.overridden_from else "—"
        table.add_row(key, display_value, cv.source_label, secret_marker, overridden)

    console.print(table)


def render_config_get(key: str, cv: ConfigValue) -> None:
    """Render a single config value with full metadata."""
    display_value = _safe_repr(cv.value, key, cv_is_secret=cv.is_secret)
    overridden = ", ".join(o.name.lower() for o in cv.overridden_from) if cv.overridden_from else "(none)"

    text = Text()
    text.append(f"Key:        ", style="bold")
    text.append(f"{key}\n")
    text.append(f"Value:      ", style="bold")
    text.append(f"{display_value}\n")
    text.append(f"Layer:      ", style="bold")
    text.append(f"{cv.source_label}\n")
    text.append(f"Overridden: ", style="bold")
    text.append(f"{overridden}\n")
    text.append(f"Is Secret:  ", style="bold")
    text.append(f"{'true' if cv.is_secret else 'false'}")

    console.print(Panel(text, title=f"Config: {key}", border_style="blue"))


def render_diff(diff: ConfigDiff) -> None:
    """Render a config diff as a Rich table."""
    title = f"Config Diff: {diff.base_label} → {diff.override_label}"
    table = Table(title=title, expand=False)
    table.add_column("Key", style="cyan", no_wrap=False)
    table.add_column("Kind", style="bold")
    table.add_column(f"Base ({diff.base_label})", style="yellow", no_wrap=False)
    table.add_column(f"Override ({diff.override_label})", style="green", no_wrap=False)

    for entry in diff.changed:
        kind_style = {"added": "green", "removed": "red", "changed": "yellow"}.get(entry.diff_kind, "white")
        base_str = _safe_repr(entry.base_value, entry.key)
        override_str = _safe_repr(entry.override_value, entry.key)
        table.add_row(
            entry.key,
            f"[{kind_style}]{entry.diff_kind}[/{kind_style}]",
            base_str,
            override_str,
        )

    console.print(table)
    if not diff.changed:
        console.print("[dim]No differences found.[/dim]")


def render_validation(errors: list[str]) -> None:
    """Render validation results."""
    if not errors:
        console.print("[green]✓ Configuration is valid.[/green]")
        return

    console.print(f"[red]✗ {len(errors)} validation error(s):[/red]")
    for err in errors:
        if err.startswith("error:"):
            console.print(f"  [red]{err[7:].strip()}[/red]")
        else:
            console.print(f"  [yellow]{err}[/yellow]")


def render_profiles(profiles: dict[str, dict[str, Any]]) -> None:
    """Render available config profiles."""
    table = Table(title="Config Profiles")
    table.add_column("Profile", style="cyan")
    table.add_column("Keys", style="dim")
    table.add_column("Description", style="green")

    for name, overrides in sorted(profiles.items()):
        desc = overrides.get("_description", "—")
        key_count = len([k for k in overrides if not k.startswith("_")])
        table.add_row(name, str(key_count), desc)

    console.print(table)
