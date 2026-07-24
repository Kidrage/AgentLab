"""Small dependency-free AgentLab terminal front desk."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
import subprocess

from .snapshot_renderer import render_tui_snapshot


SubmitTask = Callable[[str, str], tuple[bool, str]]


def _submit_task(project: str, request: str) -> tuple[bool, str]:
    """Create one governed task from natural language without executing it."""
    root = Path(__file__).resolve().parents[1]
    task_id = datetime.now(timezone.utc).strftime("task_%Y%m%d%H%M%S%f")
    result = subprocess.run(
        [
            str(root / "agentlab.sh"),
            "init-task",
            "--project",
            project,
            "--task-id",
            task_id,
            "--request-text",
            request,
        ],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    output = (result.stdout or result.stderr).strip()
    return result.returncode == 0, output


def run_tui(
    project: str | None = None,
    *,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
    submit_fn: SubmitTask | None = None,
) -> None:
    """Run a natural-language task intake loop.

    Intake creates a task only. Preparation, approval, execution, and provider
    calls remain explicit AgentLab actions.
    """
    selected_project = project or "AgentLab"
    submit = submit_fn or _submit_task
    output_fn("=== AgentLab Natural-Language TUI ===")
    output_fn(f"Project: {selected_project}")
    output_fn("Describe a task, or use /project NAME, /status, /help, /quit.")
    while True:
        try:
            request = input_fn("agentlab> ").strip()
        except (EOFError, KeyboardInterrupt):
            output_fn("")
            return
        if not request:
            continue
        if request in {"/quit", "/exit"}:
            return
        if request == "/help":
            output_fn(
                "Natural language creates a governed task only; "
                "/project NAME switches project and /status is read-only."
            )
            continue
        if request.startswith("/project "):
            candidate = request.removeprefix("/project ").strip()
            if candidate:
                selected_project = candidate
                output_fn(f"Project: {selected_project}")
            else:
                output_fn("Project name is required.")
            continue
        if request == "/status":
            output_fn(
                render_tui_snapshot(
                    project=selected_project,
                    view="overview",
                )
            )
            continue
        ok, detail = submit(selected_project, request)
        if ok:
            output_fn("Task initialized; no execution or provider call was started.")
        else:
            output_fn("Task initialization failed.")
        if detail:
            output_fn(detail)
