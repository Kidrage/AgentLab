"""CLI adapter for exact-manifest project resets."""

from __future__ import annotations

from pathlib import Path

import typer
import yaml
from rich.console import Console

from agent_runtime.atomic_io import atomic_write_yaml
from agent_runtime.project_reset import (
    CROWN_RESET_TARGETS,
    ProjectResetApplyError,
    ProjectResetError,
    apply_project_reset,
    plan_project_reset,
)


def _safe_manifest_path(root: Path, manifest: Path) -> Path:
    resolved_root = root.resolve()
    resolved = manifest.resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise typer.BadParameter("manifest must be inside the AgentLab root")
    return resolved


def register_project_reset_commands(
    app: typer.Typer,
    agentlab_root: Path,
    console: Console,
) -> None:
    reset = typer.Typer(
        help="Plan or apply an exact, hash-bound project reset.",
        no_args_is_help=True,
    )

    @reset.command("plan")
    def plan(
        project: str = typer.Option(..., "--project"),
        plan_id: str = typer.Option(..., "--plan-id"),
        manifest: Path = typer.Option(..., "--manifest"),
        target: list[str] | None = typer.Option(None, "--target"),
        distillation_seed: str | None = typer.Option(
            None,
            "--distillation-seed",
            help="Validated metadata-only fact seed under project reset_manifests/.",
        ),
    ) -> None:
        try:
            result = plan_project_reset(
                agentlab_root,
                project=project,
                targets=tuple(target or CROWN_RESET_TARGETS),
                plan_id=plan_id,
                distillation_seed=distillation_seed,
            )
            output = _safe_manifest_path(agentlab_root, manifest)
            atomic_write_yaml(output, result)
        except ProjectResetError as exc:
            raise typer.BadParameter(str(exc)) from exc
        console.print(f"status: preview\nmanifest: {output}\nentries: {result['entry_count']}")

    @reset.command("apply")
    def apply(
        manifest: Path = typer.Option(..., "--manifest"),
        confirm_project: str = typer.Option(..., "--confirm-project"),
        execute: bool = typer.Option(False, "--execute/--no-execute"),
    ) -> None:
        if not execute:
            raise typer.BadParameter("project reset apply requires explicit --execute")
        input_path = _safe_manifest_path(agentlab_root, manifest)
        try:
            raw = yaml.safe_load(input_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ProjectResetError("reset manifest must contain a YAML mapping")
            result = apply_project_reset(
                agentlab_root,
                plan=raw,
                confirm_project=confirm_project,
            )
            atomic_write_yaml(input_path, result)
        except ProjectResetApplyError as exc:
            atomic_write_yaml(input_path, exc.result)
            raise typer.BadParameter(str(exc)) from exc
        except (OSError, yaml.YAMLError, ProjectResetError) as exc:
            raise typer.BadParameter(str(exc)) from exc
        console.print(f"status: applied\nmanifest: {input_path}\nentries: {result['entry_count']}")

    app.add_typer(reset, name="project-reset")
