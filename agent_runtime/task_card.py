"""AgentLab Task Discovery & Resume Index — Task Card Renderer.

Provides human-readable formatting for task cards, search results, and resume candidates.
Uses Rich if available, else plain text.
"""

from __future__ import annotations

from typing import Optional

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    _HAS_RICH = True
except ImportError:
    _HAS_RICH = False


def render_task_card_text(record: dict) -> str:
    """Render a single task card as formatted text."""
    lines = []
    task_id = record.get("task_id", "unknown")
    lines.append(f"Task: {task_id}")
    lines.append(f"Title: {record.get('title', task_id)}")
    lines.append(f"Status: {record.get('status', 'unknown')}")
    lines.append(f"Resume state: {record.get('resume_state', 'unknown')}")
    lines.append(f"Can resume: {'yes' if record.get('can_resume') else 'no'}")
    lines.append(f"Progress: {record.get('percent_complete', 0)}%")

    agent = record.get("current_agent")
    if agent:
        lines.append(f"Current agent: {agent}")
    stage = record.get("current_stage")
    if stage:
        lines.append(f"Current stage: {stage}")
    event = record.get("last_event")
    if event:
        lines.append(f"Last event: {event}")

    summary = record.get("summary")
    if summary:
        lines.append(f"\nSummary:\n{summary}")

    # Artifacts
    lines.append("\nImportant artifacts:")
    for art in record.get("artifacts", []):
        if art.get("important"):
            status_icon = "✓" if art.get("status") == "present" else "✗"
            lines.append(f"  {status_icon} {art.get('path', '?')} - {art.get('title', '')}")

    # Backup
    backup = record.get("backup_status", {})
    if backup:
        gh = backup.get("github_synced", False)
        lines.append(f"\nBackup:")
        lines.append(f"  GitHub: {'synced ' + str(backup.get('github_commit', '')) if gh else 'not synced'}")
        lines.append(f"  TrueNAS: {'synced' if backup.get('truenas_synced') else 'not synced'}")

    # Commands
    cmds = record.get("commands", {})
    if cmds:
        lines.append("\nCommands:")
        for label, cmd in cmds.items():
            lines.append(f"  {label}: {cmd}")

    return "\n".join(lines)


def render_task_card_rich(record: dict) -> None:
    """Render a task card using Rich formatting."""
    if not _HAS_RICH:
        print(render_task_card_text(record))
        return

    console = Console()
    task_id = record.get("task_id", "unknown")
    title = record.get("title", task_id)
    status = record.get("status", "unknown")
    percent = record.get("percent_complete", 0)

    console.print(Panel(f"[bold]{title}[/bold]\n{task_id}"))

    # Status line
    status_color = {"completed": "green", "running": "cyan", "paused": "yellow", "blocked": "red"}.get(status, "white")
    console.print(f"  Status: [{status_color}]{status}[/{status_color}] | Resume: {record.get('resume_state', '?')} | Progress: {percent}%")

    if record.get("current_agent"):
        console.print(f"  Current: {record['current_agent']} / {record.get('current_stage', '?')}")
    event = record.get("last_event")
    if event:
        console.print(f"  Last: {event}")

    summary = record.get("summary")
    if summary:
        console.print(f"\n  [dim]{summary}[/dim]")

    # Artifacts table
    artifacts = [a for a in record.get("artifacts", []) if a.get("important")]
    if artifacts:
        console.print("\n[bold]Important Artifacts:[/bold]")
        for art in artifacts:
            icon = "✅" if art.get("status") == "present" else "❌"
            console.print(f"  {icon} {art.get('path', '?')} — {art.get('title', '')}")

    # Commands
    cmds = record.get("commands", {})
    if cmds:
        console.print("\n[bold]Commands:[/bold]")
        console.print(f"  Resume: [cyan]{cmds.get('resume', 'N/A')}[/cyan]")
        console.print(f"  Open:   [cyan]{cmds.get('open', 'N/A')}[/cyan]")

    console.print()


def render_task_results_table(results: list[dict]) -> str:
    """Render search results as formatted text."""
    if not results:
        return "No matching tasks found."

    lines = [f"\nFound {len(results)} matching tasks:\n"]
    for i, r in enumerate(results, 1):
        task_id = r.get("task_id", "?")
        title = r.get("title", task_id)
        status = r.get("status", "?")
        resume = r.get("resume_state", "?")
        percent = r.get("percent_complete", 0)
        score = r.get("score", 0)
        agent = r.get("current_agent", "")
        stage = r.get("current_stage", "")

        lines.append(f"[{i}] {task_id}")
        lines.append(f"    Title: {title}")
        lines.append(f"    Status: {status} | Resume: {resume} | Progress: {percent}%")
        if agent:
            lines.append(f"    Current: {agent} / {stage}")
        event = r.get("last_event")
        if event:
            lines.append(f"    Last: {event}")
        lines.append(f"    Score: {score}")
        cmds = r.get("commands", {})
        if cmds.get("open"):
            lines.append(f"    Open:   {cmds['open']}")
        if cmds.get("resume") and r.get("can_resume"):
            lines.append(f"    Resume: {cmds['resume']}")
        lines.append("")
    return "\n".join(lines)


def render_task_results_rich(results: list[dict]) -> None:
    """Render search results using Rich tables."""
    if not _HAS_RICH:
        print(render_task_results_table(results))
        return

    if not results:
        print("No matching tasks found.")
        return

    console = Console()
    console.print(f"\n[bold]Found {len(results)} matching tasks:[/bold]\n")

    table = Table("#", "Task ID", "Title", "Status", "Resume", "Progress", "Score")
    for i, r in enumerate(results, 1):
        table.add_row(
            str(i),
            r.get("task_id", ""),
            r.get("title", "")[:40],
            r.get("status", ""),
            r.get("resume_state", ""),
            f"{r.get('percent_complete', 0)}%",
            str(r.get("score", 0)),
        )
    console.print(table)

    # Command hints
    for i, r in enumerate(results, 1):
        cmds = r.get("commands", {})
        if cmds.get("open"):
            console.print(f"[{i}] Open: [cyan]{cmds['open']}[/cyan]")
        if cmds.get("resume") and r.get("can_resume"):
            console.print(f"[{i}] Resume: [cyan]{cmds['resume']}[/cyan]")


def render_resume_candidates(records: list[dict]) -> str:
    """Render list of resume candidates."""
    candidates = [r for r in records if r.get("can_resume")]
    if not candidates:
        return "No recoverable tasks found."

    lines = ["\nRecoverable tasks:\n"]
    for i, r in enumerate(candidates, 1):
        lines.append(f"[{i}] {r.get('task_id', '?')}")
        lines.append(f"    {r.get('status', '?')} | {r.get('percent_complete', 0)}% | {r.get('current_agent', '')}")
        lines.append(f"    Last: {r.get('last_event', '')}")
        cmds = r.get("commands", {})
        if cmds.get("resume"):
            lines.append(f"    Resume: {cmds['resume']}")
        lines.append("")
    return "\n".join(lines)


def render_resume_candidates_rich(records: list[dict]) -> None:
    """Render resume candidates using Rich."""
    if not _HAS_RICH:
        print(render_resume_candidates(records))
        return

    console = Console()
    candidates = [r for r in records if r.get("can_resume")]
    if not candidates:
        console.print("[yellow]No recoverable tasks found.[/yellow]")
        return

    console.print("\n[bold]Recoverable Tasks:[/bold]\n")
    for i, r in enumerate(candidates, 1):
        status_color = {"paused": "yellow", "blocked": "red", "running": "cyan"}.get(r.get("status", ""), "white")
        console.print(f"[{i}] [bold]{r.get('task_id', '?')}[/bold]")
        console.print(f"    [{status_color}]{r.get('status', '?')}[/{status_color}] | {r.get('percent_complete', 0)}% | {r.get('current_agent', '')}")
        console.print(f"    Last: {r.get('last_event', '')}")
        cmds = r.get("commands", {})
        if cmds.get("resume"):
            console.print(f"    Resume: [cyan]{cmds['resume']}[/cyan]")
        console.print()


def render_artifact_manifest_text(manifest: dict) -> str:
    """Render artifact manifest as plain text."""
    lines = [f"Artifacts for {manifest.get('task_id', 'unknown')}:\n"]
    for art in manifest.get("artifacts", []):
        icon = "✓" if art.get("status") == "present" else "✗"
        lines.append(f"  {icon} {art.get('path', '?')} [{art.get('kind', '?')}] {art.get('title', '')}")
        if art.get("summary"):
            lines.append(f"       {art['summary'][:100]}")
    summary = manifest.get("summary", {})
    lines.append(f"\nPresent: {summary.get('present', 0)} | Missing: {summary.get('missing', 0)}")
    imp = summary.get("important_missing", [])
    if imp:
        lines.append(f"Important missing: {', '.join(imp)}")
    return "\n".join(lines)