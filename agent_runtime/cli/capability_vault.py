"""Private Capability Vault CLI commands."""

from __future__ import annotations

from pathlib import Path

import typer
import yaml
from rich.console import Console

from agent_runtime.capability_vault import (
    CapabilityVaultError,
    load_private_capability_vault,
)


def register_capability_vault_commands(
    app: typer.Typer,
    agentlab_root: Path,
    console: Console,
) -> None:
    vault_app = typer.Typer(
        help="Private content-addressed capability package storage.",
        no_args_is_help=True,
    )

    @vault_app.command("doctor")
    def doctor() -> None:
        """Verify the private driver and Git metadata store without leaking paths."""
        try:
            result = load_private_capability_vault(agentlab_root).doctor()
        except CapabilityVaultError as exc:
            result = {
                "schema_version": "capability-vault-doctor/v1",
                "status": "blocked",
                "issues": [str(exc)],
                "private_locations_redacted": True,
            }
        console.print(
            yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip()
        )
        if result["status"] != "pass":
            raise typer.Exit(code=1)

    @vault_app.command("register")
    def register(
        manifest: Path = typer.Option(..., "--manifest"),
        source_archive: Path = typer.Option(..., "--source-archive"),
    ) -> None:
        """Register one immutable capability-package/v1 archive."""
        try:
            value = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
            if not isinstance(value, dict):
                raise CapabilityVaultError("manifest must be a mapping")
            result = load_private_capability_vault(agentlab_root).register(
                value,
                source_archive=source_archive,
            )
        except (
            OSError,
            UnicodeError,
            yaml.YAMLError,
            CapabilityVaultError,
        ) as exc:
            raise typer.BadParameter(str(exc)) from exc
        console.print(
            yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip()
        )

    app.add_typer(vault_app, name="capability-vault")
