"""Capability result contract CLI commands."""

from __future__ import annotations

from pathlib import Path

import typer
import yaml
from rich.console import Console


def register_capability_contract_commands(app: typer.Typer, console: Console) -> None:
    """Register mock-only capability contract writer commands."""

    @app.command("vision-contract")
    def vision_contract(
        input_artifact: str = typer.Option(..., "--input"),
        out: Path = typer.Option(..., "--out"),
        mock: bool = typer.Option(False, "--mock"),
    ) -> None:
        """Write a mock-only vision result contract. Real model execution is not allowed here."""
        from agent_runtime.capabilities import write_vision_contract

        path = write_vision_contract(
            input_artifact=input_artifact,
            out_dir=out,
            observations=["mock vision observation; no image backend executed"],
            summary="mock vision contract only",
            evidence_artifacts=[input_artifact],
            confidence="mock_only",
            mock=mock,
        )
        console.print(f"wrote {path}")

    @app.command("audio-contract")
    def audio_contract(
        input_artifact: str = typer.Option(..., "--input"),
        out: Path = typer.Option(..., "--out"),
        mock: bool = typer.Option(False, "--mock"),
    ) -> None:
        """Write a mock-only audio result contract. Real audio execution is not allowed here."""
        from agent_runtime.capabilities import write_audio_contract

        path = write_audio_contract(
            input_artifact=input_artifact,
            out_dir=out,
            duration=0.0,
            observations=["mock audio observation; no audio backend executed"],
            transcript="mock transcript",
            features={"mode": "mock"},
            summary="mock audio contract only",
            evidence_artifacts=[input_artifact],
            confidence="mock_only",
            mock=mock,
        )
        console.print(f"wrote {path}")

    @app.command("document-contract")
    def document_contract(
        input_artifact: str = typer.Option(..., "--input"),
        out: Path = typer.Option(..., "--out"),
        mock: bool = typer.Option(False, "--mock"),
    ) -> None:
        """Write a mock-only document result contract. Real parser execution is not allowed here."""
        from agent_runtime.capabilities import write_document_contract

        path = write_document_contract(
            input_artifact=input_artifact,
            out_dir=out,
            pages=0,
            extracted_text="mock extracted text",
            tables=[],
            figures=[],
            citations=[],
            evidence_artifacts=[input_artifact],
            confidence="mock_only",
            mock=mock,
        )
        console.print(f"wrote {path}")

    @app.command("media-backend-preflight")
    def media_backend_preflight(
        contract: Path = typer.Option(..., "--contract", help="Path to media_generation_contract.yml."),
        out: Path | None = typer.Option(None, "--out", help="Optional YAML report path."),
    ) -> None:
        """Check selected media backend readiness without executing generation."""
        from agent_runtime.media_backend_adapter import load_media_generation_contract, preflight_media_contract

        root = Path(__file__).resolve().parents[2]
        report = preflight_media_contract(load_media_generation_contract(contract), root)
        text = yaml.safe_dump(report, sort_keys=False, allow_unicode=True)
        if out:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(text, encoding="utf-8")
            console.print(f"wrote {out}")
        else:
            console.print(text)

    @app.command("media-backend-execute")
    def media_backend_execute(
        contract: Path = typer.Option(..., "--contract", help="Path to media_generation_contract.yml."),
        out_dir: Path = typer.Option(..., "--out-dir", help="Directory for adapter evidence and generated assets."),
        live: bool = typer.Option(False, "--live", help="Opt in to real provider execution. Default is dry-run."),
        role_session: Path | None = typer.Option(
            None,
            "--role-session",
            help="ArtifactProducer role-session packet required for live execution.",
        ),
        role: str = typer.Option("ArtifactProducer", "--role", help="AgentLab role used when generating a live role-session packet."),
        worker: str | None = typer.Option(None, "--worker", help="Worker id used to generate a live role-session packet."),
        project: str | None = typer.Option(None, "--project", help="Project for generated role-session; defaults to contract project_id."),
        task_id: str | None = typer.Option(
            None,
            "--task-id",
            "--run-id",
            help="Task/run id for generated role-session; defaults to contract task_id.",
        ),
    ) -> None:
        """Execute or dry-run a media backend contract. Real provider calls require --live."""
        from agent_runtime.media_backend_adapter import execute_media_contract, load_media_generation_contract

        root = Path(__file__).resolve().parents[2]
        media_contract = load_media_generation_contract(contract)
        role_session_packet = None
        if role_session:
            role_session_packet = yaml.safe_load(role_session.read_text(encoding="utf-8")) or {}
        elif live and worker:
            from agent_runtime.protocols import build_role_session

            role_session_packet = build_role_session(
                root,
                role,
                worker,
                project=project or str(media_contract.get("project_id") or "AgentLab"),
                task_id=task_id or str(media_contract.get("task_id") or "task_0001"),
            )
        result = execute_media_contract(
            media_contract,
            root,
            out_dir,
            live=live,
            role_session=role_session_packet if isinstance(role_session_packet, dict) else {},
        )
        console.print(yaml.safe_dump(result, sort_keys=False, allow_unicode=True))
