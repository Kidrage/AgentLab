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
from brain_governor import evaluate_token_status, request_coder_quota_decision, request_traversal_decision
from config_loader import load_agentlab_configs
from cost_tracker import append_cost_ledgers, usage_entry
from policies import assert_path_allowed, ensure_safe_task_id, resolve_agentlab_root
from schemas import TaskRunRequest
from state_store import load_state, mark_agent_completed, mark_planned, save_state, utc_now
from workflow_plan import build_workflow_plan

app = typer.Typer(help="AgentLab local-first CLI.", no_args_is_help=True)
console = Console()


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
    docs = project_root / "agent_docs"
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
):
    plan_path = agentlab_root / "projects" / project_name / "runs" / task_id / "workflow_plan.yml"
    if plan_path.exists() and user_request is None:
        data = yaml.safe_load(plan_path.read_text(encoding="utf-8")) or {}
        from schemas import WorkflowPlan

        return WorkflowPlan(**data)
    return build_workflow_plan(
        agentlab_root=agentlab_root,
        project_name=project_name,
        task_id=task_id,
        execution_backend=execution_backend,
        user_request_path=user_request,
    )


@app.command("init-task")
def init_task(
    task_id: str = typer.Option("task_0001", help="Task run id, such as task_0001."),
    project: Optional[str] = typer.Option(None, help="Project name. Defaults to DEFAULT_PROJECT."),
    request_text: str = typer.Option("", help="Optional user request text to seed user_request.md."),
    request_file: Optional[Path] = typer.Option(None, help="Optional file to copy into user_request.md."),
) -> None:
    """Create a task folder and safe placeholder files without overwriting."""
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
        "supervisor_plan.md": "# Supervisor Plan\n\nTBD\n",
        "reposcout_report.md": "# RepoScout Report\n\nTBD\n",
        "research_notes.md": "# Research Notes\n\nTBD\n",
        "interface_map.md": "# Interface Map\n\nTBD\n",
        "implementation_report.md": "# Implementation Report\n\nTBD\n",
        "validation_report.md": "# Validation Report\n\nTBD\n",
        "audit_report.md": "# Audit Report\n\nTBD\n",
        "archive_update.md": "# Archive Update\n\nTBD\n",
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

    # Apply filters
    if status_filter:
        tasks = [t for t in tasks if t.get("status") == status_filter]
    if priority_filter:
        tasks = [t for t in tasks if t.get("priority") == priority_filter]
    if category_filter:
        tasks = [t for t in tasks if t.get("category") == category_filter]
    if show_blocked:
        tasks = [t for t in tasks if t.get("status") == "blocked"]

    # Sort by priority (P0 first), then depends_on count
    def sort_key(t):
        prio_order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
        status_order = {"blocked": 0, "pending": 1, "active": 2, "complete": 3, "archived": 4}
        return (prio_order.get(t.get("priority", "P2"), 2), status_order.get(t.get("status", "pending"), 1))

    tasks.sort(key=sort_key)

    # Summary stats
    counts: dict[str, int] = defaultdict(int)
    for t in tasks:
        counts[t.get("status", "unknown")] += 1

    console.print(f"\n[bold]Task Ledger — {project_name}[/bold]")
    console.print(f"  Total: {len(tasks)} | "
                  f"Pending: {counts.get('pending', 0)} | "
                  f"Active: {counts.get('active', 0)} | "
                  f"Blocked: {counts.get('blocked', 0)} | "
                  f"Complete: {counts.get('complete', 0)}\n")

    table = Table("ID", "Status", "Pri", "Cat", "Title", "Depends On", "Blocked Reason")
    for t in tasks:
        status_icon = {
            "pending": "⏳",
            "active": "🔄",
            "blocked": "🚫",
            "complete": "✅",
            "archived": "📦",
        }.get(t.get("status", ""), "❓")

        deps = t.get("depends_on") or []
        dep_str = ", ".join(deps) if deps else "—"
        blocked = t.get("blocked_reason") or "—"
        if len(blocked) > 40:
            blocked = blocked[:37] + "..."

        table.add_row(
            t.get("task_id", ""),
            f"{status_icon} {t.get('status', '')}",
            t.get("priority", ""),
            t.get("category", ""),
            t.get("title", ""),
            dep_str,
            blocked,
        )
    console.print(table)

    # Next-action recommendation
    next_tasks = [t for t in tasks if t.get("status") in ("pending",) and not (t.get("depends_on") or [])]
    if next_tasks:
        next_task = next_tasks[0]
        console.print(f"\n[green]Recommended next: {next_task['task_id']} — {next_task['title']} (priority={next_task.get('priority', '?')})[/green]")
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


@app.command("policy-status")
def policy_status(
    project: Optional[str] = typer.Option(None, help="Project name."),
) -> None:
    """Show hard AgentLab execution policy for brain and coder stages."""
    agentlab_root, _ = runtime_context(project)
    configs = load_agentlab_configs(agentlab_root)
    execution_policy = configs.get("execution_policy", {})
    brain_policy = execution_policy.get("brain_policy", {})
    coder_policy = execution_policy.get("coder_policy", {})
    providers = configs.get("model_providers", {}).get("providers", {})

    from llm_provider import resolve_env_value

    deepseek = providers.get(brain_policy.get("required_provider", "deepseek"), {})
    api_key_configured = bool(resolve_env_value(deepseek.get("api_key"), ""))

    console.print("[bold]AgentLab execution policy[/bold]")
    console.print(
        {
            "brain_required_provider": brain_policy.get("required_provider", "deepseek"),
            "deepseek_required_for_all_agentlab_tasks": brain_policy.get(
                "deepseek_required_for_all_agentlab_tasks", False
            ),
            "codex_may_simulate_brain": brain_policy.get("codex_may_simulate_brain", False),
            "deepseek_api_key_configured": api_key_configured,
            "coder_primary_executor": coder_policy.get("primary_executor", "codex_plus_manual"),
            "coder_api_fallback_executor": coder_policy.get("api_fallback_executor", ""),
            "coder_api_fallback_profile": coder_policy.get("api_fallback_model_profile", ""),
            "automatic_patch_application": coder_policy.get("automatic_patch_application", False),
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

    timestamp = utc_now()
    dev_log = project_root / "agent_docs" / "07_DEVELOPMENT_LOG.md"
    dialogue_log = project_root / "agent_docs" / "08_CODEX_DIALOGUE_LOG.md"

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

    agent_table = Table("Agent", "Profile", "Provider", "Model", "Max Output")
    for agent_name in registry:
        settings, _ = resolve_agent_settings(agentlab_root, agent_name)
        agent_table.add_row(
            agent_name,
            settings.profile_name,
            settings.provider,
            settings.model,
            str(settings.max_output_tokens),
        )
    console.print(agent_table)


@app.command("run-agent")
def run_agent(
    agent_name: str = typer.Argument(..., help="Agent name, e.g. Supervisor or Coder."),
    task_id: str = typer.Option("task_0001", help="Task run id."),
    project: Optional[str] = typer.Option(None, help="Project name."),
    execution_backend: str = typer.Option("codex", help="Coder backend recorded in the workflow plan."),
    provider: Optional[str] = typer.Option(None, help="Override provider, e.g. deepseek or openai."),
    model: Optional[str] = typer.Option(None, help="Override model id for this run."),
    output: Optional[Path] = typer.Option(None, help="Optional report output path, relative to run dir unless absolute."),
    execute: bool = typer.Option(False, help="Actually call the configured model API. Default is dry-run."),
    overwrite_report: bool = typer.Option(False, help="Overwrite an existing non-placeholder report."),
    force: bool = typer.Option(False, help="Allow running an agent not present in the selected route."),
) -> None:
    """Dry-run or execute a single agent and write its report."""
    ensure_safe_task_id(task_id)
    agentlab_root, project_name = runtime_context(project)
    plan = load_or_build_plan(agentlab_root, project_name, task_id, execution_backend)
    if agent_name not in plan.route.agents and not force:
        raise typer.BadParameter(f"{agent_name} is not in route {plan.route.agents}. Use --force to override.")

    output_path = assert_path_allowed(report_path_for_agent(plan, agent_name, output), agentlab_root)
    settings, _ = resolve_agent_settings(agentlab_root, agent_name, provider, model)
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
        }
    )

    if not execute:
        console.print("[yellow]Dry run only. No model API call was made.[/yellow]")
        console.print("[bold]Prompt preview[/bold]")
        console.print(messages[0]["content"][:1800])
        return

    if output_path.exists() and not overwrite_report and not is_placeholder_report(output_path):
        raise typer.BadParameter(f"Report exists and is not a placeholder: {output_path}")

    result = run_agent_model(agentlab_root, plan, agent_name, output_path, provider, model)
    if result.status == "blocked_user_decision":
        blocked_path = Path(plan.run_dir) / f"blocked_{agent_name}.md"
        blocked_path.write_text(result.content, encoding="utf-8")
        user_decision_path = Path(plan.run_dir) / "USER_DECISION_REQUIRED.md"
        user_decision_path.write_text(result.content, encoding="utf-8")
        state = load_state(Path(plan.run_dir), project_name, task_id)
        state.status = "blocked"
        state.last_event = f"{agent_name} requires user decision before fallback or retry."
        state.reports[f"{agent_name}_blocked"] = str(blocked_path)
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
        state = load_state(Path(plan.run_dir), project_name, task_id)
        state.status = "blocked"
        state.last_event = f"{agent_name} needs Codex Plus handoff."
        state.reports[f"{agent_name}_fallback"] = str(fallback_path)
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
                result.error or "Codex Plus handoff.",
            ),
        )
        console.print("[yellow]Codex Plus handoff written[/yellow]")
        console.print({"output": str(fallback_path), "usage": result.model_dump(exclude={"content"})})
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(result.content, encoding="utf-8")
    mark_agent_completed(Path(plan.run_dir), project_name, task_id, agent_name, output_path)
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
    console.print("[green]Agent report written[/green]")
    console.print({"output": str(output_path), "usage": result.model_dump(exclude={"content"})})


if __name__ == "__main__":
    app()
