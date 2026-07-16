"""CLI surface for AgentLab's governed self-evolution lifecycle."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import typer
import yaml
from rich.console import Console

from agent_runtime.self_evolution.control_plane import (
    collect_verifier_receipt,
    evolution_status,
    mark_review_ready,
    materialize_component,
    prepare_verifier_request,
    propose_component,
    record_gap_observation,
    validate_evolution,
    write_rollback_candidate,
)


ProjectRootProvider = Path | Callable[[], Path]


def _root(value: ProjectRootProvider) -> Path:
    return Path(value() if callable(value) else value).resolve()


def _print(console: Console, payload: dict) -> None:
    console.print(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True).rstrip())


def register_self_evolution_commands(
    app: typer.Typer,
    project_root: ProjectRootProvider,
    console: Console,
) -> None:
    evolution_app = typer.Typer(
        help="Governed AgentLab component evolution.",
        no_args_is_help=True,
    )

    @evolution_app.command("observe")
    def observe_cmd(
        out: Path = typer.Option(..., "--out", help="Observation output directory."),
        task_id: str = typer.Option(..., "--task-id"),
        capability: str = typer.Option(..., "--capability"),
        reason: str = typer.Option(..., "--reason"),
        explicit_user_request: bool = typer.Option(False, "--explicit-user-request"),
        input_contract: list[str] = typer.Option([], "--input"),
        output_contract: list[str] = typer.Option([], "--output"),
        permission_class: str = typer.Option("read_only", "--permission-class"),
        required_capability: list[str] = typer.Option([], "--required-capability"),
    ) -> None:
        path = record_gap_observation(
            _root(project_root),
            out,
            task_id=task_id,
            capability_id=capability,
            reason=reason,
            explicit_user_request=explicit_user_request,
            input_contract=input_contract,
            output_contract=output_contract,
            permission_class=permission_class,
            required_capabilities=required_capability,
        )
        _print(console, {"status": "observed", "path": str(path)})

    @evolution_app.command("propose")
    def propose_cmd(
        manifest: Path = typer.Option(..., "--manifest", exists=True, dir_okay=False),
        evidence: list[Path] = typer.Option(..., "--evidence", exists=True, dir_okay=False),
        evolution_dir: Path = typer.Option(..., "--evolution-dir"),
    ) -> None:
        result = propose_component(
            _root(project_root),
            manifest_path=manifest,
            evidence_paths=evidence,
            evolution_dir=evolution_dir,
        )
        _print(console, result)
        if result.get("status") == "blocked":
            raise typer.Exit(code=2)

    @evolution_app.command("materialize")
    def materialize_cmd(
        evolution_dir: Path = typer.Option(..., "--evolution-dir", exists=True),
        create_worktree: bool = typer.Option(
            True,
            "--create-worktree/--no-create-worktree",
            help="Create the isolated candidate branch/worktree.",
        ),
    ) -> None:
        result = materialize_component(
            _root(project_root),
            evolution_dir=evolution_dir,
            create_worktree=create_worktree,
        )
        _print(console, result)
        if result.get("status") == "blocked":
            raise typer.Exit(code=2)

    @evolution_app.command("validate")
    def validate_cmd(
        evolution_dir: Path = typer.Option(..., "--evolution-dir", exists=True),
        execute_commands: bool = typer.Option(
            True,
            "--execute-commands/--structural-only",
            help="Run the policy's focused and full regression commands.",
        ),
        verifier_receipt: Path | None = typer.Option(
            None,
            "--verifier-receipt",
            exists=True,
            dir_okay=False,
        ),
    ) -> None:
        result = validate_evolution(
            _root(project_root),
            evolution_dir=evolution_dir,
            execute_commands=execute_commands,
            independent_verification_path=verifier_receipt,
        )
        _print(console, result)
        if result.get("status") != "pass":
            raise typer.Exit(code=2)

    @evolution_app.command("review-ready")
    def review_ready_cmd(
        evolution_dir: Path = typer.Option(..., "--evolution-dir", exists=True),
        publish: bool = typer.Option(False, "--publish/--local-only"),
    ) -> None:
        result = mark_review_ready(
            _root(project_root),
            evolution_dir=evolution_dir,
            publish=publish,
        )
        _print(console, result)

    @evolution_app.command("verifier-request")
    def verifier_request_cmd(
        evolution_dir: Path = typer.Option(..., "--evolution-dir", exists=True),
        worker: str | None = typer.Option(None, "--worker"),
    ) -> None:
        result = prepare_verifier_request(
            _root(project_root),
            evolution_dir=evolution_dir,
            worker=worker,
        )
        _print(console, result)

    @evolution_app.command("verifier-collect")
    def verifier_collect_cmd(
        evolution_dir: Path = typer.Option(..., "--evolution-dir", exists=True),
        execution_receipt: Path | None = typer.Option(
            None,
            "--execution-receipt",
            exists=True,
            dir_okay=False,
        ),
    ) -> None:
        path = collect_verifier_receipt(
            _root(project_root),
            evolution_dir=evolution_dir,
            execution_receipt_path=execution_receipt,
        )
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        _print(console, {**payload, "path": str(path)})
        if payload.get("status") != "pass":
            raise typer.Exit(code=2)

    @evolution_app.command("status")
    def status_cmd(
        evolution_dir: Path = typer.Option(..., "--evolution-dir", exists=True),
    ) -> None:
        _print(console, evolution_status(_root(project_root), evolution_dir))

    @evolution_app.command("rollback")
    def rollback_cmd(
        evolution_dir: Path = typer.Option(..., "--evolution-dir", exists=True),
    ) -> None:
        _print(console, write_rollback_candidate(_root(project_root), evolution_dir))

    app.add_typer(evolution_app, name="self-evolution")
