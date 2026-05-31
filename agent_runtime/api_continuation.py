"""Codex Full-Driver Mode: API Continuation Module (Phase D).

Responsibilities:
1. Read handoff_packet.yml.
2. Reconstruct context package.
3. Run next API agent.
4. Append reports without destroying Codex artifacts.

CLI:
    ./agentlab.sh continue-with-api --project <ProjectName> --task-id <task_id> --from handoff_packet.yml
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml


def load_handoff_packet(project_root: Path, task_id: str) -> Optional[dict]:
    """Load and parse the handoff_packet.yml for a task.

    Args:
        project_root: Path to the project directory (projects/<ProjectName>/).
        task_id: Task run identifier.

    Returns:
        Parsed handoff packet dict, or None if not found or invalid.
    """
    handoff_path = project_root / "runs" / task_id / "handoff_packet.yml"
    if not handoff_path.exists():
        return None

    try:
        data = yaml.safe_load(handoff_path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
        return None
    except Exception:
        return None


def reconstruct_context_package(
    project_root: Path,
    task_id: str,
    handoff_packet: dict,
    include_reports: Optional[list[str]] = None,
) -> dict:
    """Rebuild a context package from all available artifacts.

    The context package includes all prior role reports so API agents can
    continue without needing to read the original Codex conversation.

    Args:
        project_root: Path to the project directory.
        task_id: Task run identifier.
        handoff_packet: Parsed handoff packet dict.
        include_reports: Optional list of specific report names to include.
            If None, includes all reports listed in handoff_packet.artifacts.

    Returns:
        A dict with:
            {
                "task_id": str,
                "project": str,
                "status": str,
                "handoff_packet": dict,
                "reports": {report_name: content_string},
                "code_state": dict,
                "validation": dict,
                "resume_instructions": dict,
            }
    """
    run_dir = project_root / "runs" / task_id

    if include_reports is None:
        artifact_files = handoff_packet.get("artifacts", {}).values()
    else:
        artifact_files = include_reports

    reports = {}
    for filename in artifact_files:
        p = run_dir / filename
        if p.exists():
            try:
                reports[filename] = p.read_text(encoding="utf-8")
            except Exception:
                reports[filename] = f"<error reading {filename}>"

    context = {
        "task_id": handoff_packet.get("task_id", task_id),
        "project": handoff_packet.get("project", project_root.name),
        "status": handoff_packet.get("status", "unknown"),
        "handoff_packet": handoff_packet,
        "reports": reports,
        "code_state": handoff_packet.get("code_state", {}),
        "validation": handoff_packet.get("validation", {}),
        "resume_instructions": handoff_packet.get("resume_instructions", {}),
        "next_agent": handoff_packet.get("next_agent"),
        "last_completed_agent": handoff_packet.get("last_completed_agent"),
    }

    return context


def continue_with_api(
    project_root: Path,
    task_id: str,
    provider: str = "deepseek",
    dry_run: bool = True,
) -> dict:
    """Continue a Codex Full-Driver task using API agents.

    This is the main entry point for resuming a task with AgentLab API agents
    after Codex stopped or completed its part.

    Args:
        project_root: Path to the project directory.
        task_id: Task run identifier.
        provider: API provider to use for the next agent.
        dry_run: If True, only reconstruct context without calling API.

    Returns:
        A dict with context and execution plan:
            {
                "handoff_loaded": bool,
                "next_agent": str | None,
                "context_reconstructed": bool,
                "report_count": int,
                "api_provider": str,
                "dry_run": bool,
                "plan": str,
            }
    """
    handoff = load_handoff_packet(project_root, task_id)
    if handoff is None:
        return {
            "handoff_loaded": False,
            "next_agent": None,
            "context_reconstructed": False,
            "report_count": 0,
            "api_provider": provider,
            "dry_run": dry_run,
            "plan": "ERROR: handoff_packet.yml not found. Cannot continue.",
        }

    context = reconstruct_context_package(project_root, task_id, handoff)
    next_agent = context.get("next_agent")
    report_count = len(context.get("reports", {}))

    plan = (
        f"Continue task {task_id} from agent '{next_agent}' "
        f"using {provider} API. "
        f"{len(context['reports'])} prior reports available as context. "
        f"Run './agentlab.sh run-agent {next_agent} --project {project_root.name} "
        f"--task-id {task_id} --execute' to execute the next agent."
    )

    result = {
        "handoff_loaded": True,
        "next_agent": next_agent,
        "context_reconstructed": True,
        "report_count": report_count,
        "api_provider": provider,
        "dry_run": dry_run,
        "plan": plan,
    }

    return result


def print_continuation_plan(result: dict) -> None:
    """Pretty-print the continuation plan (for CLI use)."""
    from rich.console import Console
    from rich.panel import Panel

    console = Console()

    if not result["handoff_loaded"]:
        console.print("[red]ERROR: handoff_packet.yml not found[/red]")
        console.print("Cannot continue task without a valid handoff packet.")
        return

    console.print(Panel("[bold]Codex → API Agent Continuation Plan[/bold]"))
    console.print(f"  Next agent: [cyan]{result['next_agent']}[/cyan]")
    console.print(f"  API provider: [cyan]{result['api_provider']}[/cyan]")
    console.print(f"  Prior reports available: [green]{result['report_count']}[/green]")
    console.print(f"  Dry run: {'[yellow]Yes[/yellow]' if result['dry_run'] else '[green]No[/green]'}")
    console.print()
    console.print("[bold]Plan:[/bold]")
    console.print(result["plan"])