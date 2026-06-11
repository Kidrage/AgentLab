"""AgentLab CLI entrypoint.

This CLI is local-first and conservative by default. It can create task folders,
prepare workflow plans, inspect model/provider config, and optionally run one
agent through a configured model API when `--execute` is explicitly passed.
"""

from __future__ import annotations

from pathlib import Path
from collections import defaultdict
from typing import Optional
import os

import typer
import yaml
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from agent_runner import (
    compose_agent_messages,
    is_placeholder_report,
    report_path_for_agent,
    resolve_agent_settings,
    run_agent_model,
)
from artifact_contract import artifact_content_issues
from guard import (
    acquire_lock,
    clear_stale_lock,
    release_lock,
    scan_stale_locks,
    update_heartbeat,
)
from brain_governor import (
    evaluate_harness_status,
    evaluate_token_status,
    request_coder_quota_decision,
    request_traversal_decision,
)
from config_loader import load_agentlab_configs
from cost_tracker import append_cost_ledgers, usage_entry
from model_resolver import resolve_profile_config, validate_model_configuration
from policies import (
    assert_path_allowed,
    ensure_dir_safe,
    ensure_safe_task_id,
    generate_slug_from_request,
    resolve_agentlab_root,
    task_number,
)
from schemas import TaskRunRequest
from state_store import load_state, mark_agent_completed, mark_planned, save_state, utc_now
from workflow_plan import build_workflow_plan

app = typer.Typer(help="AgentLab local-first CLI.", no_args_is_help=True)
console = Console()


def write_agent_artifact_gate_block(
    run_dir: Path,
    project: str,
    task_id: str,
    agent_name: str,
    output_path: Path,
    issues: list[str],
) -> Path:
    block_path = run_dir / f"blocked_{agent_name}_artifact_gate.md"
    lines = [
        "# Artifact Gate Blocked",
        "",
        f"- Project: {project}",
        f"- Task: {task_id}",
        f"- Agent: {agent_name}",
        f"- Report: {output_path}",
        "",
        "## Issues",
    ]
    lines.extend(f"- {issue}" for issue in issues)
    lines.extend([
        "",
        "## Required Action",
        "Regenerate or repair the artifact with executable evidence before marking the agent complete.",
        "",
    ])
    content = "\n".join(lines)
    block_path.write_text(content, encoding="utf-8")
    (run_dir / "USER_DECISION_REQUIRED.md").write_text(content, encoding="utf-8")
    return block_path


def runtime_context(project: Optional[str]) -> tuple[Path, str]:
    load_dotenv()
    configured_root = Path(os.getenv("AGENTLAB_ROOT") or Path(__file__).resolve().parents[1])
    agentlab_root = resolve_agentlab_root(configured_root)
    project_name = project or os.getenv("DEFAULT_PROJECT", "ExampleProject")
    return agentlab_root, project_name


def write_yaml_if_allowed(path: Path, data: dict, overwrite: bool = False) -> bool:
    if path.exists() and not overwrite:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return True


def write_text_if_missing(path: Path, text: str) -> bool:
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def ensure_project_memory_files(project_root: Path) -> None:
    docs_env = os.getenv("AGENTLAB_DOCS_DIR")
    if docs_env:
        docs = Path(docs_env)
    else:
        docs = project_root / "agent_docs"
    if docs.is_symlink() and not docs.exists():
        local_backup = docs.with_name(f"{docs.name}.local.bak")
        if local_backup.is_dir():
            docs = local_backup
    ensure_dir_safe(docs, "agent_docs")
    write_text_if_missing(
        docs / "07_DEVELOPMENT_LOG.md",
        "# Development Log\n\nRecords AgentLab team activity by module.\n\n## Module: General\n\n",
    )
    write_text_if_missing(
        docs / "08_CODEX_DIALOGUE_LOG.md",
        "# Codex Dialogue Log\n\nRecords user-visible Codex Coder conversations and implementation actions.\n\n",
    )
    if not (docs / "09_COST_LEDGER.yml").exists():
        write_yaml_if_allowed(docs / "09_COST_LEDGER.yml", {"entries": []})


def load_or_build_plan(
    agentlab_root: Path,
    project_name: str,
    task_id: str,
    execution_backend: str,
    user_request: Optional[Path] = None,
    budget_mode: Optional[str] = None,
):
    plan_path = agentlab_root / "projects" / project_name / "runs" / task_id / "workflow_plan.yml"
    if plan_path.exists() and user_request is None and budget_mode is None:
        data = yaml.safe_load(plan_path.read_text(encoding="utf-8")) or {}
        from schemas import WorkflowPlan

        return WorkflowPlan(**data)
    return build_workflow_plan(
        agentlab_root=agentlab_root,
        project_name=project_name,
        task_id=task_id,
        execution_backend=execution_backend,
        user_request_path=user_request,
        budget_mode=budget_mode,
    )


@app.command("init-task")
def init_task(
    task_id: str = typer.Option("task_0001", help="Task run id, such as task_0001 or task_0001_slug-name."),
    project: Optional[str] = typer.Option(None, help="Project name. Defaults to DEFAULT_PROJECT."),
    request_text: str = typer.Option("", help="Optional user request text to seed user_request.md."),
    request_file: Optional[Path] = typer.Option(None, help="Optional file to copy into user_request.md."),
    auto_slug: bool = typer.Option(True, help="Auto-append a human-readable slug derived from request_text."),
) -> None:
    """Create a task folder and safe placeholder files without overwriting.

    Task IDs now support a smart naming scheme: task_NNNN_slug-name.
    When --auto-slug is True (default), init-task will generate a
    readable slug from the request text and append it to the task ID.
    Example: task_0042_cloud-deploy-v2
    """
    # Auto-append slug if task_id is numeric-only and request_text has content
    if auto_slug and "_" not in task_id[5:] and request_text:
        slug = generate_slug_from_request(request_text)
        if slug and len(slug) >= 2:
            task_id = f"{task_id}_{slug}"
            console.print(f"[dim]Auto-slug -> {task_id}[/dim]")

    ensure_safe_task_id(task_id)
    agentlab_root, project_name = runtime_context(project)
    project_root = assert_path_allowed(agentlab_root / "projects" / project_name, agentlab_root)
    ensure_project_memory_files(project_root)
    run_dir = assert_path_allowed(agentlab_root / "projects" / project_name / "runs" / task_id, agentlab_root)

    if request_file:
        user_request = request_file.read_text(encoding="utf-8")
    else:
        user_request = request_text or "# User Request\n\nDescribe the task here.\n"

    created = []
    skipped = []
    templates = {
        "user_request.md": user_request,
        "01_supervisor_plan.md": "# Supervisor Plan\n\nTBD\n",
        "02_reposcout_report.md": "# RepoScout Report\n\nTBD\n",
        "03_research_notes.md": "# Research Notes\n\nTBD\n",
        "04_interface_map.md": "# Interface Map\n\nTBD\n",
        "05_coder_prompt.md": "# Coder Handoff Prompt\n\nTBD\n",
        "06_implementation_report.md": "# Implementation Report\n\nTBD\n",
        "07_validation_report.md": "# Validation Report\n\nTBD\n",
        "08_audit_report.md": "# Audit Report\n\nTBD\n",
        "verification_report.md": "# Verification Report\n\nTBD\n",
        "09_archive_update.md": "# Archive Update\n\nTBD\n",
        "cost_ledger.yml": "entries: []\n",
        "brain_decisions.yml": "decisions: []\n",
    }
    for name, text in templates.items():
        path = run_dir / name
        if write_text_if_missing(path, text):
            created.append(str(path))
        else:
            skipped.append(str(path))

    state = load_state(run_dir, project_name, task_id)
    state.status = "new"
    state.last_event = "Task initialized."
    save_state(run_dir, state)

    console.print("[bold]Task initialized[/bold]")
    console.print({"run_dir": str(run_dir), "created": created, "skipped_existing": skipped})


@app.command("task-clear")
def task_clear(
    task_id: str = typer.Argument(..., help="Task id to clear, e.g. task_0003."),
    project: Optional[str] = typer.Option(None, help="Project name."),
    reason: Optional[str] = typer.Option(None, help="Reason for clearing (optional)."),
) -> None:
    """Mark a blocked task as cleared (archived) while keeping audit trail."""
    ensure_safe_task_id(task_id)
    agentlab_root, project_name = runtime_context(project)
    project_root = assert_path_allowed(agentlab_root / "projects" / project_name, agentlab_root)
    ledger_path = project_root / "agent_docs" / "02_TASK_LEDGER.yml"

    if not ledger_path.exists():
        console.print(f"[yellow]Task ledger not found: {ledger_path}[/yellow]")
        return

    data = yaml.safe_load(ledger_path.read_text(encoding="utf-8")) or {}
    tasks = list(data.get("tasks", []))
    updated = False
    for t in tasks:
        if t.get("task_id") == task_id:
            old_status = t.get("status")
            t["status"] = "archived"
            t["cleared_reason"] = reason or "User cleared via CLI"
            console.print(f"[green]{task_id}: {old_status} -> archived[/green]")
            console.print(f"  Reason: {t['cleared_reason']}")
            updated = True
            break

    if not updated:
        console.print(f"[yellow]Task {task_id} not found in ledger[/yellow]")
        return

    data["tasks"] = tasks
    ledger_path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")

    # Log event
    timestamp = utc_now()
    dev_log = project_root / "agent_docs" / "07_DEVELOPMENT_LOG.md"
    entry = f"\n### {timestamp} - {task_id} - Supervisor\n\nModule: Task Management\n\nSummary: Task cleared: {reason or 'manual clear'}\n\n"
    dev_log.write_text(dev_log.read_text(encoding="utf-8") + entry, encoding="utf-8")

    console.print(f"[green]Task {task_id} cleared. Audit trail preserved.[/green]")

@app.command("task-list")
def task_list(
    project: Optional[str] = typer.Option(None, help="Project name."),
    status_filter: Optional[str] = typer.Option(None, help="Filter by status: pending, active, blocked, complete, archived."),
    priority_filter: Optional[str] = typer.Option(None, help="Filter by priority: P0, P1, P2, P3."),
    category_filter: Optional[str] = typer.Option(None, help="Filter by category: feature, bugfix, research, refactor, docs, infra."),
    show_blocked: bool = typer.Option(False, help="Show only blocked tasks with their reasons."),
) -> None:
    """Show the global task ledger with optional filters."""
    agentlab_root, project_name = runtime_context(project)
    project_root = assert_path_allowed(agentlab_root / "projects" / project_name, agentlab_root)
    ledger_path = project_root / "agent_docs" / "02_TASK_LEDGER.yml"
    if not ledger_path.exists():
        console.print(f"[yellow]Task ledger not found: {ledger_path}[/yellow]")
        return

    data = yaml.safe_load(ledger_path.read_text(encoding="utf-8")) or {}
    tasks = data.get("tasks", [])

    if status_filter:
        tasks = [t for t in tasks if t.get("status") == status_filter]
    if priority_filter:
        tasks = [t for t in tasks if t.get("priority") == priority_filter]
    if category_filter:
        tasks = [t for t in tasks if t.get("category") == category_filter]
    if show_blocked:
        tasks = [t for t in tasks if t.get("status") == "blocked"]

    def sort_key(t):
        prio_order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
        status_order = {"blocked": 0, "pending": 1, "active": 2, "complete": 3, "archived": 4}
        return (prio_order.get(t.get("priority", "P2"), 2), status_order.get(t.get("status", "pending"), 1))

    tasks.sort(key=sort_key)

    counts: dict[str, int] = defaultdict(int)
    for t in tasks:
        counts[t.get("status", "unknown")] += 1

    console.print(f"\n[bold]Task Ledger -- {project_name}[/bold]")
    console.print(f"  Total: {len(tasks)} | "
                  f"Pending: {counts.get('pending', 0)} | "
                  f"Active: {counts.get('active', 0)} | "
                  f"Blocked: {counts.get('blocked', 0)} | "
                  f"Complete: {counts.get('complete', 0)}\n")

    table = Table("ID", "Status", "Pri", "Cat", "Title", "Description", "Depends On", "Blocked Reason")
    for t in tasks:
        status_icon = {
            "pending": chr(9203),
            "active": chr(128260),
            "blocked": chr(128683),
            "complete": chr(10004),
            "archived": chr(128230),
        }.get(t.get("status", ""), "?")

        deps = t.get("depends_on") or []
        dep_str = ", ".join(deps) if deps else "-"
        blocked = t.get("blocked_reason") or "-"
        if len(blocked) > 30:
            blocked = blocked[:27] + "..."
        desc = t.get("description") or ""
        if len(desc) > 50:
            desc = desc[:47] + "..."

        table.add_row(
            t.get("task_id", ""),
            f"{status_icon} {t.get('status', '')}",
            t.get("priority", ""),
            t.get("category", ""),
            t.get("title", ""),
            desc,
            dep_str,
            blocked,
        )
    console.print(table)

    next_tasks = [t for t in tasks if t.get("status") in ("pending",) and not (t.get("depends_on") or [])]
    if next_tasks:
        next_task = next_tasks[0]
        console.print(f"\n[green]Recommended next: {next_task['task_id']} - {next_task['title']} (priority={next_task.get('priority', '?')})[/green]")
    blocked_tasks = [t for t in tasks if t.get("status") == "blocked"]
    if blocked_tasks:
        console.print(f"\n[yellow]{len(blocked_tasks)} blocked task(s) need attention[/yellow]")

@app.command("brain-status")
def brain_status(
    task_id: str = typer.Option("task_0001", help="Task run id."),
    project: Optional[str] = typer.Option(None, help="Project name."),
) -> None:
    """Show brain governance status for token budgets and agent progress."""
    ensure_safe_task_id(task_id)
    agentlab_root, project_name = runtime_context(project)
    plan = load_or_build_plan(agentlab_root, project_name, task_id, "codex")
    statuses = evaluate_token_status(plan, agentlab_root)

    table = Table("Agent", "Used", "Budget", "Warn At", "Stop At", "State")
    for agent, status in statuses.items():
        table.add_row(
            agent,
            str(status.get("used")),
            str(status.get("budget")),
            str(status.get("warning_at")),
            str(status.get("stop_at")),
            status.get("state", ""),
        )
    console.print(table)

    decisions_path = Path(plan.run_dir) / "brain_decisions.yml"
    user_decision_path = Path(plan.run_dir) / "USER_DECISION_REQUIRED.md"
    console.print(
        {
            "brain_decisions": str(decisions_path),
            "brain_decisions_exists": decisions_path.exists(),
            "user_decision_required": str(user_decision_path) if user_decision_path.exists() else None,
        }
    )

    harness = evaluate_harness_status(plan, agentlab_root)
    console.print("[bold]Harness status[/bold]")
    console.print({
        "state": harness.get("state"),
        "counts": harness.get("counts"),
        "policy_source": harness.get("policy_source"),
    })


@app.command("harness-status")
def harness_status(
    task_id: str = typer.Option("task_0001", help="Task run id."),
    project: Optional[str] = typer.Option(None, help="Project name."),
) -> None:
    """Show repo-local harness map, feedback, and project memory health."""
    ensure_safe_task_id(task_id)
    agentlab_root, project_name = runtime_context(project)
    plan = load_or_build_plan(agentlab_root, project_name, task_id, "codex")
    harness = evaluate_harness_status(plan, agentlab_root)

    console.print("[bold]AgentLab harness status[/bold]")
    console.print({
        "project": project_name,
        "task_id": task_id,
        "state": harness.get("state"),
        "counts": harness.get("counts"),
        "metrics": harness.get("metrics"),
        "policy_source": harness.get("policy_source"),
    })

    table = Table("Scope", "Path", "State", "Reason")
    for check in harness.get("checks", []):
        table.add_row(
            check.get("scope", ""),
            check.get("path", ""),
            check.get("state", ""),
            check.get("reason", ""),
        )
    console.print(table)

    recommendations = harness.get("recommendations") or []
    if recommendations:
        console.print("[bold yellow]Recommendations[/bold yellow]")
        for item in recommendations:
            console.print(f"- {item}")


@app.command("skill-status")
def skill_status(
    project: Optional[str] = typer.Option(None, help="Project name."),
) -> None:
    """Show Skill Evolution scaffold status and pending adoption requests."""
    agentlab_root, project_name = runtime_context(project)
    from skill_evolution import ensure_skill_registry, summarize_skill_system

    ensure_skill_registry(agentlab_root)
    summary = summarize_skill_system(agentlab_root, project_name)
    console.print("[bold]AgentLab Skill Evolution Status[/bold]")
    console.print({
        "project": project_name,
        "registry_path": summary["registry_path"],
        "skill_count": summary["skill_count"],
        "active_skill_count": summary["active_skill_count"],
        "retired_skill_count": summary["retired_skill_count"],
        "pending_request_count": summary["pending_request_count"],
        "request_queue": summary["request_queue"],
    })

    table = Table("Request", "Skill", "Source", "Status", "Est Tokens", "Est Cost")
    for req in summary.get("requests", [])[-10:]:
        cost = req.get("cost_preview", {}) or {}
        source = req.get("source", {}) or {}
        est_cost = cost.get("estimated_cost")
        currency = cost.get("cost_currency") or ""
        table.add_row(
            req.get("id", ""),
            req.get("skill_name", ""),
            source.get("type", ""),
            req.get("status", ""),
            str(cost.get("total_tokens", "")),
            f"{est_cost} {currency}".strip() if est_cost is not None else "unavailable",
        )
    console.print(table)


@app.command("skill-request")
def skill_request(
    project: Optional[str] = typer.Option(None, help="Project name."),
    name: str = typer.Option(..., "--name", help="Skill name."),
    source: str = typer.Option(..., "--source", help="Source URI, repo, or local path."),
    purpose: str = typer.Option(..., "--purpose", help="Why AgentLab should learn this skill."),
    source_type: str = typer.Option("manual", help="Source type: manual, github, skill_hub, self_learned."),
    applies_to: str = typer.Option("", help="Comma-separated future task categories."),
    has_scripts: bool = typer.Option(False, help="Mark request as containing scripts."),
    requires_network: bool = typer.Option(False, help="Mark request as requiring network during learning."),
    modifies_files: bool = typer.Option(True, help="Mark request as modifying files when used."),
    validation_runs: int = typer.Option(3, help="Estimated sandbox validation runs."),
) -> None:
    """Create a pending Skill Adoption Request without installing anything."""
    agentlab_root, project_name = runtime_context(project)
    from skill_evolution import build_skill_adoption_request, ensure_skill_registry, write_skill_adoption_request

    ensure_skill_registry(agentlab_root)
    risk = {
        "has_scripts": has_scripts,
        "requires_network": requires_network or source_type in {"github", "skill_hub"},
        "modifies_files": modifies_files,
        "permission_level": "medium" if modifies_files or has_scripts else "low",
    }
    request = build_skill_adoption_request(
        agentlab_root,
        project=project_name,
        skill_name=name,
        source=source,
        purpose=purpose,
        source_type=source_type,
        validation_runs=validation_runs,
        risk=risk,
        applies_to=[x.strip() for x in applies_to.split(",") if x.strip()],
    )
    path = write_skill_adoption_request(agentlab_root, request)
    console.print("[green]Skill adoption request created[/green]")
    console.print({
        "request": str(path),
        "status": request["status"],
        "cost_preview": request["cost_preview"],
        "risk": request["risk"],
    })


@app.command("feedback-status")
def feedback_status(
    project: Optional[str] = typer.Option(None, help="Project name."),
    task_id: Optional[str] = typer.Option(None, help="Optional task id."),
    stale_after_seconds: int = typer.Option(600, help="Seconds before running task is considered stale."),
) -> None:
    """Show Feedback & Intervention scaffold status from task events and decision cards."""
    if task_id:
        ensure_safe_task_id(task_id)
    agentlab_root, project_name = runtime_context(project)
    from feedback_manager import project_feedback_status

    summary = project_feedback_status(
        agentlab_root,
        project_name,
        task_id=task_id,
        stale_after_seconds=stale_after_seconds,
    )
    console.print("[bold]AgentLab Feedback Status[/bold]")
    console.print({
        "project": project_name,
        "task_count": summary["task_count"],
        "needs_attention_count": summary["needs_attention_count"],
    })

    table = Table("Task", "Feedback", "Level", "Pending", "Age", "Last Event")
    for item in summary.get("tasks", [])[-20:]:
        task_name = Path(item["run_dir"]).name
        age = item.get("last_event_age_seconds")
        table.add_row(
            task_name,
            item.get("feedback_status", ""),
            item.get("notification_level", ""),
            str(item.get("pending_decision_count", 0)),
            f"{age}s" if age is not None else "-",
            str(item.get("last_event") or "")[:80],
        )
    console.print(table)

    if task_id and summary.get("tasks"):
        events = summary["tasks"][0].get("recent_events", [])
        if events:
            console.print("[bold]Recent events[/bold]")
            for event in events[-10:]:
                console.print({
                    "time": event.get("time"),
                    "event": event.get("event"),
                    "stage": event.get("stage"),
                    "status": event.get("status"),
                    "severity": event.get("severity"),
                    "message": event.get("message"),
                })


@app.command("task-event")
def task_event(
    task_id: str = typer.Option("task_0001", help="Task run id."),
    project: Optional[str] = typer.Option(None, help="Project name."),
    event: str = typer.Option(..., "--event", help="Event type, such as TASK_CREATED or APPROVAL_REQUIRED."),
    stage: Optional[str] = typer.Option(None, help="Lifecycle stage."),
    status: Optional[str] = typer.Option(None, help="Fine task status, such as RUNNING or WAITING_FOR_APPROVAL."),
    severity: str = typer.Option("INFO", help="Notification level."),
    message: str = typer.Option("", help="Human-readable event message."),
) -> None:
    """Append one structured event to runs/<task_id>/task_events.jsonl."""
    ensure_safe_task_id(task_id)
    agentlab_root, project_name = runtime_context(project)
    run_dir = agentlab_root / "projects" / project_name / "runs" / task_id
    if not run_dir.exists():
        console.print(f"[yellow]Task run directory does not exist: {run_dir}[/yellow]")
        return
    from task_events import append_task_event

    event_record = append_task_event(
        run_dir,
        event,
        stage=stage,
        status=status,
        severity=severity,
        message=message,
    )
    console.print("[green]Task event appended[/green]")
    console.print({"log": str(run_dir / "task_events.jsonl"), "event": event_record})


def _decision_run_dirs(agentlab_root: Path, project: str, task_id: str | None) -> list[Path]:
    runs_root = agentlab_root / "projects" / project / "runs"
    if task_id:
        ensure_safe_task_id(task_id)
        run_dir = runs_root / task_id
        return [run_dir] if run_dir.exists() else []
    if not runs_root.exists():
        return []
    return [p for p in sorted(runs_root.iterdir()) if p.is_dir()]


def _find_decision_run_dir(agentlab_root: Path, project: str, decision_id: str, task_id: str | None = None) -> Path | None:
    from feedback_manager import load_decision_card

    for run_dir in _decision_run_dirs(agentlab_root, project, task_id):
        card, _path = load_decision_card(run_dir, decision_id)
        if card:
            return run_dir
    return None


@app.command("decision-list")
def decision_list(
    project: Optional[str] = typer.Option(None, help="Project name."),
    task_id: Optional[str] = typer.Option(None, help="Optional task id."),
    all_statuses: bool = typer.Option(False, "--all", help="Show resolved decisions too."),
) -> None:
    """List pending decision cards for chat/Web UI approval."""
    agentlab_root, project_name = runtime_context(project)
    from feedback_manager import decision_cards_dir, load_pending_decision_cards
    from atomic_io import safe_read_yaml

    rows = []
    for run_dir in _decision_run_dirs(agentlab_root, project_name, task_id):
        if all_statuses:
            root = decision_cards_dir(run_dir)
            cards = []
            if root.exists():
                for path in sorted(root.glob("*.yml")):
                    data = safe_read_yaml(path, default={}) or {}
                    if isinstance(data, dict):
                        data.setdefault("_path", str(path))
                        cards.append(data)
        else:
            cards = load_pending_decision_cards(run_dir)
        for card in cards:
            rows.append((run_dir.name, card))

    console.print("[bold]AgentLab Decisions[/bold]")
    console.print({"project": project_name, "count": len(rows), "show_all": all_statuses})
    table = Table("Task", "Decision", "Type", "Status", "Recommended", "Reason")
    for run_name, card in rows:
        table.add_row(
            run_name,
            card.get("id", ""),
            card.get("type", ""),
            card.get("status", ""),
            card.get("recommended_action", ""),
            str(card.get("reason", ""))[:90],
        )
    console.print(table)


@app.command("decision-approve")
def decision_approve(
    decision_id: str = typer.Argument(..., help="Decision card id."),
    project: Optional[str] = typer.Option(None, help="Project name."),
    task_id: Optional[str] = typer.Option(None, help="Optional task id to narrow search."),
    option: str = typer.Option("approve_resume", help="Option id to approve."),
) -> None:
    """Approve a pending decision card and clear the legacy USER_DECISION_REQUIRED gate."""
    agentlab_root, project_name = runtime_context(project)
    run_dir = _find_decision_run_dir(agentlab_root, project_name, decision_id, task_id)
    if run_dir is None:
        console.print(f"[yellow]Decision not found: {decision_id}[/yellow]")
        raise typer.Exit(code=1)

    from feedback_manager import resolve_decision_card
    card = resolve_decision_card(run_dir, decision_id, option_id=option, resolution="approved")
    console.print("[green]Decision approved[/green]")
    console.print({"task_id": run_dir.name, "decision_id": decision_id, "selected_option": card.get("selected_option")})


@app.command("decision-reject")
def decision_reject(
    decision_id: str = typer.Argument(..., help="Decision card id."),
    project: Optional[str] = typer.Option(None, help="Project name."),
    task_id: Optional[str] = typer.Option(None, help="Optional task id to narrow search."),
    option: str = typer.Option("stop_task", help="Option id to record with rejection."),
) -> None:
    """Reject a pending decision card."""
    agentlab_root, project_name = runtime_context(project)
    run_dir = _find_decision_run_dir(agentlab_root, project_name, decision_id, task_id)
    if run_dir is None:
        console.print(f"[yellow]Decision not found: {decision_id}[/yellow]")
        raise typer.Exit(code=1)

    from feedback_manager import resolve_decision_card
    card = resolve_decision_card(run_dir, decision_id, option_id=option, resolution="rejected")
    console.print("[yellow]Decision rejected[/yellow]")
    console.print({"task_id": run_dir.name, "decision_id": decision_id, "selected_option": card.get("selected_option")})


@app.command("decision-resume")
def decision_resume(
    task_id: str = typer.Argument(..., help="Task id to resume."),
    project: Optional[str] = typer.Option(None, help="Project name."),
    dry_run: bool = typer.Option(True, help="Dry-run resume."),
    fake_provider: bool = typer.Option(False, help="Use fake provider."),
) -> None:
    """Resume a task after its decision card has been approved."""
    ensure_safe_task_id(task_id)
    agentlab_root, project_name = runtime_context(project)
    from feedback_manager import load_pending_decision_cards
    from pipeline_runner import resume_pipeline

    run_dir = agentlab_root / "projects" / project_name / "runs" / task_id
    if not run_dir.exists():
        console.print(f"[yellow]Task run directory does not exist: {run_dir}[/yellow]")
        raise typer.Exit(code=1)
    pending = load_pending_decision_cards(run_dir)
    if pending:
        console.print("[yellow]Task still has pending decision cards. Approve or reject them before resume.[/yellow]")
        for card in pending:
            console.print(f"- {card.get('id')}: {card.get('reason')}")
        raise typer.Exit(code=1)
    if (run_dir / "USER_DECISION_REQUIRED.md").exists():
        console.print("[yellow]USER_DECISION_REQUIRED.md still exists. Approve a decision card before resume.[/yellow]")
        raise typer.Exit(code=1)

    result = resume_pipeline(
        agentlab_root,
        project_name,
        task_id,
        dry_run=dry_run,
        fake_provider=fake_provider,
        simulate_provider_recovered=True,
    )
    console.print("[bold]Decision Resume Result[/bold]")
    console.print(result)


@app.command("policy-status")
def policy_status(
    project: Optional[str] = typer.Option(None, help="Project name."),
) -> None:
    """Show hard AgentLab execution policy for brain and coder stages."""
    agentlab_root, _ = runtime_context(project)
    configs = load_agentlab_configs(agentlab_root)
    execution_policy = configs.get("execution_policy", {})
    brain_policy = execution_policy.get("brain_policy", {})
    tier_policy = execution_policy.get("execution_policy", {})
    coder_policy = execution_policy.get("coder_policy", {})
    providers = configs.get("model_providers", {}).get("providers", {})
    agent_registry = configs.get("agent_registry", {}).get("agents", {})
    from llm_provider import resolve_env_value

    supervisor_profile_name = agent_registry.get("Supervisor", {}).get("model_profile", "")
    supervisor_profile = resolve_profile_config(
        supervisor_profile_name,
        model_profiles=configs.get("model_profiles", {}),
        model_catalog=configs.get("model_catalog", {}),
        agent_name="Supervisor",
    )
    brain_provider_name = (
        brain_policy.get("required_provider")
        or supervisor_profile.get("provider")
        or "deepseek"
    )
    deepseek = providers.get(brain_provider_name, {})
    api_key_configured = bool(resolve_env_value(deepseek.get("api_key"), ""))
    default_api_coder = tier_policy.get("default_api_coder", {})
    external_window = tier_policy.get("external_ide_window", {})

    console.print("[bold]AgentLab execution policy[/bold]")
    console.print(
        {
            "schema_version": execution_policy.get("schema_version", 1),
            "budget_mode_default": execution_policy.get("budget_mode_policy", {}).get("default_budget_mode", ""),
            "brain_required_provider": brain_provider_name,
            "brain_agent": brain_policy.get("brain_agent", "Supervisor"),
            "brain_tier": brain_policy.get("brain_tier", ""),
            "deepseek_required_for_all_agentlab_tasks": brain_policy.get(
                "deepseek_required_for_all_agentlab_tasks",
                brain_provider_name == "deepseek",
            ),
            "codex_may_simulate_brain": brain_policy.get("codex_may_simulate_brain", False),
            "deepseek_api_key_configured": api_key_configured,
            "coder_default_provider": default_api_coder.get("provider", coder_policy.get("api_fallback_executor", "")),
            "coder_default_model": default_api_coder.get("model", ""),
            "external_ide_window_enabled": external_window.get("enabled", False),
            "patch_application_policy": tier_policy.get("patch_application_policy", ""),
            "automatic_patch_application": coder_policy.get(
                "automatic_patch_application",
                tier_policy.get("patch_application_policy") == "apply_directly",
            ),
            "codex_quota_insufficient_action": coder_policy.get("if_codex_quota_insufficient", "ask_user"),
            "coder_quota_choices": coder_policy.get("user_choices_when_quota_insufficient", []),
        }
    )


@app.command("request-traversal")
def request_traversal(
    agent_name: str = typer.Argument(..., help="Agent requesting traversal."),
    task_id: str = typer.Option("task_0001", help="Task run id."),
    project: Optional[str] = typer.Option(None, help="Project name."),
    scope: str = typer.Option("targeted", help="Requested scope, such as targeted, module, full_repo."),
    reason: str = typer.Option(..., help="Why traversal is needed."),
    estimated_files: int = typer.Option(0, help="Estimated number of files to inspect."),
    estimated_tokens: int = typer.Option(0, help="Estimated token cost."),
    full_repo: bool = typer.Option(False, help="Whether this is a full repo/directory traversal request."),
) -> None:
    """Ask the brain governor for traversal permission."""
    ensure_safe_task_id(task_id)
    agentlab_root, project_name = runtime_context(project)
    plan = load_or_build_plan(agentlab_root, project_name, task_id, "codex")
    decision = request_traversal_decision(
        agentlab_root=agentlab_root,
        plan=plan,
        agent_name=agent_name,
        requested_scope=scope,
        reason=reason,
        estimated_files=estimated_files,
        estimated_tokens=estimated_tokens,
        full_repo=full_repo,
    )
    console.print("[bold]Brain traversal decision[/bold]")
    console.print(decision.model_dump())
    if decision.requires_user:
        console.print("[yellow]User yes/no decision required in the main Codex conversation.[/yellow]")
        console.print(str(Path(plan.run_dir) / "USER_DECISION_REQUIRED.md"))


@app.command("request-coder-quota")
def request_coder_quota(
    task_id: str = typer.Option("task_0001", help="Task run id."),
    project: Optional[str] = typer.Option(None, help="Project name."),
    reason: str = typer.Option(..., help="Why Codex quota may be insufficient."),
    quota_status: str = typer.Option("insufficient", help="Manual quota status label."),
    estimated_codex_tokens: int = typer.Option(0, help="Rough remaining Codex token need."),
) -> None:
    """Ask the user whether to pause Coder work or delegate coding to DeepSeek."""
    ensure_safe_task_id(task_id)
    agentlab_root, project_name = runtime_context(project)
    plan = load_or_build_plan(agentlab_root, project_name, task_id, "codex")
    decision = request_coder_quota_decision(
        agentlab_root=agentlab_root,
        plan=plan,
        reason=reason,
        quota_status=quota_status,
        estimated_codex_tokens=estimated_codex_tokens,
    )
    console.print("[bold]Coder quota decision required[/bold]")
    console.print(decision.model_dump())
    console.print("[yellow]Ask the user in the main Codex conversation before continuing Coder work.[/yellow]")
    console.print(str(Path(plan.run_dir) / "USER_DECISION_REQUIRED.md"))


@app.command("log-event")
def log_event(
    task_id: str = typer.Option("task_0001", help="Task run id."),
    project: Optional[str] = typer.Option(None, help="Project name."),
    module: str = typer.Option("General", help="Project module name for the development log."),
    agent: str = typer.Option("Codex", help="Agent or executor name."),
    summary: str = typer.Option(..., help="What was handled."),
    user_message: str = typer.Option("", help="User-visible request or dialogue summary."),
    codex_response: str = typer.Option("", help="Codex-visible response/action summary."),
    files_changed: str = typer.Option("", help="Comma-separated changed files."),
    commands_run: str = typer.Option("", help="Comma-separated commands actually run."),
    provider: str = typer.Option("codex_plus_manual", help="Provider or executor."),
    model: str = typer.Option("Codex Plus", help="Model/executor label."),
) -> None:
    """Append project development, dialogue, and cost log entries."""
    ensure_safe_task_id(task_id)
    agentlab_root, project_name = runtime_context(project)
    project_root = assert_path_allowed(agentlab_root / "projects" / project_name, agentlab_root)
    run_dir = assert_path_allowed(project_root / "runs" / task_id, agentlab_root)
    ensure_project_memory_files(project_root)
    docs = project_root / "agent_docs"
    if docs.is_symlink() and not docs.exists() and docs.with_name("agent_docs.local.bak").is_dir():
        docs = docs.with_name("agent_docs.local.bak")
    if not docs.exists() and docs.with_name("agent_docs.local.bak").is_dir():
        docs = docs.with_name("agent_docs.local.bak")

    timestamp = utc_now()
    dev_log = docs / "07_DEVELOPMENT_LOG.md"
    dialogue_log = docs / "08_CODEX_DIALOGUE_LOG.md"

    dev_entry = f"""
### {timestamp} - {task_id} - {agent}

Module: {module}

Summary: {summary}

Files changed: {files_changed or "none recorded"}

Commands run: {commands_run or "none recorded"}

"""
    dialogue_entry = f"""
## {timestamp} - {task_id} - {agent}

### User Message / Request
{user_message or "Not recorded."}

### Codex Response / Action Summary
{codex_response or summary}

"""
    dev_log.write_text(dev_log.read_text(encoding="utf-8") + dev_entry, encoding="utf-8")
    dialogue_log.write_text(dialogue_log.read_text(encoding="utf-8") + dialogue_entry, encoding="utf-8")

    entry = usage_entry(
        project=project_name,
        task_id=task_id,
        agent_name=agent,
        provider=provider,
        model=model,
        status="manual_logged",
        notes=summary,
    )
    append_cost_ledgers(project_root, run_dir, entry)
    console.print("[green]Logged AgentLab event[/green]")
    console.print({"development_log": str(dev_log), "dialogue_log": str(dialogue_log)})


@app.command("prepare")
def prepare(
    task_id: str = typer.Option("task_0001", help="Task run id, such as task_0001."),
    project: Optional[str] = typer.Option(None, help="Project name. Defaults to DEFAULT_PROJECT."),
    user_request: Optional[Path] = typer.Option(None, help="Optional path to a user request file."),
    execution_backend: str = typer.Option("codex", help="Planned Coder backend: codex or qwen."),
    budget: Optional[str] = typer.Option(None, "--budget", help="Budget mode: frugal, balanced, or max-quality."),
    write_plan: bool = typer.Option(False, help="Write runs/task_xxxx/workflow_plan.yml if it does not exist."),
    overwrite_plan: bool = typer.Option(False, help="Allow replacing an existing workflow_plan.yml."),
) -> None:
    """Build and optionally save the visible workflow plan."""
    ensure_safe_task_id(task_id)
    if execution_backend not in {"codex", "qwen"}:
        raise typer.BadParameter("execution_backend must be codex or qwen")

    agentlab_root, project_name = runtime_context(project)
    plan = build_workflow_plan(
        agentlab_root=agentlab_root,
        project_name=project_name,
        task_id=task_id,
        execution_backend=execution_backend,
        user_request_path=user_request,
        budget_mode=budget,
    )

    request = TaskRunRequest(
        project=project_name,
        task_id=task_id,
        user_request_path=plan.user_request_path,
        run_dir=plan.run_dir,
        execution_backend=execution_backend,
        recommended_route=plan.route.agents,
    )

    console.print("[bold]AgentLab prepare[/bold]")
    console.print("No model calls, source edits, dependency installs, or validation commands were run.")
    console.print(request.model_dump())
    console.print("[bold]Workflow plan[/bold]")
    console.print(plan.model_dump())

    if write_plan:
        plan_path = Path(plan.run_dir) / "workflow_plan.yml"
        wrote = write_yaml_if_allowed(plan_path, plan.model_dump(mode="json"), overwrite=overwrite_plan)
        if wrote:
            mark_planned(Path(plan.run_dir), project_name, task_id)
            from progress_tracker import create_progress, load_progress
            from lifecycle_graph import create_lifecycle, load_lifecycle, mark_node_completed
            from task_snapshot import safe_write_task_snapshot
            run_dir = Path(plan.run_dir)
            if load_progress(run_dir) is None:
                create_progress(
                    run_dir,
                    project_name,
                    task_id,
                    list(plan.route.agents),
                    risk_level=plan.risk_level,
                    budget_mode=plan.budget_mode,
                )
            if load_lifecycle(run_dir) is None:
                create_lifecycle(run_dir, plan.model_dump(mode="json"))
                mark_node_completed(run_dir, "INIT_TASK")
                mark_node_completed(run_dir, "PREPARE_PLAN")
            safe_write_task_snapshot(run_dir, project_name, task_id)
            console.print(f"[green]Wrote workflow plan:[/green] {plan_path}")
        else:
            console.print(f"[yellow]Plan already exists and was not overwritten:[/yellow] {plan_path}")


@app.command("status")
def status(
    task_id: str = typer.Option("task_0001", help="Task run id."),
    project: Optional[str] = typer.Option(None, help="Project name."),
) -> None:
    """Show task state, route, reports, and missing inputs."""
    ensure_safe_task_id(task_id)
    agentlab_root, project_name = runtime_context(project)
    plan = load_or_build_plan(agentlab_root, project_name, task_id, "codex")
    state = load_state(Path(plan.run_dir), project_name, task_id)

    console.print("[bold]Task status[/bold]")
    console.print(state.model_dump())
    console.print("[bold]Route[/bold]")
    console.print(plan.route.model_dump())
    if plan.missing_inputs:
        console.print("[yellow]Missing inputs[/yellow]")
        console.print(plan.missing_inputs)

    table = Table("Agent", "Report", "Exists")
    for agent in plan.route.agents:
        path = report_path_for_agent(plan, agent)
        table.add_row(agent, str(path), "yes" if path.exists() else "no")
    console.print(table)


@app.command("models")
def models(
    project: Optional[str] = typer.Option(None, help="Project name, only used to resolve root."),
) -> None:
    """Show configured providers and agent model profiles without exposing secrets."""
    agentlab_root, _ = runtime_context(project)
    configs = load_agentlab_configs(agentlab_root)
    providers = configs.get("model_providers", {}).get("providers", {})
    registry = configs.get("agent_registry", {}).get("agents", {})

    provider_table = Table("Provider", "Type", "Base URL", "API Key")
    from llm_provider import resolve_env_value

    for name, config in providers.items():
        provider_table.add_row(
            name,
            config.get("type", ""),
            resolve_env_value(config.get("base_url"), ""),
            "configured" if resolve_env_value(config.get("api_key"), "") else "missing",
        )
    console.print(provider_table)

    agent_table = Table("Agent", "Profile", "Provider", "Model", "Max Output", "Source")
    for agent_name in registry:
        settings, _ = resolve_agent_settings(agentlab_root, agent_name)
        profile = resolve_profile_config(
            settings.profile_name,
            model_profiles=configs.get("model_profiles", {}),
            model_catalog=configs.get("model_catalog", {}),
            agent_name=agent_name,
        )
        agent_table.add_row(
            agent_name,
            settings.profile_name,
            settings.provider,
            settings.model,
            str(settings.max_output_tokens),
            str(profile.get("source", "")),
        )
    console.print(agent_table)

    check = validate_model_configuration(configs)
    console.print("[bold]Model config check[/bold]")
    console.print({"status": check["status"], "issue_count": check["issue_count"]})
    for issue in check.get("issues", [])[:12]:
        console.print(issue)


@app.command("model-doctor")
def model_doctor(
    project: Optional[str] = typer.Option(None, help="Project name, only used to resolve root."),
) -> None:
    """Audit model/provider wiring without making network calls."""
    agentlab_root, _ = runtime_context(project)
    configs = load_agentlab_configs(agentlab_root)
    check = validate_model_configuration(configs)

    console.print("[bold]AgentLab model doctor[/bold]")
    console.print({"status": check["status"], "issue_count": check["issue_count"]})

    table = Table("Agent", "Origin", "Profile", "Provider", "Model", "Source")
    for row in check.get("resolved_profiles", []):
        table.add_row(
            row.get("agent", ""),
            row.get("origin", ""),
            row.get("profile", ""),
            row.get("provider", ""),
            row.get("model", ""),
            row.get("source", ""),
        )
    console.print(table)

    if check.get("issues"):
        issue_table = Table("Severity", "Scope", "Issue", "Provider/Profile")
        for issue in check["issues"]:
            scope = issue.get("agent") or issue.get("provider") or "global"
            provider_profile = issue.get("provider") or issue.get("profile") or ""
            issue_table.add_row(issue.get("severity", ""), scope, issue.get("issue", ""), provider_profile)
        console.print(issue_table)


@app.command("run-agent")
def run_agent(
    agent_name: str = typer.Argument(..., help="Agent name, e.g. Supervisor or Coder."),
    task_id: str = typer.Option("task_0001", help="Task run id."),
    project: Optional[str] = typer.Option(None, help="Project name."),
    execution_backend: str = typer.Option("codex", help="Coder backend recorded in the workflow plan."),
    budget: Optional[str] = typer.Option(None, "--budget", help="Budget mode used when rebuilding a plan: frugal, balanced, or max-quality."),
    provider: Optional[str] = typer.Option(None, help="Override provider, e.g. deepseek or openai."),
    model: Optional[str] = typer.Option(None, help="Override model id for this run."),
    output: Optional[Path] = typer.Option(None, help="Optional report output path, relative to run dir unless absolute."),
    execute: bool = typer.Option(False, help="Actually call the configured model API. Default is dry-run."),
    overwrite_report: bool = typer.Option(False, help="Overwrite an existing non-placeholder report."),
    force: bool = typer.Option(False, help="Allow running an agent not present in the selected route."),
    no_apply_patches: bool = typer.Option(False, help="Skip applying structured edit blocks from the LLM output."),
) -> None:
    """Dry-run or execute a single agent and write its report."""
    ensure_safe_task_id(task_id)
    agentlab_root, project_name = runtime_context(project)
    plan = load_or_build_plan(agentlab_root, project_name, task_id, execution_backend, budget_mode=budget)
    if agent_name not in plan.route.agents and not force:
        raise typer.BadParameter(f"{agent_name} is not in route {plan.route.agents}. Use --force to override.")

    output_path = assert_path_allowed(report_path_for_agent(plan, agent_name, output), agentlab_root)
    settings, _ = resolve_agent_settings(
        agentlab_root,
        agent_name,
        provider,
        model,
        profile_config=(plan.model_profiles or {}).get(agent_name),
    )
    messages = compose_agent_messages(agentlab_root, plan, agent_name, output_path)

    console.print("[bold]Agent run plan[/bold]")
    console.print(
        {
            "agent": agent_name,
            "project": project_name,
            "task_id": task_id,
            "provider": settings.provider,
            "model": settings.model,
            "api_key_configured": settings.api_key_configured,
            "output": str(output_path),
            "execute": execute,
            "apply_patches": not no_apply_patches,
        }
    )

    if (
        execute
        and agent_name == "Coder"
        and settings.provider == "external_ide_ai"
        and provider not in {"qwen-coder", "qwen", "qwen3", "deepseek", "deepseek-coder"}
    ):
        console.print()
        console.print("[bold yellow]??? Coder ??? Codex Plus ????[/bold yellow]")
        console.print()
        console.print("  ?? Coder executor ?? [bold]Codex Plus[/bold]?????? Codex Plus ???Coder ??")
        console.print("  1. ?????????:")
        console.print(f"     supervisor_plan:   {Path(plan.run_dir) / 'supervisor_plan.md'}")
        console.print(f"     reposcout_report:  {Path(plan.run_dir) / 'reposcout_report.md'}")
        console.print(f"     workflow_plan:     {Path(plan.run_dir) / 'workflow_plan.yml'}")
        console.print()
        console.print("  [dim]To use the DashScope Qwen API fallback explicitly:[/dim]")
        console.print(f"  [dim]./agentlab.sh run-agent Coder --project {project_name} --task-id {task_id} --execute --provider qwen-coder [/dim]")
        console.print()
        handoff_path = Path(plan.run_dir) / "codex_fallback_Coder.md"
        handoff_path.write_text(
            f"# Coder Handoff to External IDE AI\n\n"
            f"Provider: {settings.provider}\n"
            f"Model: {settings.model}\n\n"
            f"CLI blocked automatic Coder execution.\n",
            encoding="utf-8",
        )
        console.print(f"[dim]Handoff file: {handoff_path}[/dim]")
        return

    if not execute:
        console.print("[yellow]Dry run only. No model API call was made.[/yellow]")
        console.print("[bold]Prompt preview[/bold]")
        console.print(messages[0]["content"][:1800])
        return

    tx_id = None
    try:
        tx_id = acquire_lock(agentlab_root, project_name, task_id)
    except RuntimeError as e:
        console.print(f"[yellow]Lock conflict: {e}[/yellow]")
        console.print("If this is a stale lock from a crash, run: ./agentlab.sh recover --scan")
        return

    try:
        update_heartbeat(agentlab_root, project_name, task_id)

        if output_path.exists() and not overwrite_report and not is_placeholder_report(output_path):
            raise typer.BadParameter(f"Report exists and is not a placeholder: {output_path}")

        result = run_agent_model(agentlab_root, plan, agent_name, output_path, provider, model, apply_patches=not no_apply_patches)
    except Exception:
        try:
            from state_store import mark_failed_recoverable
            mark_failed_recoverable(
                Path(plan.run_dir), project_name, task_id,
                f"{agent_name} execution interrupted. Transaction: {tx_id}.",
                failed_agent=agent_name,
            )
        except Exception:
            pass
        raise
    finally:
        if tx_id:
            try:
                release_lock(agentlab_root, project_name, task_id)
            except Exception:
                pass
    if result.status == "blocked_user_decision":
        blocked_path = Path(plan.run_dir) / f"blocked_{agent_name}.md"
        blocked_path.write_text(result.content, encoding="utf-8")
        user_decision_path = Path(plan.run_dir) / "USER_DECISION_REQUIRED.md"
        user_decision_path.write_text(result.content, encoding="utf-8")
        run_dir_path = Path(plan.run_dir)
        state = load_state(run_dir_path, project_name, task_id)
        state.status = "blocked"
        state.last_event = f"{agent_name} requires user decision."
        state.reports[f"{agent_name}_blocked"] = str(blocked_path)
        save_state(run_dir_path, state)
        from progress_tracker import load_progress, save_progress
        progress = load_progress(run_dir_path)
        if progress:
            progress["status"] = "blocked"
            progress["current_stage"] = "blocked_user_decision"
            progress["last_event"] = state.last_event
            progress["current_agent"] = None
            if agent_name in progress.get("agents", {}):
                progress["agents"][agent_name]["status"] = "blocked"
            save_progress(run_dir_path, progress)
        append_cost_ledgers(
            Path(plan.project_root),
            Path(plan.run_dir),
            usage_entry(
                project_name,
                task_id,
                agent_name,
                result.provider,
                result.model,
                result.status,
                result.input_tokens,
                result.output_tokens,
                result.total_tokens,
                result.error or "User decision required.",
            ),
        )
        console.print("[yellow]User decision required before continuing[/yellow]")
        console.print(
            {
                "blocked_report": str(blocked_path),
                "user_decision_required": str(user_decision_path),
                "usage": result.model_dump(exclude={"content"}),
            }
        )
        return
    if result.status == "fallback_handoff":
        fallback_path = Path(plan.run_dir) / f"codex_fallback_{agent_name}.md"
        fallback_path.write_text(result.content, encoding="utf-8")
        run_dir_path = Path(plan.run_dir)
        state = load_state(run_dir_path, project_name, task_id)
        state.status = "blocked"
        state.last_event = f"{agent_name} needs Codex Plus handoff."
        state.reports[f"{agent_name}_fallback"] = str(fallback_path)
        save_state(run_dir_path, state)
        from progress_tracker import load_progress, save_progress
        progress = load_progress(run_dir_path)
        if progress:
            progress["status"] = "blocked"
            progress["current_stage"] = "handoff_required"
            progress["last_event"] = state.last_event
            progress["current_agent"] = None
            if agent_name in progress.get("agents", {}):
                progress["agents"][agent_name]["status"] = "blocked"
            save_progress(run_dir_path, progress)
        append_cost_ledgers(
            Path(plan.project_root),
            Path(plan.run_dir),
            usage_entry(
                project_name,
                task_id,
                agent_name,
                result.provider,
                result.model,
                result.status,
                result.input_tokens,
                result.output_tokens,
                result.total_tokens,
                result.error or "Codex Plus handoff.",
            ),
        )
        console.print("[yellow]Codex Plus handoff written[/yellow]")
        console.print({"output": str(fallback_path), "usage": result.model_dump(exclude={"content"})})
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(result.content, encoding="utf-8")
    gate_issues = artifact_content_issues(output_path.name, result.content or "", Path(plan.run_dir))
    if gate_issues:
        block_path = write_agent_artifact_gate_block(
            Path(plan.run_dir), project_name, task_id, agent_name, output_path, gate_issues
        )
        run_dir_path = Path(plan.run_dir)
        state = load_state(run_dir_path, project_name, task_id)
        state.status = "blocked"
        state.last_event = f"{agent_name} artifact gate failed."
        state.reports[f"{agent_name}_artifact_gate"] = str(block_path)
        save_state(run_dir_path, state)
        from progress_tracker import load_progress, save_progress
        progress = load_progress(run_dir_path)
        if progress:
            progress["status"] = "blocked"
            progress["current_stage"] = "blocked"
            progress["last_event"] = state.last_event
            progress["current_agent"] = None
            if agent_name in progress.get("agents", {}):
                progress["agents"][agent_name]["status"] = "blocked"
            save_progress(run_dir_path, progress)
        append_cost_ledgers(
            Path(plan.project_root),
            Path(plan.run_dir),
            usage_entry(
                project_name,
                task_id,
                agent_name,
                result.provider,
                result.model,
                result.status,
                result.input_tokens,
                result.output_tokens,
                result.total_tokens,
                "API usage recorded before artifact gate blocked completion.",
            ),
        )
        console.print("[yellow]Artifact gate blocked completion[/yellow]")
        console.print({"output": str(output_path), "blocked_report": str(block_path), "issues": gate_issues})
        return

    state = mark_agent_completed(Path(plan.run_dir), project_name, task_id, agent_name, output_path)
    if all(agent in state.completed_agents for agent in plan.route.agents):
        state.status = "completed"
        state.last_event = "All routed agents completed."
        save_state(Path(plan.run_dir), state)
    append_cost_ledgers(
        Path(plan.project_root),
        Path(plan.run_dir),
        usage_entry(
            project_name,
            task_id,
            agent_name,
            result.provider,
            result.model,
            result.status,
            result.input_tokens,
            result.output_tokens,
            result.total_tokens,
            "API usage recorded from provider telemetry when available.",
        ),
    )

    raw_usage = result.raw_usage or {}
    if "patch_applied" in raw_usage:
        applied = raw_usage.get("patch_applied", 0)
        failed = raw_usage.get("patch_failed", 0)
        if applied > 0:
            console.print(f"[green]Patch applied:[/green] {applied} file edit(s) written to filesystem")
        if failed > 0:
            console.print(f"[yellow]Patch failures:[/yellow] {failed} edit(s) could not be applied")
        if applied == 0 and failed == 0:
            console.print("[dim]No structured edit blocks found in LLM output[/dim]")

    console.print("[green]Agent report written[/green]")
    console.print({"output": str(output_path), "usage": result.model_dump(exclude={"content"})})


@app.command("run-pipeline")
def run_pipeline(
    task_id: str = typer.Option("task_0001", help="Task run id."),
    project: Optional[str] = typer.Option(None, help="Project name."),
    execution_backend: str = typer.Option("codex", help="Pipeline backend: codex dry-run runner or langgraph."),
    budget: Optional[str] = typer.Option(None, "--budget", help="Budget mode: frugal, balanced, or max-quality."),
    dry_run: bool = typer.Option(True, help="Default dry-run, no API calls."),
    execute: bool = typer.Option(False, "--execute", help="Call real LLM APIs (not dry-run). False by default for safety."),
) -> None:
    """Run the full lifecycle pipeline. Default is dry-run with fake provider. Use --execute for real API calls."""
    ensure_safe_task_id(task_id)
    agentlab_root, project_name = runtime_context(project)

    if execution_backend in ("langgraph",):
        from langgraph_workflow import build_agentlab_graph, run_agentlab_graph
        plan = load_or_build_plan(agentlab_root, project_name, task_id, execution_backend, budget_mode=budget)
        console.print("[bold]AgentLab LangGraph Pipeline[/bold]")
        console.print(f"  Project: {project_name}")
        console.print(f"  Task: {task_id}")
        console.print(f"  Agents: {' -> '.join(plan.route.agents)}")
        console.print(f"  Run dir: {plan.run_dir}")
        try:
            app_graph = build_agentlab_graph(agentlab_root, plan)
        except RuntimeError as exc:
            console.print(f"[red]{exc}[/red]")
            return
        _final_state = run_agentlab_graph(app_graph, plan)
        run_dir = Path(plan.run_dir)
        state = load_state(run_dir, project_name, task_id)
        state.status = "complete"
        state.last_event = "LangGraph pipeline completed."
        save_state(run_dir, state)
        console.print()
        console.print("[green bold]Pipeline finished successfully.[/green bold]")
        console.print(f"  Reports: {run_dir}/")
        console.print(f"  State: {run_dir}/state.yml")
        return

    # --execute overrides --dry-run: execute mode calls real LLM APIs
    use_fake = dry_run and not execute
    if execute:
        console.print("[yellow]⚠ EXECUTE mode: real LLM API calls will be made. Token costs apply.[/yellow]")
        console.print()

    from pipeline_runner import run_full_pipeline
    result = run_full_pipeline(agentlab_root, project_name, task_id, dry_run=dry_run, fake_provider=use_fake, budget_mode=budget)
    console.print(f"\n[bold]Lifecycle Pipeline Result[/bold]")
    console.print(f"  Mode: {'execute' if not use_fake else 'dry-run'}")
    console.print(f"  Final status: {result.get('final_status', result.get('status', '?'))}")
    console.print(f"  Steps executed: {len(result.get('history', []))}")
    console.print(f"  Pipeline complete: {bool(result.get('success'))}")
    art = result.get('artifact_completeness', {})
    console.print(f"  Artifact pass_rate: {art.get('pass_rate', 'N/A')} ({art.get('artifacts_passed', 0)}/{art.get('artifacts_checked', 0)})")
    if not art.get('valid'):
        for iss in (art.get('issues') or [])[:5]:
            console.print(f"    Issue: {iss}")


@app.command("budget-eval")
def budget_eval_cmd(
    task_id: str = typer.Option("task_0001", help="Task run id used as the source request."),
    project: Optional[str] = typer.Option(None, help="Project name."),
    modes: str = typer.Option("frugal,balanced,max-quality", help="Comma-separated budget modes."),
) -> None:
    """Compare route, model, and token budget across budget modes without API calls."""
    ensure_safe_task_id(task_id)
    agentlab_root, project_name = runtime_context(project)
    selected_modes = [m.strip() for m in modes.split(",") if m.strip()]
    rows = []
    for mode in selected_modes:
        plan = build_workflow_plan(
            agentlab_root=agentlab_root,
            project_name=project_name,
            task_id=task_id,
            execution_backend="codex",
            budget_mode=mode,
        )
        total_tokens = sum(b.estimated_total_tokens for b in plan.token_budgets)
        rows.append({
            "mode": plan.budget_mode,
            "budget_profile": plan.budget_profile,
            "project_size": plan.project_size,
            "risk_level": plan.risk_level,
            "route": list(plan.route.agents),
            "estimated_tokens": total_tokens,
            "models": {
                agent: {
                    "profile": cfg.get("profile"),
                    "provider": cfg.get("provider"),
                    "model": cfg.get("model"),
                }
                for agent, cfg in plan.model_profiles.items()
            },
        })

    run_dir = agentlab_root / "projects" / project_name / "runs" / task_id
    run_dir.mkdir(parents=True, exist_ok=True)
    out_path = run_dir / "budget_eval_matrix.yml"
    out_path.write_text(
        yaml.safe_dump({"project": project_name, "task_id": task_id, "modes": rows}, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    table = Table("Mode", "Profile", "Size", "Risk", "Agents", "Est Tokens")
    for row in rows:
        table.add_row(
            row["mode"],
            row["budget_profile"],
            row["project_size"],
            row["risk_level"],
            " → ".join(row["route"]),
            str(row["estimated_tokens"]),
        )
    console.print("[bold]AgentLab budget evaluation[/bold]")
    console.print("No model calls, source edits, dependency installs, or validation commands were run.")
    console.print(table)
    console.print(f"[green]Wrote:[/green] {out_path}")


@app.command("workspace-scan")
def workspace_scan(
    task_id: str = typer.Option("task_0001", help="Task run id."),
    project: Optional[str] = typer.Option(None, help="Project name."),
    target: Path = typer.Option(..., help="Local workspace directory to scan read-only."),
    max_depth: int = typer.Option(8, help="Maximum directory depth per top-level project."),
) -> None:
    """Create project memory from a local workspace without model API calls."""
    ensure_safe_task_id(task_id)
    agentlab_root, project_name = runtime_context(project)
    from workspace_scanner import run_workspace_scan

    result = run_workspace_scan(
        agentlab_root=agentlab_root,
        project=project_name,
        task_id=task_id,
        target=target,
        max_depth=max_depth,
    )
    workspace = result["workspace"]
    artifact = result["artifact_check"]
    console.print("[bold]AgentLab workspace scan[/bold]")
    console.print("No model calls, source edits, dependency installs, or validation builds were run.")
    console.print(f"  Project: {result['project']}")
    console.print(f"  Task: {result['task_id']}")
    console.print(f"  Target: {result['target']}")
    console.print(f"  Top-level projects: {workspace['top_level_project_count']}")
    console.print(f"  Git repos: {workspace['git_repo_count']} ({workspace['dirty_git_repo_count']} dirty)")
    console.print(f"  Files counted: {workspace['file_count']}")
    console.print(f"  Size counted: {workspace['human_size']}")
    console.print(f"  Agent docs: {result['docs_dir']}")
    console.print(f"  Run dir: {result['run_dir']}")
    console.print(
        f"  Artifact pass_rate: {artifact.get('pass_rate')} "
        f"({artifact.get('artifacts_passed')}/{artifact.get('artifacts_checked')})"
    )


@app.command("performance-eval")
def performance_eval(
    task_id: str = typer.Option("task_0001", help="Task run id."),
    project: Optional[str] = typer.Option(None, help="Project name."),
) -> None:
    """Run a local deterministic AgentLab performance evaluation."""
    ensure_safe_task_id(task_id)
    agentlab_root, project_name = runtime_context(project)
    from performance_evaluator import run_performance_evaluation, REPORT

    metrics = run_performance_evaluation(agentlab_root, project_name, task_id)
    artifact = metrics.get("artifacts", {})
    console.print("[bold]AgentLab performance evaluation[/bold]")
    console.print("No model calls, source edits, dependency installs, or validation builds were run.")
    console.print(f"  Project: {project_name}")
    console.print(f"  Task: {task_id}")
    console.print(f"  Route: {metrics['route']['route_key']}")
    console.print(f"  Score: {metrics['score']['total']}/100 ({metrics['score']['grade']})")
    console.print(f"  Routing: {metrics['routing']['passed']}/{metrics['routing']['total']}")
    console.print(f"  Commands: {metrics['commands']['passed']}/{metrics['commands']['total']}")
    console.print(f"  Artifact pass_rate: {artifact.get('pass_rate')} ({artifact.get('artifacts_passed')}/{artifact.get('artifacts_checked')})")
    console.print(f"  Report: {agentlab_root / 'projects' / project_name / 'runs' / task_id / REPORT}")


@app.command("progress")
def progress(
    task_id: str = typer.Option("task_0001", help="Task run id."),
    project: Optional[str] = typer.Option(None, help="Project name."),
) -> None:
    """Show task progress from progress.yml."""
    ensure_safe_task_id(task_id)
    agentlab_root, project_name = runtime_context(project)
    run_dir = agentlab_root / "projects" / project_name / "runs" / task_id

    from progress_tracker import load_progress, progress_summary
    data = load_progress(run_dir)
    if data is None:
        console.print(f"[yellow]No progress.yml found for {project_name}/{task_id}[/yellow]")
        console.print(f"Run: ./agentlab.sh prepare --project {project_name} --task-id {task_id} --write-plan")
        return

    summary = progress_summary(data)

    console.print()
    console.print("[bold]AgentLab Progress[/bold]")
    console.print(f"  Project: [cyan]{summary['project']}[/cyan]")
    console.print(f"  Task:    [cyan]{summary['task_id']}[/cyan]")
    console.print(f"  Status:  [yellow]{summary['status']}[/yellow]")
    console.print(f"  Progress: [green]{summary['percent']}%[/green]")
    if summary.get("current_agent"):
        console.print(f"  Current: {summary['current_agent']} / {summary.get('current_stage', '?')}")
    console.print(f"  Last:    {summary.get('last_event', '-')}")
    console.print()

    table = Table("Agent", "Status", "Provider", "Tokens")
    for ag in summary.get("agents", []):
        icon = {"completed": chr(10004), "active": chr(128260), "paused": "P", "waiting": "W", "skipped": "S", "blocked": "X", "failed": "F"}.get(ag["status"], "?")
        table.add_row(ag["name"], f"{icon} {ag['status']}", ag.get("provider", "-"), str(ag.get("tokens", 0)))
    console.print(table)

    ps = summary.get("provider_status", {})
    if ps:
        console.print(f"\n[bold]Provider:[/bold] current={ps.get('current_provider', '-')}, failed={ps.get('failed_provider', '-')}, paused={ps.get('paused_for_provider', False)}")

    inc = summary.get("incidents", {})
    if inc and inc.get("open_count", 0) > 0:
        console.print(f"[yellow]Open incidents: {inc['open_count']}[/yellow]")

    resume_path = run_dir / "resume_plan.yml"
    if resume_path.exists():
        console.print(f"\n[green]Resume available:[/green] ./agentlab.sh resume --project {project_name} --task-id {task_id}")


@app.command("pause")
def pause_task(
    task_id: str = typer.Option("task_0001", help="Task run id."),
    project: Optional[str] = typer.Option(None, help="Project name."),
    reason: str = typer.Option("manual", help="Reason for pause."),
) -> None:
    """Pause a running task safely, marking state and progress."""
    ensure_safe_task_id(task_id)
    agentlab_root, project_name = runtime_context(project)
    run_dir = Path(agentlab_root / "projects" / project_name / "runs" / task_id)

    from progress_tracker import load_progress
    from state_store import load_state, save_state

    state = load_state(run_dir, project_name, task_id)
    state.status = "paused"
    state.last_event = f"Paused: {reason}"
    save_state(run_dir, state)
    console.print(f"[green]Task {task_id} paused: {reason}[/green]")

    data = load_progress(run_dir)
    if data:
        from progress_tracker import save_progress
        data["status"] = "paused"
        data["last_event"] = f"Paused: {reason}"
        data["current_stage"] = "paused"
        save_progress(run_dir, data)
        console.print("[dim]progress.yml updated[/dim]")


@app.command("resume")
def resume_task(
    task_id: str = typer.Option("task_0001", help="Task run id."),
    project: Optional[str] = typer.Option(None, help="Project name."),
    provider: Optional[str] = typer.Option(None, help="Resume with a different provider (e.g. qwen)."),
    dry_run: bool = typer.Option(True, help="Dry-run resume."),
    fake_provider: bool = typer.Option(False, help="Use fake provider."),
) -> None:
    """Resume a paused task. Optionally switch provider or use lifecycle resume."""
    ensure_safe_task_id(task_id)
    agentlab_root, project_name = runtime_context(project)
    run_dir = Path(agentlab_root / "projects" / project_name / "runs" / task_id)

    # Check for lifecycle-based resume
    from lifecycle_graph import load_lifecycle
    lc = load_lifecycle(run_dir)
    if lc:
        from pipeline_runner import resume_pipeline
        result = resume_pipeline(agentlab_root, project_name, task_id, dry_run=dry_run, fake_provider=fake_provider, simulate_provider_recovered=True)
        console.print(f"[bold]Lifecycle Resume Result[/bold]")
        console.print(f"  Status: {result.get('status', '?')}")
        console.print(f"  Message: {result.get('message', '?')}")
        if result.get('artifact_completeness'):
            art = result['artifact_completeness']
            console.print(f"  Artifact pass_rate: {art.get('pass_rate', 'N/A')}")
        return

    resume_path = run_dir / "resume_plan.yml"
    if not resume_path.exists() and not lc:
        console.print(f"[yellow]No resume plan or lifecycle found for {task_id}.[/yellow]")
        return

    plan = yaml.safe_load(resume_path.read_text(encoding="utf-8")) or {}
    console.print(f"[bold]Resume plan for {task_id}[/bold]")
    console.print(f"  Paused reason: {plan.get('paused_reason', '?')}")
    console.print(f"  Current agent: {plan.get('current_agent', '?')}")
    console.print(f"  Allowed providers: {plan.get('allowed_resume_providers', [])}")

    from state_store import load_state, save_state
    state = load_state(run_dir, project_name, task_id)
    state.status = "running"
    state.last_event = f"Resumed after pause ({plan.get('paused_reason', '?')})"
    save_state(run_dir, state)

    from progress_tracker import load_progress, save_progress
    data = load_progress(run_dir)
    if data:
        data["status"] = "running"
        data["provider_status"]["paused_for_provider"] = False
        save_progress(run_dir, data)

    console.print("[green]Task marked as resumed. Run 'run-agent' or 'run-pipeline --dry-run' to continue.[/green]")


@app.command("guard-status")
def guard_status(
    project: Optional[str] = typer.Option(None, help="Project name."),
    task_id: Optional[str] = typer.Option(None, help="Filter by task id."),
) -> None:
    """Show active and stale file locks."""
    agentlab_root, project_name = runtime_context(project)
    from guard import scan_stale_locks

    stale_results = scan_stale_locks(agentlab_root, timeout=120)
    if task_id:
        stale_results = [r for r in stale_results if task_id in r.get("lock_file", "")]

    if not stale_results:
        console.print("[green]No lock files found.[/green]")
        return

    table = Table("Project/Task", "TX ID", "Status", "Heartbeat Age", "State", "Action")
    for r in stale_results:
        lock_file = r.get("lock_file", "")
        # Extract project/task from filename like "AgentLab__task_0001.lock"
        name = Path(lock_file).stem.replace(".lock", "").replace("__", "/")
        table.add_row(
            name,
            r.get("tx_id", "?"),
            r.get("tx_status", "?"),
            f"{r.get('heartbeat_age_seconds', '?')}s" if r.get("heartbeat_age_seconds") is not None else "N/A",
            r.get("state", "?"),
            r.get("recommended_action", "?"),
        )
    console.print("\n[bold]Guard Lock Status[/bold]")
    console.print(table)
    stale_count = len([r for r in stale_results if r.get("is_stale")])
    if stale_count:
        console.print(f"\n[yellow]{stale_count} stale lock(s) can be recovered.[/yellow]")
        console.print("Run: ./agentlab.sh recover --scan to clear all stale locks")
        console.print("  or: ./agentlab.sh recover --project <project> --task-id <task_id>")


@app.command("recover")
def recover(
    task_id: Optional[str] = typer.Option(None, help="Task id to recover (clear stale lock)."),
    project: Optional[str] = typer.Option(None, help="Project name."),
    scan: bool = typer.Option(False, help="Scan and clear all stale locks across all projects."),
) -> None:
    """Recover from crashes by clearing stale file locks."""
    agentlab_root, project_name = runtime_context(project)
    from guard import scan_stale_locks, clear_stale_lock

    if scan:
        stale_results = scan_stale_locks(agentlab_root, timeout=120)
        stale = [r for r in stale_results if r.get("is_stale")]
        if not stale:
            console.print("[green]No stale locks found.[/green]")
            return

        cleared = 0
        for r in stale:
            lock_file = Path(r["lock_file"])
            lock_file.unlink(missing_ok=True)
            cleared += 1
            console.print(f"  [green]Cleared[/green] {lock_file.name}")
        console.print(f"\n[green]{cleared} stale lock(s) cleared.[/green]")
        return

    if task_id:
        ok = clear_stale_lock(agentlab_root, project_name, task_id)
        if ok:
            console.print(f"[green]Stale lock cleared for {project_name}/{task_id}.[/green]")
        else:
            console.print(f"[yellow]No stale lock found for {project_name}/{task_id}.[/yellow]")
        return

    console.print("[yellow]Specify --task-id or --scan.[/yellow]")


@app.command("providers")
def providers(
    project: Optional[str] = typer.Option(None, help="Project name."),
    task_id: Optional[str] = typer.Option(None, help="Task id for per-task incident view."),
) -> None:
    """Show configured providers and their status. Never prints API keys."""
    agentlab_root, _ = runtime_context(project)
    configs = load_agentlab_configs(agentlab_root)
    providers_config = configs.get("model_providers", {}).get("providers", {})

    table = Table("Provider", "Type", "Base URL", "API Key", "Circuit")
    from llm_provider import resolve_env_value
    for name, cfg in providers_config.items():
        key_ok = "ok" if resolve_env_value(cfg.get("api_key"), "") else "missing"
        url = resolve_env_value(cfg.get("base_url"), "-")
        if len(url) > 50:
            url = url[:47] + "..."
        table.add_row(name, cfg.get("type", ""), url, key_ok, "-")
    console.print(table)

    if task_id:
        run_dir = agentlab_root / "projects" / (project or "AgentLab") / "runs" / task_id
        from incident_manager import open_incidents
        incidents = open_incidents(run_dir)
        if incidents:
            console.print(f"\n[yellow]Open incidents for {task_id}: {len(incidents)}[/yellow]")
            for inc in incidents[:5]:
                console.print(f"  - {inc.get('at', '?')}: {inc.get('provider', '?')} {inc.get('error_class', '?')} - {inc.get('error_message', '')[:80]}")
        else:
            console.print(f"\n[green]No open incidents for {task_id}[/green]")


@app.command("chat")
def chat(
    project: Optional[str] = typer.Option(None, help="Project name."),
    task_id: Optional[str] = typer.Option(None, help="Attach to existing task."),
    new_task: bool = typer.Option(False, help="Start in new-task mode."),
    execute: bool = typer.Option(False, help="Allow API calls."),
    no_auto_sync: bool = typer.Option(False, help="Disable auto-push."),
) -> None:
    """Start Terminal chat REPL."""
    agentlab_root, project_name = runtime_context(project)
    from terminal_chat import chat_main
    chat_main(
        agentlab_root=str(agentlab_root),
        project=project_name,
        task_id=task_id,
        new_task=new_task,
        execute=execute,
        auto_sync=not no_auto_sync,
    )


@app.command("check")
def check_cmd(
    task_id: str = typer.Option("task_0001", help="Task run id."),
    project: Optional[str] = typer.Option(None, help="Project name."),
    strict: bool = typer.Option(False, help="Treat warnings as failures."),
    json_output: bool = typer.Option(False, help="Output JSON."),
) -> None:
    """Run rule-based self-check and write self_check_report.yml."""
    ensure_safe_task_id(task_id)
    agentlab_root, project_name = runtime_context(project)
    from rule_self_check import run_self_check
    report = run_self_check(agentlab_root, project_name, task_id, strict=strict)

    if json_output:
        import json
        console.print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    else:
        console.print(f"\n[bold]Self-Check:[/bold] [{'green' if report['status'] == 'pass' else 'yellow' if report['status'] == 'warn' else 'red'}]{report['status'].upper()}[/]")
        console.print(f"  Passed: {report['summary']['passed']}, Warnings: {report['summary']['warnings']}, Failed: {report['summary']['failed']}")
        for c in report.get("checks", []):
            icon = {"pass": "ok", "warn": "!", "fail": "X"}.get(c["status"], "?")
            console.print(f"  {icon} {c['id']}: {c['message'][:100]}")
        if report.get("blocking_reasons"):
            console.print(f"\n[red]Blocking:[/red]")
            for r in report["blocking_reasons"]:
                console.print(f"  - {r}")
        console.print(f"\nAuto-sync eligible: {'yes' if report.get('auto_sync_eligible') else 'no'}")
        console.print(f"Report: {agentlab_root}/projects/{project_name}/runs/{task_id}/self_check_report.yml")

    if report.get("status") == "fail":
        raise typer.Exit(code=1)


@app.command("sync")
def sync_cmd(
    task_id: str = typer.Option("task_0001", help="Task run id."),
    project: Optional[str] = typer.Option(None, help="Project name."),
    dry_run: bool = typer.Option(False, help="Preview only, no commit/push."),
    confirm: bool = typer.Option(False, help="Proceed even with warnings."),
    remote: str = typer.Option("origin", help="Git remote."),
    branch: str = typer.Option("main", help="Git branch."),
) -> None:
    """Run self-check + guarded commit + push."""
    ensure_safe_task_id(task_id)
    agentlab_root, project_name = runtime_context(project)
    from github_sync import run_sync
    report = run_sync(
        agentlab_root, project_name, task_id,
        dry_run=dry_run, confirm=confirm, remote=remote, branch=branch,
    )
    status_color = "green" if report["status"] in ("pushed", "committed_only") else "yellow"
    console.print(f"\n[bold]Sync:[/bold] [{status_color}]{report['status']}[/{status_color}]")
    if report.get("commit_sha"):
        console.print(f"  Commit: {report['commit_sha'][:12]}")
    if report.get("warnings"):
        for w in report["warnings"]:
            console.print(f"  ! {w}")
    if report.get("blocking_reasons"):
        console.print(f"[red]Blocking reasons:[/red]")
        for r in report["blocking_reasons"]:
            console.print(f"  - {r}")
    console.print(f"Report: {agentlab_root}/projects/{project_name}/runs/{task_id}/sync_report.yml")


@app.command("sync-status")
def sync_status(
    project: Optional[str] = typer.Option(None, help="Project name."),
) -> None:
    """Show project sync ledger."""
    agentlab_root, project_name = runtime_context(project)
    ledger_path = agentlab_root / "projects" / project_name / "agent_docs" / "10_SYNC_LEDGER.yml"
    if not ledger_path.exists():
        console.print("[yellow]No sync ledger found.[/yellow]")
        return
    from atomic_io import safe_read_yaml
    ledger = safe_read_yaml(ledger_path) or {}
    entries = ledger.get("entries", [])
    console.print(f"\n[bold]Sync Ledger - {project_name}[/bold]")
    console.print(f"  Total entries: {len(entries)}")
    for e in entries[-5:]:
        target = e.get("target", "github" if e.get("commit_sha") else "unknown")
        console.print(f"  {e.get('timestamp', '?')[:19]} - {target} - {e.get('task_id', '?')} - {e.get('status', '?')} - {e.get('commit_sha', '')[:12]}")


@app.command("migration-doctor")
def migration_doctor_cmd(
    project: Optional[str] = typer.Option(None, help="Project name."),
    task_id: Optional[str] = typer.Option(None, help="Optional task id for writing migration_doctor_report.yml."),
    write_report: bool = typer.Option(False, help="Write report into projects/<project>/runs/<task_id>."),
    json_output: bool = typer.Option(False, help="Output JSON."),
    no_write_probe: bool = typer.Option(False, help="Skip SMB write probe."),
) -> None:
    """Check migration readiness: env, repo, SMB, Web UI, cache, backup permissions."""
    if task_id:
        ensure_safe_task_id(task_id)
    agentlab_root, project_name = runtime_context(project)
    from migration_doctor import run_migration_doctor
    report = run_migration_doctor(
        agentlab_root,
        project_name,
        task_id=task_id,
        write_report=write_report,
        write_probe=not no_write_probe,
    )
    if json_output:
        import json
        console.print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    else:
        color = "green" if report["status"] == "pass" else "yellow" if report["status"] == "warn" else "red"
        console.print(f"\n[bold]Migration Doctor:[/bold] [{color}]{report['status'].upper()}[/{color}]")
        console.print(f"  Summary: {report.get('summary', {})}")
        table = Table("Check", "Status", "Message")
        for check in report.get("checks", []):
            table.add_row(check.get("id", ""), check.get("status", ""), check.get("message", ""))
        console.print(table)
        if report.get("blocking_reasons"):
            console.print("[red]Blocking reasons:[/red]")
            for reason in report["blocking_reasons"]:
                console.print(f"  - {reason}")
        if write_report and task_id:
            console.print(f"Report: {agentlab_root}/projects/{project_name}/runs/{task_id}/migration_doctor_report.yml")
    raise typer.Exit(code=1 if report["status"] == "fail" else 0)


@app.command("migration-init")
def migration_init_cmd(
    project: Optional[str] = typer.Option(None, help="Project name."),
    task_id: Optional[str] = typer.Option(None, help="Optional task id for migration_init_report.yml."),
    overwrite: bool = typer.Option(False, help="Overwrite existing safe helper files."),
    json_output: bool = typer.Option(False, help="Output JSON."),
) -> None:
    """Generate safe migration helper files without storing real secrets."""
    if task_id:
        ensure_safe_task_id(task_id)
    agentlab_root, project_name = runtime_context(project)
    from migration_doctor import write_migration_bootstrap
    report = write_migration_bootstrap(agentlab_root, project_name, task_id=task_id, overwrite=overwrite)
    if json_output:
        import json
        console.print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    else:
        console.print("[green]Migration bootstrap files checked.[/green]")
        console.print({"created": report.get("created", []), "skipped_existing": report.get("skipped_existing", [])})


@app.command("truenas-status")
def truenas_status_cmd(
    project: Optional[str] = typer.Option(None, help="Project name, only used to resolve root."),
    json_output: bool = typer.Option(False, help="Output JSON."),
    no_write_probe: bool = typer.Option(False, help="Skip SMB write probe."),
) -> None:
    """Check configured TrueNAS/SMB mount status."""
    agentlab_root, _ = runtime_context(project)
    from truenas_sync import get_truenas_status
    report = get_truenas_status(agentlab_root, write_probe=not no_write_probe)
    if json_output:
        import json
        console.print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    else:
        color = "green" if report["status"] == "pass" else "yellow" if report["status"] == "warn" else "red"
        console.print(f"\n[bold]TrueNAS Status:[/bold] [{color}]{report['status'].upper()}[/{color}]")
        console.print(f"  URL: {report.get('protocol_url', '')}")
        console.print(f"  Mount: {report.get('mount_path', '')}")
        console.print(f"  Mounted: {report.get('mounted', False)}")
        console.print(f"  Writable: {report.get('writable', False)}")
        console.print(f"  Free bytes: {report.get('free_bytes', 0)}")
        if report.get("probe_error"):
            console.print(f"  Probe error: {report['probe_error']}")
    raise typer.Exit(code=1 if report["status"] == "fail" else 0)


@app.command("truenas-sync")
def truenas_sync_cmd(
    task_id: str = typer.Option("task_0001", help="Task run id."),
    project: Optional[str] = typer.Option(None, help="Project name."),
    dry_run: bool = typer.Option(True, help="Preview only; --execute performs real copy."),
    execute: bool = typer.Option(False, help="Execute push-only merge copy."),
    json_output: bool = typer.Option(False, help="Output JSON."),
    no_write_probe: bool = typer.Option(False, help="Skip SMB write probe."),
) -> None:
    """Run TrueNAS/SMB push-only merge sync with manifest and checksum reports."""
    ensure_safe_task_id(task_id)
    agentlab_root, project_name = runtime_context(project)
    from truenas_sync import run_truenas_sync
    report = run_truenas_sync(
        agentlab_root,
        project_name,
        task_id,
        dry_run=dry_run,
        execute=execute,
        write_probe=not no_write_probe,
    )
    if json_output:
        import json
        console.print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    else:
        color = "green" if report["status"] in ("synced", "dry_run_completed") else "yellow" if report["status"] == "partial" else "red"
        console.print(f"\n[bold]TrueNAS Sync:[/bold] [{color}]{report['status']}[/{color}]")
        console.print(f"  Dry-run: {report.get('dry_run')}")
        console.print(f"  Would copy: {report.get('would_copy_files', 0)}")
        console.print(f"  Copied: {report.get('copied_files', 0)}")
        console.print(f"  Skipped existing: {report.get('skipped_existing', 0)}")
        console.print(f"  Failed: {report.get('failed_files', 0)}")
        for warning in report.get("warnings", [])[:10]:
            console.print(f"  ! {warning}")
        for reason in report.get("blocking_reasons", []):
            console.print(f"  - {reason}")
        console.print(f"Report: {agentlab_root}/projects/{project_name}/runs/{task_id}/truenas_sync_report.yml")
        console.print(f"Manifest: {agentlab_root}/projects/{project_name}/runs/{task_id}/truenas_manifest.yml")
    raise typer.Exit(code=1 if report["status"] in ("failed", "partial") else 0)


@app.command("backup-status")
def backup_status_cmd(
    project: Optional[str] = typer.Option(None, help="Project name."),
    task_id: Optional[str] = typer.Option(None, help="Optional task id filter."),
    json_output: bool = typer.Option(False, help="Output JSON."),
) -> None:
    """Show combined GitHub + TrueNAS backup status."""
    if task_id:
        ensure_safe_task_id(task_id)
    agentlab_root, project_name = runtime_context(project)
    from truenas_sync import build_backup_status
    report = build_backup_status(agentlab_root, project_name, task_id=task_id)
    if json_output:
        import json
        console.print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    else:
        console.print(f"\n[bold]Backup Status - {project_name}[/bold]")
        console.print(f"  Overall: {report.get('status')}")
        github = report.get("github", {})
        truenas = report.get("truenas", {})
        tn_status = truenas.get("status", {})
        console.print(f"  GitHub: enabled={github.get('enabled')} token={github.get('token_configured')} latest={github.get('latest', {}).get('status', '-')}")
        console.print(f"  TrueNAS: status={tn_status.get('status')} mounted={tn_status.get('mounted')} writable={tn_status.get('writable')}")
        console.print(f"  Ledger entries: {report.get('ledger', {}).get('entries_count', 0)}")


@app.command("provider-test")
def provider_test(
    provider: str = typer.Option("deepseek", help="Provider key to test."),
    dry_run: bool = typer.Option(True, help="Dry-run: check config only. --no-dry-run to execute."),
) -> None:
    """Test a provider's configuration and reachability."""
    agentlab_root, _ = runtime_context(None)
    configs = load_agentlab_configs(agentlab_root)
    model_providers_config = configs.get("model_providers", {})
    providers_config = model_providers_config.get("providers", {})
    cfg = providers_config.get(provider, {})

    if not cfg:
        console.print(f"[red]Provider '{provider}' not found in model_providers.yml[/red]")
        return

    from llm_provider import resolve_env_value
    api_key = resolve_env_value(cfg.get("api_key"), "")
    base_url = resolve_env_value(cfg.get("base_url"), "")
    model = resolve_env_value(cfg.get("default_model"), "")

    console.print(f"[bold]Provider: {provider}[/bold]")
    console.print(f"  Type: {cfg.get('type')}")
    console.print(f"  Base URL: {base_url}")
    console.print(f"  Model: {model}")
    console.print(f"  API Key configured: {'yes' if api_key else '[red]no[/red]'}")

    if dry_run:
        console.print("[yellow]Dry-run only. Use --no-dry-run to test with a real API call.[/yellow]")
        return

    if not api_key:
        console.print("[red]Cannot test - no API key configured.[/red]")
        return

    from llm_provider import generate_text
    from schemas import LLMSettings
    test_settings = LLMSettings(
        provider=provider,
        provider_type=cfg.get("type", "openai_compatible"),
        model=model,
        base_url=base_url,
        api_key_configured=True,
        max_output_tokens=32,
    )
    messages = [{"role": "user", "content": "Reply with exactly the single word: OK"}]
    try:
        result = generate_text(test_settings, model_providers_config, messages)
        if result.status == "completed":
            content = (result.content or "").strip()
            if content:
                console.print(f"[green]ok Provider {provider} responded: {content[:100]}[/green]")
            else:
                console.print(f"[yellow]Provider {provider} connected but returned empty content.[/yellow]")
        else:
            console.print(f"[yellow]Provider returned status: {result.status}[/yellow]")
            console.print(result.error or "no error details")
    except Exception as e:
        console.print(f"[red]X Provider {provider} failed: {e}[/red]")


# Task Discovery & Resume Index Commands

@app.command("task-index")
def task_index_cmd(
    project: Optional[str] = typer.Option(None, help="Project name."),
    rebuild: bool = typer.Option(False, help="Full rebuild of index and per-task artifacts."),
) -> None:
    """Build or rebuild the project task discovery index."""
    agentlab_root, project_name = runtime_context(project)
    from task_index import rebuild_index, build_project_task_index, save_project_task_index, sync_task_ledger

    if rebuild:
        index = rebuild_index(agentlab_root, project_name)
        console.print(f"[green]Full rebuild complete.[/green]")
    else:
        index = build_project_task_index(agentlab_root, project_name)
        save_project_task_index(agentlab_root, project_name, index)
        sync_task_ledger(agentlab_root, project_name, index)
        console.print(f"[green]Index updated.[/green]")

    tasks = index.get("tasks", [])
    status_counts = {}
    for t in tasks:
        s = t.get("status", "unknown")
        status_counts[s] = status_counts.get(s, 0) + 1

    console.print(f"\n[bold]Indexed {len(tasks)} tasks.[/bold]")
    for status, count in sorted(status_counts.items()):
        console.print(f"  {status}: {count}")
    console.print(f"Index: {agentlab_root}/projects/{project_name}/task_index.yml")
    console.print(f"Ledger: {agentlab_root}/projects/{project_name}/agent_docs/02_TASK_LEDGER.yml")


@app.command("task-find")
def task_find_cmd(
    query: str = typer.Argument(..., help="Search query (English and/or Chinese)."),
    project: Optional[str] = typer.Option(None, help="Project name."),
    status: Optional[str] = typer.Option(None, help="Comma-separated status filter (paused,blocked,completed)."),
    limit: int = typer.Option(10, help="Max results."),
) -> None:
    """Find tasks by natural-language query."""
    agentlab_root, project_name = runtime_context(project)
    from task_index import ensure_project_task_index
    from task_search import search_tasks
    from task_card import render_task_results_rich

    index = ensure_project_task_index(agentlab_root, project_name)
    status_list = [s.strip() for s in status.split(",") if s.strip()] if status else None
    results = search_tasks(index, query, status_filter=status_list, limit=limit, agentlab_root=agentlab_root)
    render_task_results_rich(results)


@app.command("task-open")
def task_open_cmd(
    task_id: str = typer.Argument(..., help="Task ID to open."),
    project: Optional[str] = typer.Option(None, help="Project name."),
) -> None:
    """Display a task card with full details."""
    agentlab_root, project_name = runtime_context(project)
    from task_index import ensure_project_task_index
    from task_card import render_task_card_rich

    index = ensure_project_task_index(agentlab_root, project_name)
    record = None
    for t in index.get("tasks", []):
        if t.get("task_id") == task_id:
            record = t
            break
    if record:
        render_task_card_rich(record)
    else:
        console.print(f"[yellow]Task '{task_id}' not found in index.[/yellow]")


@app.command("task-resume-candidates")
def task_resume_candidates_cmd(
    project: Optional[str] = typer.Option(None, help="Project name."),
) -> None:
    """List all recoverable tasks that can be resumed."""
    agentlab_root, project_name = runtime_context(project)
    from task_index import ensure_project_task_index
    from task_card import render_resume_candidates_rich

    index = ensure_project_task_index(agentlab_root, project_name)
    tasks = index.get("tasks", [])
    render_resume_candidates_rich(tasks)


@app.command("task-map")
def task_map_cmd(
    project: Optional[str] = typer.Option(None, help="Project name."),
) -> None:
    """Show project task overview grouped by status."""
    agentlab_root, project_name = runtime_context(project)
    from task_index import ensure_project_task_index
    from rich.console import Console

    index = ensure_project_task_index(agentlab_root, project_name)
    tasks = index.get("tasks", [])

    grouped: dict[str, list[dict]] = {}
    for t in tasks:
        status = t.get("status", "unknown")
        grouped.setdefault(status, []).append(t)

    console = Console()
    console.print(f"\n[bold]AgentLab Task Map -- {project_name}[/bold]\n")

    order = ["running", "paused", "recoverable", "blocked", "completed", "failed", "archived", "unknown"]
    for status in order:
        items = grouped.get(status, [])
        if not items:
            continue
        console.print(f"[bold]{status.title()}:[/bold]")
        for t in items[:20]:
            pct = t.get("percent_complete", 0)
            console.print(f"  - {t['task_id']}  {pct}%  {t.get('title', '')[:50]}")
        if len(items) > 20:
            console.print(f"  ... and {len(items) - 20} more")
        console.print()


@app.command("task-artifacts")
def task_artifacts_cmd(
    task_id: str = typer.Argument(..., help="Task ID."),
    project: Optional[str] = typer.Option(None, help="Project name."),
) -> None:
    """Display the artifact manifest for a task."""
    agentlab_root, project_name = runtime_context(project)
    from task_index import run_dir_for_task, build_artifact_manifest
    from task_card import render_artifact_manifest_text

    run_dir = run_dir_for_task(agentlab_root, project_name, task_id)
    manifest = build_artifact_manifest(run_dir)
    text = render_artifact_manifest_text(manifest)
    console.print(text)


# Lifecycle & Artifact Commands

@app.command("lifecycle-status")
def lifecycle_status_cmd(
    task_id: str = typer.Option("task_0001", help="Task run id."),
    project: Optional[str] = typer.Option(None, help="Project name."),
) -> None:
    """Show lifecycle state for a task."""
    agentlab_root, project_name = runtime_context(project)
    run_dir = agentlab_root / "projects" / project_name / "runs" / task_id
    from lifecycle_graph import load_lifecycle, next_node, validate_lifecycle, lifecycle_summary

    lc = load_lifecycle(run_dir)
    if not lc:
        console.print("[yellow]No lifecycle.yml found for this task.[/yellow]")
        console.print("Run 'run-pipeline --dry-run' to create one.")
        return

    validation = validate_lifecycle(run_dir)
    next_n = next_node(run_dir)

    console.print(f"\n[bold]Lifecycle Status: {task_id}[/bold]")
    console.print(f"  Next node: {next_n or 'all completed'}")
    console.print(f"  Validation: {'PASS' if validation['valid'] else 'FAIL'}")
    console.print(f"  Completed: {validation['completed_count']}/{validation['node_count']}")
    console.print(f"  Skipped: {validation['skipped_count']}")
    console.print()
    console.print(lifecycle_summary(run_dir))


@app.command("artifact-check")
def artifact_check_cmd(
    task_id: str = typer.Option("task_0001", help="Task run id."),
    project: Optional[str] = typer.Option(None, help="Project name."),
) -> None:
    """Validate all artifacts for a task."""
    agentlab_root, project_name = runtime_context(project)
    run_dir = agentlab_root / "projects" / project_name / "runs" / task_id
    from artifact_contract import validate_artifacts, write_artifact_manifest

    result = validate_artifacts(run_dir)
    write_artifact_manifest(run_dir, result)

    status = "PASS" if result['valid'] else "FAIL"
    console.print(f"\n[bold]Artifact Check: {task_id} - [{status}][/bold]")
    console.print(f"  Pass rate: {result['pass_rate']} ({result['artifacts_passed']}/{result['artifacts_checked']})")
    if result.get('issues'):
        console.print(f"  Issues ({result['issues_count']}):")
        for iss in result['issues'][:10]:
            console.print(f"    - {iss.get('file', '?')}: {iss.get('issue', '?')}")
    console.print(f"  Manifest: {run_dir}/artifact_manifest.yml")


@app.command("run-next")
def run_next_cmd(
    task_id: str = typer.Option("task_0001", help="Task run id."),
    project: Optional[str] = typer.Option(None, help="Project name."),
    dry_run: bool = typer.Option(True, help="Default dry-run."),
) -> None:
    """Run the next lifecycle node."""
    agentlab_root, project_name = runtime_context(project)
    from pipeline_runner import run_next_node
    result = run_next_node(agentlab_root, project_name, task_id, fake_provider=dry_run)
    console.print(f"\n[bold]Next Node Result[/bold]")
    console.print(f"  Node: {result.get('node', '?')}")
    console.print(f"  Status: {result.get('status', '?')}")
    console.print(f"  Message: {result.get('message', '?')}")
    if result.get('resume_command'):
        console.print(f"  Resume: {result['resume_command']}")


@app.command("doctor")
def doctor(
    project: Optional[str] = typer.Option(None, help="Project name."),
    json_output: bool = typer.Option(False, help="Output JSON."),
) -> None:
    """AgentLab system health check."""
    import subprocess
    import sys
    agentlab_root, _ = runtime_context(project)
    results = []
    exit_code = 0

    # 1. Python version
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if sys.version_info >= (3, 10):
        results.append(("Python version", "PASS", py_ver))
    else:
        results.append(("Python version", "FAIL", f"{py_ver} < 3.10"))
        exit_code = 1

    # 2. bash syntax
    bash_path = agentlab_root / "agentlab.sh"
    try:
        subprocess.run(["bash", "-n", str(bash_path)], capture_output=True, check=True)
        results.append(("bash syntax", "PASS", str(bash_path)))
    except subprocess.CalledProcessError:
        results.append(("bash syntax", "FAIL", "agentlab.sh syntax error"))
        exit_code = 1

    # 3. py_compile agentlab_app.py
    try:
        subprocess.run(
            [sys.executable, "-m", "py_compile", str(agentlab_root / "agentlab_app.py")],
            capture_output=True, check=True,
        )
        results.append(("py_compile agentlab_app", "PASS", ""))
    except subprocess.CalledProcessError as e:
        results.append(("py_compile agentlab_app", "FAIL", e.stderr.decode()[:100]))
        exit_code = 1

    # 4. py_compile agent_runtime/*.py
    runtime_dir = agentlab_root / "agent_runtime"
    runtime_failed = []
    for f in sorted(runtime_dir.glob("*.py")):
        try:
            subprocess.run(
                [sys.executable, "-m", "py_compile", str(f)],
                capture_output=True, check=True,
            )
        except subprocess.CalledProcessError:
            runtime_failed.append(f.name)
    if runtime_failed:
        results.append(("py_compile runtime", "FAIL", ", ".join(runtime_failed)))
        exit_code = 1
    else:
        results.append(("py_compile runtime", "PASS", "41 files"))

    # 5. py_compile web_ui/server.py
    ui_server = agentlab_root / "web_ui" / "server.py"
    if ui_server.exists():
        try:
            subprocess.run(
                [sys.executable, "-m", "py_compile", str(ui_server)],
                capture_output=True, check=True,
            )
            results.append(("py_compile web_ui", "PASS", ""))
        except subprocess.CalledProcessError as e:
            results.append(("py_compile web_ui", "FAIL", e.stderr.decode()[:100]))
            exit_code = 1

    # 6. YAML parse check
    config_dir = agentlab_root / "config"
    yaml_failed = []
    for f in sorted(config_dir.glob("*.yml")):
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8"))
            if data is None:
                yaml_failed.append(f"{f.name} (empty)")
        except Exception as e:
            yaml_failed.append(f"{f.name} ({e})")
    if yaml_failed:
        results.append(("config parse", "FAIL", ", ".join(yaml_failed)))
        exit_code = 1
    else:
        results.append(("config parse", "PASS", ""))

    # 7. Required directories
    dirs = ["agent_runtime", "agent_templates", "config", "projects", "web_ui"]
    for d in dirs:
        p = agentlab_root / d
        results.append((f"dir {d}", "PASS" if p.is_dir() else "FAIL", str(p)))
        if not p.is_dir():
            exit_code = 1

    # 8. Required Web UI files
    ui_files = ["index.html", "app.js", "styles.css", "server.py"]
    for f in ui_files:
        p = agentlab_root / "web_ui" / f
        results.append((f"ui file {f}", "PASS" if p.exists() else "FAIL", str(p)))
        if not p.exists():
            exit_code = 1

    # 9. Artifact contract load
    try:
        from artifact_contract import REQUIRED_ARTIFACTS_BY_ROUTE, COMMON_ARTIFACTS
        total_artifacts = len(COMMON_ARTIFACTS) + len(set(
            a for v in REQUIRED_ARTIFACTS_BY_ROUTE.values() for a in v
        ))
        results.append(("artifact contract", "PASS", f"{total_artifacts} artifacts defined"))
    except Exception as e:
        results.append(("artifact contract", "FAIL", str(e)))
        exit_code = 1

    # 10. API key check (warn only)
    from llm_provider import resolve_env_value
    import os as _os
    load_dotenv()
    keys_found = 0
    keys_total = 0
    for var in ["DEEPSEEK_API_KEY", "DASHSCOPE_API_KEY"]:
        keys_total += 1
        if _os.getenv(var):
            keys_found += 1
    if keys_found == 0:
        results.append(("API keys", "WARN", "no API keys configured"))
    else:
        results.append(("API keys", "PASS", f"{keys_found}/{keys_total} configured"))

    if json_output:
        import json
        out = {
            "status": "pass" if exit_code == 0 else "fail",
            "checks": [
                {"id": r[0], "status": r[1].lower(), "message": r[2]}
                for r in results
            ],
        }
        console.print(json.dumps(out, indent=2, ensure_ascii=False))
    else:
        for name, status, detail in results:
            icon = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}.get(status, "❓")
            console.print(f"{icon} {status:5s} {name}: {detail}")
        console.print()
        if exit_code == 0:
            console.print("[green]All checks passed.[/green]")
        else:
            console.print("[red]Some checks failed.[/red]")

    raise typer.Exit(code=exit_code)


@app.command("codex-start")
def codex_start_cmd(
    task_id: str = typer.Option("task_0001", help="Task run id."),
    project: Optional[str] = typer.Option(None, help="Project name."),
    request_file: Optional[Path] = typer.Option(None, help="Optional request file."),
    mode: str = typer.Option("full-driver", help="Codex execution mode label."),
) -> None:
    """Show Codex full-driver start context without making model calls."""
    agentlab_root, project_name = runtime_context(project)
    console.print(f"[bold]Codex Full-Driver: {task_id}[/bold]")
    console.print(f"  Project: {project_name}")
    console.print(f"  Mode: {mode}")
    console.print(f"  Request file: {request_file or '(none)'}")
    console.print(f"  Run dir: {agentlab_root}/projects/{project_name}/runs/{task_id}")
    console.print()
    console.print("[green]Task context ready. Continue with prepare, run-pipeline, check, and handoff.[/green]")


@app.command("codex-status")
def codex_status_cmd(
    task_id: str = typer.Option("task_0001", help="Task run id."),
    project: Optional[str] = typer.Option(None, help="Project name."),
) -> None:
    """Show Codex task state using the normal AgentLab state store."""
    agentlab_root, project_name = runtime_context(project)
    run_dir = agentlab_root / "projects" / project_name / "runs" / task_id
    state = load_state(run_dir, project_name, task_id)
    console.print(f"[bold]Codex Task Status: {task_id}[/bold]")
    console.print(f"  Project: {project_name}")
    console.print(f"  Status: {state.status}")
    console.print(f"  Execution mode: {state.execution_mode or 'codex_full_driver'}")
    console.print(f"  Current agent: {state.current_agent}")
    console.print(f"  Completed agents: {state.completed_agents}")
    console.print(f"  Blocked: {state.blocked}")


@app.command("codex-handoff")
def codex_handoff_cmd(
    task_id: str = typer.Option("task_0001", help="Task run id."),
    project: Optional[str] = typer.Option(None, help="Project name."),
) -> None:
    """Write a machine-readable Codex handoff packet."""
    agentlab_root, project_name = runtime_context(project)
    from handoff_builder import build_handoff_packet, write_handoff_packet

    project_root = agentlab_root / "projects" / project_name
    packet = build_handoff_packet(project_root, task_id)
    path = write_handoff_packet(project_root, task_id, packet)
    console.print(f"[green]Handoff packet written:[/green] {path}")
    console.print(f"  Status: {packet['status']}")
    console.print(f"  Last agent: {packet['last_completed_agent']}")
    console.print(f"  Next agent: {packet['next_agent']}")


@app.command("codex-resume")
def codex_resume_cmd(
    task_id: str = typer.Option("task_0001", help="Task run id."),
    project: Optional[str] = typer.Option(None, help="Project name."),
    from_file: str = typer.Option("handoff_packet.yml", "--from", help="Handoff packet filename."),
) -> None:
    """Print Codex/API resume instructions from a handoff packet."""
    agentlab_root, project_name = runtime_context(project)
    from api_continuation import load_handoff_packet

    project_root = agentlab_root / "projects" / project_name
    handoff = load_handoff_packet(project_root, task_id)
    if handoff is None:
        console.print(f"[red]No handoff packet found for {task_id}[/red]")
        raise typer.Exit(code=1)

    console.print(f"[bold]Resume: {task_id}[/bold]")
    console.print(f"  Status: {handoff['status']}")
    console.print(f"  Next agent: {handoff['next_agent']}")
    console.print(f"  Resume available: {handoff['resume_available']}")
    console.print()
    console.print("[green]To continue with API agents:[/green]")
    console.print(
        f"  ./agentlab.sh continue-with-api --project {project_name} "
        f"--task-id {task_id} --from {from_file}"
    )
    console.print()
    console.print("[green]To continue manually:[/green]")
    console.print(f"  Read {project_root}/runs/{task_id}/handoff_packet.yml")


@app.command("codex-verify-artifacts")
def codex_verify_artifacts_cmd(
    task_id: str = typer.Option("task_0001", help="Task run id."),
    project: Optional[str] = typer.Option(None, help="Project name."),
) -> None:
    """Validate Codex/lifecycle closure artifacts for a task."""
    agentlab_root, project_name = runtime_context(project)
    from codex_artifact_validator import validate_artifacts, print_validation_report

    project_root = agentlab_root / "projects" / project_name
    result = validate_artifacts(project_root, task_id)
    print_validation_report(result)
    if result.get("result") != "pass":
        raise typer.Exit(code=1)


@app.command("continue-with-api")
def continue_with_api_cmd(
    task_id: str = typer.Option("task_0001", help="Task run id."),
    project: Optional[str] = typer.Option(None, help="Project name."),
    from_file: str = typer.Option("handoff_packet.yml", "--from", help="Handoff packet filename."),
    execute: bool = typer.Option(False, help="Allow real API continuation. Defaults to dry-run."),
) -> None:
    """Continue from a handoff packet using API agents or dry-run preview."""
    agentlab_root, project_name = runtime_context(project)
    from api_continuation import continue_with_api, print_continuation_plan

    project_root = agentlab_root / "projects" / project_name
    _ = from_file
    result = continue_with_api(project_root, task_id, dry_run=not execute)
    print_continuation_plan(result)


if __name__ == "__main__":
    app()
