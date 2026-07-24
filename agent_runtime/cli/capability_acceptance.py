"""CLI commands for capability acceptance and the current evidence chain."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console


def register_capability_acceptance_commands(
    app: typer.Typer,
    project_root: Path,
    console: Console,
) -> None:
    """Register capability-acceptance and evidence-chain commands."""

    @app.command("capability-acceptance")
    def capability_acceptance_cmd(
        out: Optional[Path] = typer.Option(
            None,
            "--out",
            help="Optional path to write the YAML report.",
        ),
        write_evidence_chain: bool = typer.Option(
            True,
            "--write-evidence-chain/--no-write-evidence-chain",
            help=(
                "When writing the canonical current.yml, also regenerate the "
                "canonical current evidence chain. Arbitrary --out paths never "
                "mutate the canonical chain."
            ),
        ),
    ) -> None:
        """Aggregate local evidence for AgentLab's core capability acceptance matrix."""
        from agent_runtime.capability_acceptance import (
            build_capability_acceptance_report,
            write_capability_acceptance_report,
        )
        from agent_runtime.capability_evidence_chain import (
            chain_path,
            is_canonical_acceptance_report_path,
        )
        from agent_runtime.report_sanitizer import dump_report_yaml

        agentlab_root = project_root
        if out:
            report = write_capability_acceptance_report(
                agentlab_root,
                out,
                write_evidence_chain=write_evidence_chain,
            )
            console.print(f"wrote {out}")
            if write_evidence_chain and is_canonical_acceptance_report_path(agentlab_root, out):
                console.print(f"wrote {chain_path(agentlab_root)}")
            console.print(dump_report_yaml(report, agentlab_root).rstrip())
        else:
            report = build_capability_acceptance_report(agentlab_root)
            console.print(dump_report_yaml(report, agentlab_root).rstrip())
        if report.get("overall_status") == "fail":
            raise typer.Exit(code=1)

    @app.command("capability-current-evidence-chain")
    def capability_current_evidence_chain_cmd(
        write: bool = typer.Option(
            False,
            "--write",
            help="Regenerate an evidence chain from the fixed canonical current.yml.",
        ),
        verify: bool = typer.Option(
            False,
            "--verify",
            help="Verify an evidence chain against the fixed canonical current.yml.",
        ),
    ) -> None:
        """Regenerate or verify the one canonical current capability evidence chain."""
        from agent_runtime.capability_evidence_chain import (
            chain_path,
            verify_capability_current_evidence_chain,
            write_capability_current_evidence_chain,
        )
        from agent_runtime.report_sanitizer import dump_report_yaml

        agentlab_root = project_root
        if not write and not verify:
            write = True
            verify = True

        exit_fail = False
        if write:
            chain = write_capability_current_evidence_chain(agentlab_root)
            written_path = chain_path(agentlab_root)
            console.print(f"wrote {written_path}")
            console.print(dump_report_yaml(chain, agentlab_root).rstrip())
            if chain.get("status") == "fail":
                exit_fail = True
        if verify:
            # Write+verify always checks the exact file that was just written.
            verification = verify_capability_current_evidence_chain(
                agentlab_root,
            )
            console.print(dump_report_yaml(verification, agentlab_root).rstrip())
            if verification.get("status") == "fail":
                exit_fail = True
        if exit_fail:
            raise typer.Exit(code=1)
