"""Capability result contract CLI commands."""

from __future__ import annotations

from pathlib import Path

import typer
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
