"""CLI entrypoint for longform narrative acceptance evaluation."""

from __future__ import annotations

from pathlib import Path

import typer
import yaml
from rich.console import Console

from agent_runtime.narrative_eval import DEFAULT_CHAPTERS, DEFAULT_SUITE, VALID_MODES, run_narrative_eval


def _parse_chapters(value: str) -> list[int]:
    value = value.strip()
    if not value:
        return list(DEFAULT_CHAPTERS)
    if "-" in value:
        start_text, end_text = value.split("-", 1)
        start = int(start_text)
        end = int(end_text)
        if start < 1 or end < start:
            raise typer.BadParameter("chapter range must look like 1-3")
        return list(range(start, end + 1))
    chapters = [int(part.strip()) for part in value.split(",") if part.strip()]
    if not chapters or any(chapter < 1 for chapter in chapters):
        raise typer.BadParameter("chapters must be positive integers")
    return chapters


def register_narrative_eval_commands(app: typer.Typer, project_root: Path, console: Console) -> None:
    eval_app = typer.Typer(help="Longform narrative acceptance harness.", no_args_is_help=True)

    @eval_app.command("run")
    def run(
        project: str = typer.Option(..., "--project", help="Project name under projects/."),
        suite: str = typer.Option(DEFAULT_SUITE, "--suite", help="Acceptance suite id."),
        mode: str = typer.Option("live", "--mode", help="One of: audit-only, mock, live."),
        chapters: str = typer.Option("1-3", "--chapters", help="Chapter range or comma list, e.g. 1-3 or 1,2,3."),
        timestamp: str | None = typer.Option(None, "--timestamp", help="Stable acceptance run id for tests or reruns."),
        writer_worker: str | None = typer.Option(None, "--writer-worker", help="Worker id used to generate Writer role-session packets for live mode."),
        resume_valid: bool = typer.Option(False, "--resume-valid/--no-resume-valid", help="Reuse already valid chapter runs under the same timestamp."),
        stop_on_block: bool = typer.Option(False, "--stop-on-block/--continue-on-block", help="Stop before later chapters when one chapter delivery is blocked."),
    ) -> None:
        """Run L0-L3 longform acceptance checks without modifying production."""
        if mode not in VALID_MODES:
            raise typer.BadParameter(f"mode must be one of {sorted(VALID_MODES)}")
        result = run_narrative_eval(
            project_root,
            project,
            suite=suite,
            mode=mode,
            chapters=_parse_chapters(chapters),
            timestamp=timestamp,
            writer_worker=writer_worker,
            resume_valid=resume_valid,
            stop_on_block=stop_on_block,
        )
        console.print(yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip())
        if result.get("status") == "fail":
            raise typer.Exit(code=1)

    app.add_typer(eval_app, name="narrative-eval")
