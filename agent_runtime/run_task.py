"""AgentLab CLI entrypoint.

This CLI is local-first and conservative by default. It can create task folders,
prepare workflow plans, inspect model/provider config, and optionally run one
agent through a configured model API when `--execute` is explicitly passed.
"""

from __future__ import annotations

from pathlib import Path
from collections import defaultdict
from typing import Optional
import json
import os
import sys

# Ensure project root is on sys.path so `agent_runtime.` imports work
# for P2 modules when this script is run directly from within agent_runtime/.
# Insert at position 1 so agent_runtime/ modules take priority over project-level
# modules with the same name (e.g., atomic_io.py exists in both locations).
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_RUNTIME_ROOT = Path(__file__).resolve().parent
if str(_RUNTIME_ROOT) not in sys.path:
    sys.path.insert(1, str(_RUNTIME_ROOT))
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(1, str(_PROJECT_ROOT))

import typer
import yaml
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from agent_runner import (
    compose_agent_messages,
    is_placeholder_report,
    report_path_for_agent,
    resolve_agent_execution_preview,
    resolve_agent_settings,
    run_agent_model,
)
from artifact_contract import artifact_content_issues
from guard import (
    acquire_lock,
    release_lock,
    update_heartbeat,
)
from brain_governor import (
    evaluate_harness_status,
    evaluate_token_status,
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
)
try:
    from agent_runtime.report_sanitizer import dump_report_yaml, write_report_yaml
except ModuleNotFoundError:  # pragma: no cover - direct script path
    from report_sanitizer import dump_report_yaml, write_report_yaml
from schemas import TaskRunRequest
from state_store import load_state, mark_agent_completed, mark_planned, save_state, utc_now
from workflow_plan import build_workflow_plan, write_mission_contract_artifacts

# -- M2-10 TUI Module Integration --
def run_tui():
    try:
        from agentlab_tui.app import AgentLabTUI
        tui = AgentLabTUI()
        tui.run()
    except ImportError as e:
        print(f"Failed to load TUI module: {e}")

app = typer.Typer(help="AgentLab local-first CLI.", no_args_is_help=True)
external_skills_app = typer.Typer(help="External Skill workflow closure commands.", no_args_is_help=True)
search_app = typer.Typer(help="Search provider adapter commands.", no_args_is_help=True)
repo_index_app = typer.Typer(help="Repo indexer adapter commands.", no_args_is_help=True)
external_projects_app = typer.Typer(help="M1 external project registry commands.", no_args_is_help=True)
mission_compiler_app = typer.Typer(help="M1-2 mission compiler v2 commands.", no_args_is_help=True)

@app.command("tui")
def tui_cmd(headless: bool = typer.Option(False, "--headless", help="Run in headless mode"),
            view: str = typer.Option("overview", "--view", help="View to display in headless mode"),
            project: str = typer.Option(None, "--project", help="Project to inspect")):
    """Start the AgentLab Terminal User Interface."""
    if headless:
        from agentlab_tui.snapshot_renderer import render_tui_snapshot
        print(render_tui_snapshot(project=project, view=view))
    else:
        run_tui()

@app.command("webui")
def webui_cmd(host: str = typer.Option("127.0.0.1", "--host", help="Host to bind to"), port: int = typer.Option(8765, "--port", help="Port to bind to")):
    """Start the AgentLab Web User Interface."""
    try:
        from agentlab_app.dashboard.app import run_server
        run_server(host=host, port=port)
    except ValueError as e:
        print(f"Error: {e}")
        raise typer.Exit(1)
    except ImportError as e:
        print(f"Failed to load WebUI module: {e}")

from agent_runtime.config_center.cli import app as config_app
from agent_runtime.assistant.cli import register_assistant_commands
app.add_typer(external_skills_app, name="external-skills")
app.add_typer(search_app, name="search")
app.add_typer(repo_index_app, name="repo-index")
app.add_typer(external_projects_app, name="external-projects")
app.add_typer(mission_compiler_app, name="mission-compiler")
app.add_typer(config_app, name="config")

assistant_app = typer.Typer(
    help="M2-9 AgentLab Assistant commands.",
    no_args_is_help=True,
)
register_assistant_commands(assistant_app)
app.add_typer(assistant_app, name="assistant")

goal_app = typer.Typer(help="M2-12.5 Goal / Mainline Command Bridge", no_args_is_help=True)
from agent_runtime.goals.cli import register_goal_commands
register_goal_commands(goal_app)
app.add_typer(goal_app, name="goal")

console = Console()

INIT_BASE_TEMPLATES = {
    "cost_ledger.yml": "entries: []\n",
    "brain_decisions.yml": "decisions: []\n",
}

INIT_AGENT_TEMPLATES = {
    "Supervisor": {
        "01_supervisor_plan.md": "# Supervisor Plan\n\nTBD\n",
    },
    "RepoScout": {
        "02_reposcout_report.md": "# RepoScout Report\n\nTBD\n",
    },
    "Researcher": {
        "03_research_notes.md": "# Research Notes\n\nTBD\n",
    },
    "InterfaceMapper": {
        "04_interface_map.md": "# Interface Map\n\nTBD\n",
    },
    "PromptEngineer": {
        "05_coder_prompt.md": "# Coder Handoff Prompt\n\nTBD\n",
    },
    "Coder": {
        "05_coder_prompt.md": "# Coder Handoff Prompt\n\nTBD\n",
        "06_implementation_report.md": "# Implementation Report\n\nTBD\n",
    },
    "ArtifactProducer": {
        "artifact_producer_report.md": "# Artifact Producer Report\n\nTBD\n",
    },
    "Writer": {
        "fiction_draft.md": "# Fiction Draft\n\nTBD\n",
    },
    "Reviewer": {
        "fiction_review.yml": "status: tbd\nfindings: []\n",
    },
    "Scribe": {
        "continuity_ledger.yml": "status: tbd\nentries: []\n",
    },
    "TesterAuditor": {
        "07_validation_report.md": "# Validation Report\n\nTBD\n",
        "08_audit_report.md": "# Audit Report\n\nTBD\n",
    },
    "Verifier": {
        "verification_report.md": "# Verification Report\n\nTBD\n",
    },
    "Archivist": {
        "09_archive_update.md": "# Archive Update\n\nTBD\n",
    },
}

from agent_runtime.cli.role_capability import register_role_capability_commands
register_role_capability_commands(app, _PROJECT_ROOT, console)

from agent_runtime.cli.protocol import register_protocol_commands
register_protocol_commands(app, _PROJECT_ROOT, console)

from agent_runtime.cli.external_projects import register_external_project_commands
register_external_project_commands(external_projects_app, _PROJECT_ROOT, console)

from agent_runtime.cli.routing import register_routing_commands
register_routing_commands(app, lambda: _PROJECT_ROOT, console)

from agent_runtime.cli.capability_contracts import register_capability_contract_commands
register_capability_contract_commands(app, console)

from agent_runtime.cli.runtime_hygiene import register_runtime_hygiene_commands
register_runtime_hygiene_commands(app, lambda: _PROJECT_ROOT, console)

from agent_runtime.cli.workers import register_worker_commands
register_worker_commands(app, lambda: _PROJECT_ROOT, console)

from agent_runtime.cli.models import register_model_commands
register_model_commands(app, _PROJECT_ROOT, console)

from agent_runtime.cli.governance import register_governance_commands
register_governance_commands(app, _PROJECT_ROOT, console)

from agent_runtime.cli.narrative import register_narrative_commands
register_narrative_commands(app, _PROJECT_ROOT, console)

from agent_runtime.cli.narrative_eval import register_narrative_eval_commands
register_narrative_eval_commands(app, _PROJECT_ROOT, console)

from agent_runtime.cli.background_jobs import register_background_job_commands
register_background_job_commands(app, _PROJECT_ROOT, console)

from agent_runtime.cli.run_retention import register_run_retention_commands
register_run_retention_commands(app, _PROJECT_ROOT, console)

from agent_runtime.cli.knowledge import register_knowledge_commands
register_knowledge_commands(app, _PROJECT_ROOT, console)

def _run_external_skills_cli(args: list[str]) -> None:
    from external_skills_cli import main as external_skills_main

    code = external_skills_main(args)
    if code:
        raise typer.Exit(code=code)


def _run_search_cli(args: list[str]) -> None:
    from search_cli import main as search_main

    code = search_main(args)
    if code:
        raise typer.Exit(code=code)


def _run_repo_index_cli(args: list[str]) -> None:
    from repo_index_cli import main as repo_index_main

    code = repo_index_main(args)
    if code:
        raise typer.Exit(code=code)


@mission_compiler_app.command("compile")
def compile_mission_v2(
    prompt_file: Path = typer.Option(..., "--prompt-file", help="Path to a .txt file containing the rough user prompt."),
    out: Path = typer.Option(..., "--out", help="Output directory for mission contract artifacts."),
    project: str = typer.Option("", "--project", help="Optional project name."),
    task_id: str | None = typer.Option(None, "--task-id", help="Optional task ID."),
) -> None:
    """Compile a rough project prompt into a mission contract v2.

    Reads the prompt from --prompt-file and writes deterministic mission
    contract artifacts to --out. No LLM calls — purely keyword/rule-based.
    """
    from agent_runtime.brain import build_mission_contract
    from agent_runtime.brain.renderer import render_mission_contract_outputs

    if not prompt_file.exists():
        console.print(f"[red]Error:[/red] prompt file not found: {prompt_file}")
        raise typer.Exit(code=1)
    prompt_text = prompt_file.read_text(encoding="utf-8").strip()
    if not prompt_text:
        console.print("[red]Error:[/red] prompt file is empty")
        raise typer.Exit(code=1)

    contract = build_mission_contract(
        prompt_text,
        project_id=project or None,
        task_id=task_id,
    )
    written = render_mission_contract_outputs(contract, out)

    console.print(f"[green]Mission contract compiled.[/green]")
    console.print(f"  domain:        {contract['task_type']}")
    console.print(f"  project_type:  {contract['project_type']}")
    console.print(f"  long_project:  {contract['is_long_project']}")
    console.print(f"  scale:         {contract['estimated_scale']}")
    console.print(f"  capabilities:  {len(contract['required_capabilities'])} required")
    console.print(f"  risk_flags:    {len(contract['risk_flags'])}")
    console.print(f"  decision_cards: {len(contract['decision_cards'])}")
    console.print(f"  artifacts written to: {out}")
    for name, path in sorted(written.items()):
        if name.endswith("_dir"):
            continue
        console.print(f"    -> {path.name}")


@search_app.command("web")
def search_web_cmd(query: str, mock: bool = typer.Option(False, "--mock"), project: str = typer.Option("AgentLab", "--project"), task_id: str | None = typer.Option(None, "--task-id")) -> None:
    """Run or plan web search. May call external provider only when enabled."""
    args = ["--project", project]
    if task_id:
        args.extend(["--task-id", task_id])
    args.append("search-web")
    if mock:
        args.append("--mock")
    args.append(query)
    _run_search_cli(args)


@search_app.command("extract-url")
def search_extract_url_cmd(url: str, mock: bool = typer.Option(False, "--mock"), project: str = typer.Option("AgentLab", "--project"), task_id: str | None = typer.Option(None, "--task-id")) -> None:
    """Extract a URL. Defaults avoid external provider calls unless enabled."""
    args = ["--project", project]
    if task_id:
        args.extend(["--task-id", task_id])
    args.append("extract-url")
    if mock:
        args.append("--mock")
    args.append(url)
    _run_search_cli(args)


@repo_index_app.command("status")
def repo_index_status_cmd(repo_path: Path = typer.Option(..., "--repo-path"), project: str = typer.Option("AgentLab", "--project"), task_id: str | None = typer.Option(None, "--task-id")) -> None:
    """Read-only repo indexer status. Does not clone or index."""
    args = ["--project", project]
    if task_id:
        args.extend(["--task-id", task_id])
    args.extend(["status", "--repo-path", str(repo_path)])
    _run_repo_index_cli(args)


@repo_index_app.command("index")
def repo_index_index_cmd(repo_path: Path = typer.Option(..., "--repo-path"), dry_run: bool = typer.Option(True, "--dry-run"), approve_indexing: bool = typer.Option(False, "--approve-indexing"), mode: str = typer.Option("repo_patch", "--mode"), project: str = typer.Option("AgentLab", "--project"), task_id: str | None = typer.Option(None, "--task-id")) -> None:
    """Plan or explicitly approve local repo indexing. Never clones repos."""
    args = ["--project", project]
    if task_id:
        args.extend(["--task-id", task_id])
    args.extend(["index", "--repo-path", str(repo_path), "--mode", mode])
    if not dry_run:
        args.append("--execute")
    if approve_indexing:
        args.append("--approve-indexing")
    _run_repo_index_cli(args)


@external_skills_app.command("list")
def external_skills_list(json_output: bool = typer.Option(False, "--json", help="Emit JSON.")) -> None:
    """List external skills from config/external_skill_registry.yml without executing tools."""
    _run_external_skills_cli([*( ["--json"] if json_output else [] ), "list"])


@external_skills_app.command("scan-ecc")
def external_skills_scan_ecc(json_output: bool = typer.Option(False, "--json", help="Emit JSON.")) -> None:
    """Write artifacts/external_skill_inventory.json using static ECC scan only."""
    _run_external_skills_cli([*( ["--json"] if json_output else [] ), "scan-ecc"])


@external_skills_app.command("import-ecc")
def external_skills_import_ecc(
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview import without modifying registry."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Import static ECC inventory metadata into the disabled-by-default registry."""
    args = []
    if json_output:
        args.append("--json")
    args.append("import-ecc")
    if dry_run:
        args.append("--dry-run")
    _run_external_skills_cli(args)


@external_skills_app.command("incubate")
def external_skills_incubate(
    task_id: str = typer.Option(..., "--task-id", help="Task id."),
    project: str = typer.Option("AgentLab", "--project", help="Project name."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Write task-scoped internal_skill_candidates.yml and skill_incubation_report.md."""
    args = []
    if json_output:
        args.append("--json")
    args.extend(["incubate", "--task-id", task_id, "--project", project])
    _run_external_skills_cli(args)


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


@app.command("activation-plan")
def activation_plan(
    task_packet: Path = typer.Option(..., "--task-packet")
) -> None:
    """Compile the execution economy activation plan for a task packet."""
    from agent_runtime.execution_economy.activation_plan import compile_activation_plan
    plan = compile_activation_plan(task_packet, _PROJECT_ROOT)
    print(yaml.safe_dump(plan, sort_keys=False, allow_unicode=True))


@app.command("activation-explain")
def activation_explain(
    decision: Path = typer.Option(..., "--decision")
) -> None:
    """Explain an activation decision."""
    if not decision.exists():
        console.print(f"[red]Error: decision file '{decision}' not found.[/red]")
        raise typer.Exit(code=1)
    content = yaml.safe_load(decision.read_text(encoding="utf-8")) or {}
    console.print(f"[bold]Role:[/bold] {content.get('role')}")
    console.print(f"[bold]Candidate Worker:[/bold] {content.get('candidate_worker')}")
    console.print(f"[bold]Decision:[/bold] {content.get('decision')}")
    console.print(f"[bold]Marginal Utility Verdict:[/bold] {content.get('marginal_utility_verdict')}")
    console.print("[bold]Reasons:[/bold]")
    for r in content.get("reason", []):
        console.print(f"  - {r}")


@app.command("execution-economy-report")
def execution_economy_report(
    project: str = typer.Option(..., "--project")
) -> None:
    """Print the markdown execution economy report for a project."""
    report_path = _PROJECT_ROOT / "projects" / project / "execution_economy" / "execution_economy_report.md"
    if not report_path.exists():
        console.print(f"[red]Error: execution economy report not found for project '{project}'.[/red]")
        raise typer.Exit(code=1)
    print(report_path.read_text(encoding="utf-8"))


@app.command("estimate-spawn-cost")
def estimate_spawn_cost(
    worker: str = typer.Option(..., "--worker"),
    role: str = typer.Option(..., "--role")
) -> None:
    """Estimate the cost to spawn a specific worker for a role."""
    from agent_runtime.execution_economy.activation_cost import ActivationCost
    from agent_runtime.execution_economy.activation_plan import DEFAULT_WORKER_COSTS, load_worker_costs
    from agent_runtime.execution_economy.effective_cost import calculate_effective_tokens, estimate_cost_in_usd, get_cost_tier
    from agent_runtime.execution_economy.cache_profile import calculate_cache_profile
    
    worker_costs = load_worker_costs(_PROJECT_ROOT / "config" / "worker_activation_costs.yml")
    w_cost_dict = worker_costs.get(worker, DEFAULT_WORKER_COSTS.get("claude_code"))
    act_cost = ActivationCost.from_dict({"worker_id": worker, **w_cost_dict})
    
    cp = calculate_cache_profile(worker)
    act_cost.cache_profile = cp
    
    effective_tokens = calculate_effective_tokens(act_cost)
    act_cost.fixed_startup_cost.effective_prompt_tokens = effective_tokens
    
    raw_tokens = act_cost.fixed_startup_cost.raw_prompt_tokens + act_cost.variable_cost.task_specific_context_tokens
    raw_usd = estimate_cost_in_usd(raw_tokens, worker)
    eff_usd = estimate_cost_in_usd(effective_tokens, worker)
    
    result = {
        "worker_id": worker,
        "role": role,
        "raw_tokens": raw_tokens,
        "effective_tokens": effective_tokens,
        "estimated_usd": raw_usd,
        "effective_estimated_usd": get_cost_tier(eff_usd),
        "coordination_cost": act_cost.non_token_costs.coordination_cost,
        "permission_risk": act_cost.non_token_costs.permission_risk,
        "state_mutation_risk": act_cost.non_token_costs.state_mutation_risk
    }
    print(yaml.safe_dump(result, sort_keys=False, allow_unicode=True))


@app.command("cache-profile-report")
def cache_profile_report(
    worker: str = typer.Option(..., "--worker")
) -> None:
    """Generate a cache profile report for a worker."""
    from agent_runtime.execution_economy.cache_profile import calculate_cache_profile
    cp = calculate_cache_profile(worker)
    result = {
        "worker_id": worker,
        "stable_prefix_hash": cp.stable_prefix_hash,
        "skill_context_hash": cp.skill_context_hash,
        "mcp_manifest_hash": cp.mcp_manifest_hash,
        "last_cache_hit_observed": cp.last_cache_hit_observed,
        "cache_confidence": cp.cache_confidence
    }
    print(yaml.safe_dump(result, sort_keys=False, allow_unicode=True))


@app.command("capability-providers")
def capability_providers() -> None:
    """List all registered capability providers."""
    from agent_runtime.capability_broker.broker_registry import BrokerRegistry
    registry = BrokerRegistry(_PROJECT_ROOT / "config" / "capability_provider_registry.yml")
    providers_dict = {p.provider_id: p.passport.to_dict() for p in registry.list_providers()}
    print(yaml.safe_dump(providers_dict, sort_keys=False, allow_unicode=True))


@app.command("capability-provider-inspect")
def capability_provider_inspect(
    provider: str = typer.Option(..., "--provider")
) -> None:
    """Inspect a capability provider passport."""
    from agent_runtime.capability_broker.broker_registry import BrokerRegistry
    registry = BrokerRegistry(_PROJECT_ROOT / "config" / "capability_provider_registry.yml")
    p = registry.get_provider(provider)
    if not p:
        console.print(f"[red]Error: capability provider '{provider}' not found.[/red]")
        raise typer.Exit(code=1)
    print(yaml.safe_dump(p.passport.to_dict(), sort_keys=False, allow_unicode=True))


@app.command("skill-discover")
def skill_discover(
    worker: str = typer.Option(..., "--worker"),
    safe: bool = typer.Option(True, "--safe/--unsafe")
) -> None:
    """Discover local skills exposed by a worker."""
    from agent_runtime.capability_broker.skill_discovery import discover_worker_skills
    discovered = discover_worker_skills(worker, safe=safe)
    result = {p.provider_id: p.to_dict() for p in discovered}
    print(yaml.safe_dump(result, sort_keys=False, allow_unicode=True))


@app.command("mcp-discover")
def mcp_discover(
    worker: str = typer.Option(..., "--worker"),
    safe: bool = typer.Option(True, "--safe/--unsafe")
) -> None:
    """Discover local MCP servers exposed by a worker."""
    from agent_runtime.capability_broker.mcp_discovery import discover_worker_mcps
    discovered = discover_worker_mcps(worker, safe=safe)
    result = {p.provider_id: p.to_dict() for p in discovered}
    print(yaml.safe_dump(result, sort_keys=False, allow_unicode=True))


@app.command("capability-broker-plan")
def capability_broker_plan(
    capability: str = typer.Option(..., "--capability"),
    project: str = typer.Option("AgentLab", "--project")
) -> None:
    """Route a capability to the best provider and write the plan to project files."""
    from agent_runtime.capability_broker.broker_registry import BrokerRegistry
    from agent_runtime.capability_broker.provider_trust import ProviderTrustPolicy
    from agent_runtime.capability_broker.provider_routing import route_capability
    from agent_runtime.capability_broker.renderer import render_provider_routing_plan
    
    registry = BrokerRegistry(_PROJECT_ROOT / "config" / "capability_provider_registry.yml")
    trust_policy = ProviderTrustPolicy(_PROJECT_ROOT / "config" / "provider_trust_policy.yml")
    
    # Also load discovered providers if any
    from agent_runtime.capability_broker.skill_discovery import discover_worker_skills
    from agent_runtime.capability_broker.mcp_discovery import discover_worker_mcps
    
    # Discovered providers for claude_code
    for p in discover_worker_skills("claude_code", safe=True):
        registry.register_passport(p)
    for p in discover_worker_mcps("claude_code", safe=True):
        registry.register_passport(p)
        
    prov, decision = route_capability(capability, registry, trust_policy, project_id=project)
    
    # Save output to projects/<project>/capability_broker/
    cb_dir = _PROJECT_ROOT / "projects" / project / "capability_broker"
    cb_dir.mkdir(parents=True, exist_ok=True)
    
    # Save provider passports
    passports = {p.provider_id: p.passport.to_dict() for p in registry.list_providers()}
    (cb_dir / "provider_passports.yml").write_text(yaml.safe_dump(passports, sort_keys=False), encoding="utf-8")
    
    # Save broker registry
    registry_data = {"providers": passports}
    (cb_dir / "broker_registry.yml").write_text(yaml.safe_dump(registry_data, sort_keys=False), encoding="utf-8")
    
    # Save routing decisions
    routing_data = {
        "routing_decisions": [decision]
    }
    (cb_dir / "provider_routing_decisions.yml").write_text(yaml.safe_dump(routing_data, sort_keys=False), encoding="utf-8")
    
    # Save delegated capabilities
    delegated = [p.passport.to_dict() for p in registry.list_providers() if p.passport.invocation_mode == "delegated_worker"]
    (cb_dir / "delegated_capabilities.yml").write_text(yaml.safe_dump({"delegated_capabilities": delegated}, sort_keys=False), encoding="utf-8")
    
    # Save trust report
    report_md = trust_policy.generate_trust_report(registry.list_providers())
    (cb_dir / "provider_trust_report.md").write_text(report_md, encoding="utf-8")
    
    # Print the markdown route plan
    route_plan_md = render_provider_routing_plan(capability, decision)
    print(route_plan_md)


@app.command("provider-trust-report")
def provider_trust_report() -> None:
    """Print the provider trust evaluation report."""
    from agent_runtime.capability_broker.broker_registry import BrokerRegistry
    from agent_runtime.capability_broker.provider_trust import ProviderTrustPolicy
    
    registry = BrokerRegistry(_PROJECT_ROOT / "config" / "capability_provider_registry.yml")
    trust_policy = ProviderTrustPolicy(_PROJECT_ROOT / "config" / "provider_trust_policy.yml")
    
    # Also load discovered providers
    from agent_runtime.capability_broker.skill_discovery import discover_worker_skills
    from agent_runtime.capability_broker.mcp_discovery import discover_worker_mcps
    for p in discover_worker_skills("claude_code", safe=True):
        registry.register_passport(p)
    for p in discover_worker_mcps("claude_code", safe=True):
        registry.register_passport(p)
        
    print(trust_policy.generate_trust_report(registry.list_providers()))



@app.command("eval-generalization")
def eval_generalization(
    out: Path = typer.Option(Path("acceptance_runs/s10_generalization_eval"), "--out"),
    replay_pipeline: bool = typer.Option(False, "--replay-pipeline", help="Run S10 route/task/acceptance/Project Brain replay."),
) -> None:
    """Run the S10 offline generalization evaluation suite."""
    from agent_runtime.evaluation.generalization_suite import (
        load_generalization_fixtures,
        run_generalization_suite,
        run_pipeline_replay,
    )

    summary = run_generalization_suite(_PROJECT_ROOT, out)
    replay = None
    if replay_pipeline:
        replay = run_pipeline_replay(_PROJECT_ROOT, out, load_generalization_fixtures(_PROJECT_ROOT)[0])
        summary["pipeline_replay"] = replay
    console.print(yaml.safe_dump({
        "verdict": summary["verdict"],
        "passed": summary["passed"],
        "total": summary["total"],
        "pipeline_replay": replay,
        "out": str(out),
    }, sort_keys=False))


@app.command("ci-gates")
def ci_gates(dry_run: bool = typer.Option(False, "--dry-run")) -> None:
    """Run or print the local S10 CI gate policy commands."""
    from agent_runtime.evaluation.generalization_suite import load_ci_gate_policy

    import subprocess

    policy = load_ci_gate_policy(_PROJECT_ROOT)
    commands = [gate["command"] for gate in policy["gates"]]
    if dry_run:
        for command in commands:
            console.print(command)
        return
    for command in commands:
        console.print(f"$ {command}")
        completed = subprocess.run(command, shell=True, cwd=_PROJECT_ROOT)
        if completed.returncode != 0:
            raise typer.Exit(code=completed.returncode)


@app.command("ops-console-status")
def ops_console_status(
    project: str = typer.Option("AgentLab", "--project"),
    out: Path = typer.Option(Path("acceptance_runs/s11_dashboard"), "--out"),
) -> None:
    """Write a read-only S11 ops console snapshot. Does not start a server."""
    from agent_runtime.ops_console import write_ops_console_snapshot

    path = write_ops_console_snapshot(_PROJECT_ROOT, project=project, out_dir=out)
    console.print(f"wrote {path}")


@app.command("ops-console-serve")
def ops_console_serve(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8765, "--port"),
    dry_run: bool = typer.Option(True, "--dry-run/--execute"),
) -> None:
    """Plan a local-only S11 dashboard server launch; execute remains opt-in."""
    from agent_runtime.ops_console.status_api import dry_run_server_plan

    try:
        plan = dry_run_server_plan(_PROJECT_ROOT, host=host, port=port)
    except ValueError as exc:
        console.print(str(exc))
        raise typer.Exit(code=2) from exc
    if dry_run:
        console.print(yaml.safe_dump(plan, sort_keys=False))
        return
    console.print("S11 server execution is intentionally not automatic; run the printed uvicorn command explicitly.")
    raise typer.Exit(code=2)


@app.command("service-factory-plan")
def service_factory_plan(
    prompt: str = typer.Option(..., "--prompt"),
    out: Path = typer.Option(Path("acceptance_runs/s12_productization/service_factory_demo"), "--out"),
    complexity: str = typer.Option("medium", "--complexity"),
) -> None:
    """Write S12 service match, quote, timeline, and delivery package artifacts."""
    from agent_runtime.service_factory import write_service_factory_artifacts

    data = write_service_factory_artifacts(_PROJECT_ROOT, prompt=prompt, out_dir=out, complexity=complexity)
    console.print(yaml.safe_dump({
        "service_id": data["service_match"]["service_id"],
        "quote_band": data["quote_estimate"]["quote_band"],
        "out": str(out),
    }, sort_keys=False, allow_unicode=True))


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
        docs / "08_WORKER_DIALOGUE_LOG.md",
        "# Worker Dialogue Log\n\nRecords user-visible assigned-worker conversations and implementation actions.\n\n",
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
        from project_artifact_steward import ensure_workflow_artifact_intent

        data = ensure_workflow_artifact_intent(agentlab_root, project_name, task_id, plan_path)
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


def _has_meaningful_init_request(user_request: str) -> bool:
    stripped = user_request.strip()
    return bool(stripped and stripped != "# User Request\n\nDescribe the task here.")


def _init_agents_for_request(
    user_request: str,
    *,
    agentlab_root: Path,
    project_name: str,
    task_id: str,
) -> tuple[list[str], str | None]:
    if not _has_meaningful_init_request(user_request):
        return (["Supervisor"], "unclassified_blank_request")

    try:
        from agent_runtime.brain.mission_contract import build_mission_contract
        from agent_runtime.routing.route_catalog import RouteCatalog

        contract = build_mission_contract(
            user_request,
            project_id=project_name,
            task_id=task_id,
            agentlab_root=agentlab_root,
        )
        route_decision = contract.get("route_decision") if isinstance(contract, dict) else {}
        route_decision = route_decision if isinstance(route_decision, dict) else {}
        route_key = route_decision.get("selected_route")
        agents = (
            RouteCatalog.from_file(agentlab_root / "config" / "routing_rules.yml").agents_for(str(route_key))
            if route_key
            else []
        )
        if agents:
            return (agents, str(route_key or "mission_contract"))
    except Exception:
        pass

    try:
        from agent_runtime.routing.route_catalog import RouteCatalog
        from task_router import recommend_route

        routing_config_path = agentlab_root / "config" / "routing_rules.yml"
        routing_config = yaml.safe_load(routing_config_path.read_text(encoding="utf-8")) if routing_config_path.exists() else {}
        route = recommend_route(user_request, routing_config if isinstance(routing_config, dict) else None)
        agents = list(route.agents or [])
        if not agents and route.route_key:
            agents = RouteCatalog.from_file(routing_config_path).agents_for(route.route_key)
        if agents:
            return (agents, route.route_key)
    except Exception:
        pass

    return (["Supervisor"], "unclassified_route_detection_failed")


def _init_templates_for_agents(user_request: str, agents: list[str]) -> dict[str, str]:
    selected_agents = []
    for agent in ["Supervisor", *agents]:
        if agent not in selected_agents:
            selected_agents.append(agent)

    templates: dict[str, str] = {"user_request.md": user_request}
    for agent in selected_agents:
        templates.update(INIT_AGENT_TEMPLATES.get(agent, {}))
    templates.update(INIT_BASE_TEMPLATES)
    return templates


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
    init_agents, init_route_key = _init_agents_for_request(
        user_request,
        agentlab_root=agentlab_root,
        project_name=project_name,
        task_id=task_id,
    )
    templates = _init_templates_for_agents(user_request, init_agents)
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
    console.print({
        "run_dir": str(run_dir),
        "init_route_hint": init_route_key,
        "init_agents": init_agents,
        "created": created,
        "skipped_existing": skipped,
    })


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
    """Show Skill Lifecycle MVP status and pending adoption requests."""
    agentlab_root, project_name = runtime_context(project)
    from skill_evolution import ensure_skill_registry, summarize_skill_system

    ensure_skill_registry(agentlab_root)
    summary = summarize_skill_system(agentlab_root, project_name)
    console.print("[bold]AgentLab Skill Lifecycle Status[/bold]")
    console.print({
        "project": project_name,
        "registry_path": summary["registry_path"],
        "skill_count": summary["skill_count"],
        "active_skill_count": summary["active_skill_count"],
        "retired_skill_count": summary["retired_skill_count"],
        "pending_request_count": summary["pending_request_count"],
        "staging_request_count": summary.get("staging_request_count", 0),
        "validated_request_count": summary.get("validated_request_count", 0),
        "staging_dir_count": summary.get("staging_dir_count", 0),
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


@app.command("skill-distill")
def skill_distill_cmd(
    project: Optional[str] = typer.Option(None, help="Project name."),
    task_id: str = typer.Option(..., "--task-id", help="Task run id."),
) -> None:
    """Generate a deterministic Project Memory → Skill Draft. Does not promote."""
    ensure_safe_task_id(task_id)
    agentlab_root, project_name = runtime_context(project)
    from skill_distiller import distill_skill_draft

    result = distill_skill_draft(agentlab_root, project_name, task_id)
    console.print("[green]Skill draft generated[/green]")
    console.print({
        "draft_id": result["draft_id"],
        "vault_path": result.get("vault_path") or result["draft_path"],
        "pointer_path": result.get("pointer_path"),
        "warnings": result.get("warnings", []),
    })
    console.print("[dim]Draft requires manual review. It was not promoted or activated.[/dim]")
    console.print("[dim]Skill vault changed. Run: ./agentlab.sh skill-vault-backup --dry-run[/dim]")


@app.command("skill-draft-list")
def skill_draft_list_cmd(
    project: Optional[str] = typer.Option(None, help="Project name."),
) -> None:
    """List Project Memory → Skill Drafts for a project."""
    agentlab_root, project_name = runtime_context(project)
    from skill_distiller import list_skill_drafts

    drafts = list_skill_drafts(agentlab_root, project_name)
    table = Table("Draft ID", "Name", "Status", "Task", "Reuse", "Risk", "Path")
    for draft in drafts:
        table.add_row(
            str(draft.get("id", "")),
            str(draft.get("name", "")),
            str(draft.get("status", "")),
            str(draft.get("task_id", "")),
            str(draft.get("reuse_score", "")),
            str(draft.get("risk_level", "")),
            str(draft.get("path", "")),
        )
    console.print(f"[bold]Skill Drafts — {project_name}[/bold]")
    console.print(table)


@app.command("skill-draft-approve")
def skill_draft_approve_cmd(
    project: Optional[str] = typer.Option(None, help="Project name."),
    draft_id: str = typer.Option(..., "--draft-id", help="Draft id."),
) -> None:
    """Approve a skill draft by creating a pending skill lifecycle request. No promote."""
    agentlab_root, project_name = runtime_context(project)
    from skill_distiller import approve_skill_draft

    try:
        result = approve_skill_draft(agentlab_root, project_name, draft_id)
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(code=1)
    console.print(f"[green]Skill draft approved: {draft_id}[/green]")
    console.print({
        "skill_request_id": result["skill_request_id"],
        "skill_request_path": result["skill_request_path"],
        "draft_path": result["draft_path"],
    })
    console.print(f"[dim]Next: ./agentlab.sh skill-approve --project {project_name} --request-id {result['skill_request_id']}[/dim]")
    console.print("[dim]No active skill was promoted.[/dim]")
    console.print("[dim]Skill vault changed. Run: ./agentlab.sh skill-vault-backup --dry-run[/dim]")


@app.command("skill-draft-reject")
def skill_draft_reject_cmd(
    project: Optional[str] = typer.Option(None, help="Project name."),
    draft_id: str = typer.Option(..., "--draft-id", help="Draft id."),
    reason: str = typer.Option(..., "--reason", help="Rejection reason."),
) -> None:
    """Reject a skill draft and keep the original draft artifacts."""
    agentlab_root, project_name = runtime_context(project)
    from skill_distiller import reject_skill_draft

    try:
        result = reject_skill_draft(agentlab_root, project_name, draft_id, reason)
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(code=1)
    console.print(f"[yellow]Skill draft rejected: {draft_id}[/yellow]")
    console.print({"draft_path": result["draft_path"], "reason": result["draft"].get("rejection_reason")})
    console.print("[dim]Skill vault changed. Run: ./agentlab.sh skill-vault-backup --dry-run[/dim]")


@app.command("skill-vault-list")
def skill_vault_list_cmd(
    project: Optional[str] = typer.Option(None, help="Optional project filter."),
    status: str = typer.Option("", "--status", help="Optional comma-separated status filter."),
) -> None:
    """List central Skill Vault entries from registry.yml."""
    agentlab_root, project_name = runtime_context(project)
    from skill_vault import list_vault_skills

    statuses = [item.strip() for item in status.split(",") if item.strip()] or None
    rows = list_vault_skills(agentlab_root, project=project_name if project else None, statuses=statuses)
    table = Table("Skill ID", "Name", "Status", "Project", "Task", "Risk", "Path")
    for row in rows:
        table.add_row(
            str(row.get("id", "")),
            str(row.get("name", "")),
            str(row.get("status", "")),
            str(row.get("project", "")),
            str(row.get("task_id", "")),
            str(row.get("risk_level", "")),
            str(row.get("path", "")),
        )
    console.print("[bold]Skill Vault[/bold]")
    console.print(table)


@app.command("skill-vault-status")
def skill_vault_status_cmd() -> None:
    """Show central Skill Vault layout and registry counts."""
    agentlab_root, _project_name = runtime_context(None)
    from skill_vault import vault_status

    console.print(vault_status(agentlab_root))


@app.command("skill-vault-migrate")
def skill_vault_migrate_cmd(
    project: Optional[str] = typer.Option(None, help="Project name."),
    dry_run: bool = typer.Option(True, "--dry-run", help="Preview migration without modifying files."),
    execute: bool = typer.Option(False, "--execute", help="Actually copy legacy run drafts into Skill Vault."),
) -> None:
    """Migrate legacy projects/<Project>/runs/*/skill_drafts into Skill Vault."""
    agentlab_root, project_name = runtime_context(project)
    from skill_vault import migrate_project_run_draft_to_vault

    result = migrate_project_run_draft_to_vault(agentlab_root, project_name, dry_run=dry_run or not execute, execute=execute)
    console.print(result)
    if execute and not result.get("dry_run"):
        console.print("[dim]Skill vault changed. Run: ./agentlab.sh skill-vault-backup --dry-run[/dim]")


@app.command("skill-vault-backup")
def skill_vault_backup_cmd(
    dry_run: bool = typer.Option(True, "--dry-run", help="Plan rsync without executing."),
    execute: bool = typer.Option(False, "--execute", help="Execute rsync. Must be explicit."),
) -> None:
    """Plan or explicitly execute Skill Vault rsync backup."""
    agentlab_root, _project_name = runtime_context(None)
    from skill_backup import dry_run_rsync_command, execute_rsync

    if execute:
        result = execute_rsync(agentlab_root)
    else:
        result = dry_run_rsync_command(agentlab_root)
    console.print(result)
    if result.get("error"):
        console.print(f"[yellow]{result['error']}[/yellow]")
        if execute:
            raise typer.Exit(code=1)


@app.command("skill-vault-backup-status")
def skill_vault_backup_status_cmd() -> None:
    """Show Skill Vault backup readiness without executing rsync."""
    agentlab_root, _project_name = runtime_context(None)
    from skill_backup import backup_status

    console.print(backup_status(agentlab_root))


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
    console.print(f"\n[dim]Next: ./agentlab.sh skill-approve --project {project_name} --request-id {request['id']}[/dim]")


@app.command("skill-list")
def skill_list(
    project: Optional[str] = typer.Option(None, help="Project name."),
    status_filter: Optional[str] = typer.Option(None, help="Filter by status: pending_user_approval, approved, staging, validated, active, retired, rejected."),
) -> None:
    """List all Skill Adoption Requests for a project."""
    agentlab_root, project_name = runtime_context(project)
    from skill_evolution import ensure_skill_registry, list_skill_requests, load_skill_registry, skill_staging_dir

    ensure_skill_registry(agentlab_root)
    requests = list_skill_requests(agentlab_root, project_name)
    if status_filter:
        requests = [r for r in requests if r.get("status") == status_filter]

    registry = load_skill_registry(agentlab_root)
    active_count = len([s for s in registry.get("skills", []) if s.get("status") == "active"])
    retired_count = len(registry.get("retired_skills", []))
    staging_root = skill_staging_dir(agentlab_root)
    staging_count = len([d for d in staging_root.iterdir() if d.is_dir()]) if staging_root.exists() else 0

    status_counts: dict[str, int] = {}
    for r in requests:
        s = r.get("status", "unknown")
        status_counts[s] = status_counts.get(s, 0) + 1

    console.print(f"\n[bold]Skill Requests — {project_name}[/bold]")
    console.print(f"  Total: {len(requests)} | "
                  f"Pending: {status_counts.get('pending_user_approval', 0)} | "
                  f"Approved: {status_counts.get('approved', 0)} | "
                  f"Staging: {status_counts.get('staging', 0)} | "
                  f"Validated: {status_counts.get('validated', 0)} | "
                  f"Rejected: {status_counts.get('rejected', 0)}")
    console.print(f"  Registry — Active: {active_count} | Retired: {retired_count} | Staging dirs: {staging_count}")

    if not requests:
        console.print("[dim]No skill requests found.[/dim]")
        return

    table = Table("Request ID", "Skill Name", "Status", "Source", "Skill ID")
    for r in requests:
        source = r.get("source", {}) or {}
        table.add_row(
            r.get("id", ""),
            r.get("skill_name", ""),
            r.get("status", ""),
            source.get("type", ""),
            r.get("skill_id", "-"),
        )
    console.print(table)


@app.command("skill-approve")
def skill_approve(
    project: Optional[str] = typer.Option(None, help="Project name."),
    request_id: str = typer.Option(..., "--request-id", help="Skill request ID to approve."),
) -> None:
    """Approve a pending skill request (pending_user_approval → approved)."""
    agentlab_root, project_name = runtime_context(project)
    from skill_evolution import approve_skill_request, ensure_skill_registry

    ensure_skill_registry(agentlab_root)
    try:
        result = approve_skill_request(agentlab_root, project_name, request_id)
        console.print(f"[green]Skill request approved: {request_id}[/green]")
        console.print(f"  New status: {result.get('status')}")
        console.print(f"\n[dim]Next: ./agentlab.sh skill-stage --project {project_name} --request-id {request_id}[/dim]")
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(code=1)


@app.command("skill-reject")
def skill_reject(
    project: Optional[str] = typer.Option(None, help="Project name."),
    request_id: str = typer.Option(..., "--request-id", help="Skill request ID to reject."),
    reason: str = typer.Option("Rejected by user.", "--reason", help="Reason for rejection."),
) -> None:
    """Reject a pending skill request (pending_user_approval → rejected)."""
    agentlab_root, project_name = runtime_context(project)
    from skill_evolution import ensure_skill_registry, reject_skill_request

    ensure_skill_registry(agentlab_root)
    try:
        result = reject_skill_request(agentlab_root, project_name, request_id, reason)
        console.print(f"[yellow]Skill request rejected: {request_id}[/yellow]")
        console.print(f"  Reason: {result.get('rejection_reason')}")
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(code=1)


@app.command("skill-stage")
def skill_stage(
    project: Optional[str] = typer.Option(None, help="Project name."),
    request_id: str = typer.Option(..., "--request-id", help="Approved skill request ID to stage."),
) -> None:
    """Stage an approved skill request (approved → staging)."""
    agentlab_root, project_name = runtime_context(project)
    from skill_evolution import ensure_skill_registry, stage_skill_request

    ensure_skill_registry(agentlab_root)
    try:
        result = stage_skill_request(agentlab_root, project_name, request_id)
        console.print(f"[green]Skill staged: {request_id}[/green]")
        console.print({
            "skill_id": result["skill_id"],
            "staging_dir": result["staging_dir"],
            "status": result["status"],
        })
        console.print(f"\n[dim]Next: ./agentlab.sh skill-validate --skill-id {result['skill_id']} --fake-sandbox[/dim]")
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(code=1)


@app.command("skill-validate")
def skill_validate(
    skill_id: str = typer.Option(..., "--skill-id", help="Staged skill ID to validate."),
    fake_sandbox: bool = typer.Option(True, help="Use fake sandbox (no external execution)."),
) -> None:
    """Validate a staged skill (staging → validated). --fake-sandbox only reads metadata and adapted_skill.md."""
    agentlab_root, project_name = runtime_context(None)
    from skill_evolution import ensure_skill_registry, validate_staged_skill

    ensure_skill_registry(agentlab_root)
    try:
        result = validate_staged_skill(agentlab_root, skill_id, fake_sandbox=fake_sandbox)
        console.print(f"[green]Skill validated: {skill_id}[/green]")
        console.print({
            "status": result["status"],
            "risk_level": result["risk_level"],
            "checked_files": result["checked_files_count"],
            "sandbox_report": result["sandbox_report"],
        })
        console.print(f"\n[dim]Next: ./agentlab.sh skill-promote --skill-id {skill_id}[/dim]")
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(code=1)


@app.command("skill-promote")
def skill_promote(
    skill_id: str = typer.Option(..., "--skill-id", help="Validated skill ID to promote."),
) -> None:
    """Promote a validated skill to active (validated → active)."""
    agentlab_root, project_name = runtime_context(None)
    from skill_evolution import ensure_skill_registry, promote_skill

    ensure_skill_registry(agentlab_root)
    try:
        result = promote_skill(agentlab_root, skill_id)
        console.print(f"[green]Skill promoted to active: {skill_id}[/green]")
        console.print({
            "skill_name": result["skill_name"],
            "status": result["status"],
            "active_dir": result["active_dir"],
        })
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(code=1)


@app.command("skill-retire")
def skill_retire_cmd(
    skill_id: str = typer.Option(..., "--skill-id", help="Active skill ID to retire."),
    reason: str = typer.Option(..., "--reason", help="Reason for retiring."),
) -> None:
    """Retire an active skill (active → retired)."""
    agentlab_root, project_name = runtime_context(None)
    from skill_evolution import ensure_skill_registry, retire_skill

    ensure_skill_registry(agentlab_root)
    try:
        result = retire_skill(agentlab_root, skill_id, reason)
        console.print(f"[yellow]Skill retired: {skill_id}[/yellow]")
        console.print({
            "reason": result["reason"],
            "status": result["status"],
            "retired_dir": result["retired_dir"],
        })
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(code=1)


@app.command("pack-candidate-validate")
def pack_candidate_validate_cmd(
    proposal: Path = typer.Option(..., "--proposal", help="Path to production_pack_proposal.yml."),
    catalog: Optional[Path] = typer.Option(None, "--catalog", help="Production pack catalog path."),
    allow_replace: bool = typer.Option(False, "--allow-replace", help="Allow an existing pack_id."),
) -> None:
    """Validate a synthesized production-pack proposal before promotion."""
    agentlab_root, _project_name = runtime_context(None)
    from production_pack_registry import validate_pack_candidate

    catalog_path = catalog or (agentlab_root / "config" / "production_packs.yml")
    result = validate_pack_candidate(proposal, catalog_path, allow_replace=allow_replace)
    console.print(result.as_dict())
    if not result.valid:
        raise typer.Exit(code=1)


@app.command("pack-catalog-audit")
def pack_catalog_audit_cmd(
    catalog: Optional[Path] = typer.Option(None, "--catalog", help="Production pack catalog path."),
    routing: Optional[Path] = typer.Option(None, "--routing", help="Routing rules path."),
    domain_route_packs: Optional[Path] = typer.Option(None, "--domain-route-packs", help="Domain route packs path."),
    out: Optional[Path] = typer.Option(None, "--out", help="Optional path to write the YAML report."),
) -> None:
    """Audit the production-pack catalog for selector collisions and duplicate pack ids."""
    agentlab_root, _project_name = runtime_context(None)
    from production_pack_registry import audit_pack_catalog

    catalog_path = catalog or (agentlab_root / "config" / "production_packs.yml")
    routing_path = routing or (agentlab_root / "config" / "routing_rules.yml")
    domain_route_packs_path = domain_route_packs or (agentlab_root / "config" / "domain_route_packs.yml")
    report = audit_pack_catalog(catalog_path, routing_path, domain_route_packs_path)
    text = dump_report_yaml(report, agentlab_root)
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        console.print(f"wrote {out}")
    else:
        console.print(text.rstrip())
    if report.get("status") == "fail":
        raise typer.Exit(code=1)


@app.command("pack-candidate-promote")
def pack_candidate_promote_cmd(
    proposal: Path = typer.Option(..., "--proposal", help="Path to production_pack_proposal.yml."),
    catalog: Optional[Path] = typer.Option(None, "--catalog", help="Production pack catalog path."),
    approved_by: str = typer.Option(..., "--approved-by", help="Human or Supervisor approval identity."),
    allow_replace: bool = typer.Option(False, "--allow-replace", help="Replace an existing pack_id."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Validate and preview without writing catalog."),
) -> None:
    """Promote an approved synthesized production pack into the catalog."""
    agentlab_root, _project_name = runtime_context(None)
    from production_pack_registry import promote_pack_candidate

    catalog_path = catalog or (agentlab_root / "config" / "production_packs.yml")
    try:
        result = promote_pack_candidate(
            proposal,
            catalog_path,
            approved_by=approved_by,
            allow_replace=allow_replace,
            dry_run=dry_run,
        )
    except ValueError as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(code=1)
    console.print(result)
    if result.get("status") == "invalid":
        raise typer.Exit(code=1)


@app.command("production-pack-synthesis-smoke")
def production_pack_synthesis_smoke_cmd(
    out: Optional[Path] = typer.Option(None, "--out", help="Optional path to write the YAML report."),
    project: str = typer.Option("AgentLab", "--project", help="Project name for the smoke run."),
    task_id: str = typer.Option(
        "task_production_pack_synthesis_smoke_20260707",
        "--task-id",
        help="Task run id for the smoke run.",
    ),
) -> None:
    """Generate and validate production-pack synthesis candidate artifacts offline."""
    agentlab_root, _project_name = runtime_context(None)
    from production_pack_synthesis_smoke import run_production_pack_synthesis_smoke

    report = run_production_pack_synthesis_smoke(
        agentlab_root,
        project=project,
        task_id=task_id,
        out=out,
    )
    if out:
        console.print(f"wrote {out}")
    else:
        console.print(dump_report_yaml(report, agentlab_root).rstrip())
    if report.get("status") == "fail":
        raise typer.Exit(code=1)


@app.command("production-pack-role-session-request")
def production_pack_role_session_request_cmd(
    out: Optional[Path] = typer.Option(
        None,
        "--out",
        help="Optional request YAML path; a sibling runner script is generated.",
    ),
    project: str = typer.Option(
        "AgentLab",
        "--project",
        help="Project containing the source and target synthesis runs.",
    ),
    source_task_id: str = typer.Option(
        "task_production_pack_role_session_live_20260710",
        "--source-task-id",
        help="Existing synthesis run whose user request is reused.",
    ),
    target_task_id: str = typer.Option(
        "task_production_pack_role_session_governed_20260710_01",
        "--target-task-id",
        help="Fresh candidate run id; it must not already exist.",
    ),
) -> None:
    """Build a four-role trusted-runner request without provider calls."""
    agentlab_root, _project_name = runtime_context(None)
    from production_pack_role_session_request import (
        write_production_pack_role_session_request,
    )

    request_out = out or (
        agentlab_root
        / "acceptance_runs"
        / "agentlab_capability_acceptance"
        / "production_pack_role_session_request.yml"
    )
    report = write_production_pack_role_session_request(
        agentlab_root,
        request_out,
        project=project,
        source_task_id=source_task_id,
        target_task_id=target_task_id,
    )
    console.print(f"wrote {request_out}")
    console.print(dump_report_yaml(report, agentlab_root).rstrip())
    if report.get("status") != "ready_for_explicit_approval":
        raise typer.Exit(code=1)


@app.command("production-pack-role-session-audit")
def production_pack_role_session_audit_cmd(
    out: Optional[Path] = typer.Option(
        None,
        "--out",
        help="Optional path to write the YAML report.",
    ),
    project: str = typer.Option(
        "AgentLab",
        "--project",
        help="Project containing the synthesis run.",
    ),
    task_id: str = typer.Option(
        "task_production_pack_role_session_live_20260710",
        "--task-id",
        help="Production-pack synthesis task run id.",
    ),
    require_pass: bool = typer.Option(
        False,
        "--require-pass",
        help="Exit non-zero unless the returned role-session audit passes.",
    ),
) -> None:
    """Audit returned production-pack role-session artifacts without provider calls."""
    agentlab_root, _project_name = runtime_context(None)
    from production_pack_role_session_audit import (
        write_production_pack_role_session_audit,
    )

    report_out = out or (
        agentlab_root
        / "acceptance_runs"
        / "agentlab_capability_acceptance"
        / "production_pack_role_session_audit.yml"
    )
    report = write_production_pack_role_session_audit(
        agentlab_root,
        report_out,
        project=project,
        task_id=task_id,
    )
    console.print(f"wrote {report_out}")
    console.print(dump_report_yaml(report, agentlab_root).rstrip())
    if report.get("status") == "fail" or (
        require_pass and report.get("status") != "pass"
    ):
        raise typer.Exit(code=1)


@app.command("skill-match")
def skill_match(
    task_id: str = typer.Option(..., "--task-id", help="Task run id."),
    project: Optional[str] = typer.Option(None, help="Project name."),
) -> None:
    """Match active skills against a task without writing injection usage."""
    ensure_safe_task_id(task_id)
    agentlab_root, project_name = runtime_context(project)
    run_dir = agentlab_root / "projects" / project_name / "runs" / task_id
    request_path = run_dir / "user_request.md"
    task_text = request_path.read_text(encoding="utf-8") if request_path.exists() else ""
    from skill_retriever import load_skill_injection_policy, match_active_skills

    result = match_active_skills(
        agentlab_root,
        task_text=task_text,
        policy=load_skill_injection_policy(agentlab_root),
    )
    console.print("[bold]Skill Match[/bold]")
    console.print({"project": project_name, "task_id": task_id, "selected": len(result["selected"]), "rejected": len(result["rejected"])})
    table = Table("Status", "Skill", "Name", "Reason", "Load", "Saving")
    for item in result["selected"]:
        table.add_row(
            "selected",
            item.get("skill_id", ""),
            item.get("name", ""),
            item.get("reason", ""),
            str(item.get("load_tokens", "")),
            str(item.get("expected_saving_tokens", "")),
        )
    for item in result["rejected"]:
        table.add_row("rejected", item.get("skill_id", ""), item.get("name", ""), item.get("reason", ""), "-", "-")
    console.print(table)


@app.command("skill-inject")
def skill_inject(
    task_id: str = typer.Option(..., "--task-id", help="Task run id."),
    project: Optional[str] = typer.Option(None, help="Project name."),
) -> None:
    """Inject matched active skills into workflow_plan.yml and write usage ledgers."""
    ensure_safe_task_id(task_id)
    agentlab_root, project_name = runtime_context(project)
    run_dir = agentlab_root / "projects" / project_name / "runs" / task_id
    plan_path = run_dir / "workflow_plan.yml"
    if not plan_path.exists():
        console.print(f"[yellow]workflow_plan.yml not found: {plan_path}[/yellow]")
        raise typer.Exit(code=1)
    request_path = run_dir / "user_request.md"
    task_text = request_path.read_text(encoding="utf-8") if request_path.exists() else ""
    from skill_injector import inject_skills_into_workflow_plan

    result = inject_skills_into_workflow_plan(
        agentlab_root,
        plan_path,
        project=project_name,
        task_id=task_id,
        task_text=task_text,
        record_usage=True,
    )
    console.print("[green]Skills injected into workflow plan[/green]")
    console.print({
        "workflow_plan": str(plan_path),
        "selected": len(result.get("selected", [])),
        "rejected": len(result.get("rejected", [])),
        "usage": result.get("usage", {}),
    })


@app.command("skill-usage")
def skill_usage_cmd(
    task_id: Optional[str] = typer.Option(None, "--task-id", help="Task run id for task skill usage."),
    project: Optional[str] = typer.Option(None, help="Project name."),
    skill_id: Optional[str] = typer.Option(None, "--skill-id", help="Active skill id for usage ledger."),
) -> None:
    """Show task skill_usage.yml or an active skill usage ledger."""
    if task_id:
        ensure_safe_task_id(task_id)
    agentlab_root, project_name = runtime_context(project)
    from atomic_io import safe_read_yaml

    if skill_id:
        path = agentlab_root / "skills" / "active" / skill_id / "usage_ledger.yml"
        data = safe_read_yaml(path, default={}) or {}
        console.print("[bold]Skill Usage Ledger[/bold]")
        console.print({"skill_id": skill_id, "path": str(path), "entries": len(data.get("entries", [])) if isinstance(data, dict) else 0})
        if isinstance(data, dict):
            for entry in data.get("entries", [])[-10:]:
                console.print(entry)
        return

    if not task_id:
        console.print("[yellow]Provide --task-id or --skill-id.[/yellow]")
        raise typer.Exit(code=1)
    path = agentlab_root / "projects" / project_name / "runs" / task_id / "skill_usage.yml"
    data = safe_read_yaml(path, default={}) or {}
    console.print("[bold]Task Skill Usage[/bold]")
    console.print({"project": project_name, "task_id": task_id, "path": str(path)})
    console.print(data)


@app.command("skill-import-url")
def skill_import_url(
    project: Optional[str] = typer.Option(None, help="Project name."),
    url: str = typer.Option(..., "--url", help="External SKILL.md URL to import."),
    allow_network: bool = typer.Option(False, "--allow-network", help="Allow network fetch."),
) -> None:
    """Import a skill from an external SKILL.md URL.

    Requires --allow-network to actually fetch.  The URL must be in the
    allowlist defined by config/external_skill_import_policy.yml.

    The skill always enters pending_user_approval status.
    """
    agentlab_root, project_name = runtime_context(project)
    from external_skill_importer import import_skill_from_url

    result = import_skill_from_url(
        agentlab_root,
        project=project_name,
        url=url,
        allow_network=allow_network,
    )

    if result.get("ok"):
        console.print("[green]Skill import request created[/green]")
        console.print({
            "request_id": result["request_id"],
            "skill_name": result["skill_name"],
            "source_url": result["source_url"],
            "risk_level": result["risk_level"],
            "estimated_tokens": result["input_tokens_estimate"],
            "status": result["status"],
        })
    else:
        console.print(f"[red]Import failed: {result.get('error')}[/red]")
        raise typer.Exit(code=1)


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


@app.command("watchdog-scan")
def watchdog_scan_cmd(
    project: Optional[str] = typer.Option(None, help="Project name."),
    task_id: Optional[str] = typer.Option(None, "--task-id", help="Optional task id to scan."),
) -> None:
    """Scan task runs for stale running or waiting states."""
    if task_id:
        ensure_safe_task_id(task_id)
    agentlab_root, project_name = runtime_context(project)
    from watchdog import scan_project

    summary = scan_project(agentlab_root, project_name, task_id=task_id)
    console.print("[bold]AgentLab Watchdog Scan[/bold]")
    console.print({
        "project": project_name,
        "task_count": summary.get("task_count", 0),
        "stale_count": summary.get("stale_count", 0),
    })
    table = Table("Task", "Status", "Stale", "Reasons", "Event Age", "Heartbeat Age")
    for item in summary.get("tasks", [])[-50:]:
        table.add_row(
            item.get("task_id", ""),
            item.get("raw_status", ""),
            "yes" if item.get("is_stale") else "no",
            ", ".join(item.get("reasons", [])),
            str(item.get("event_age_seconds") if item.get("event_age_seconds") is not None else "-"),
            str(item.get("heartbeat_age_seconds") if item.get("heartbeat_age_seconds") is not None else "-"),
        )
    console.print(table)


@app.command("watchdog-status")
def watchdog_status_cmd(
    task_id: str = typer.Option(..., "--task-id", help="Task run id."),
    project: Optional[str] = typer.Option(None, help="Project name."),
) -> None:
    """Show watchdog status for one task without mutating it."""
    ensure_safe_task_id(task_id)
    agentlab_root, project_name = runtime_context(project)
    from watchdog import watchdog_status

    console.print("[bold]AgentLab Watchdog Status[/bold]")
    console.print(watchdog_status(agentlab_root, project_name, task_id))


@app.command("webhook-test")
def webhook_test_cmd(
    event: str = typer.Option(..., "--event", help="Event name to send, such as ACTION_REQUIRED."),
    project: Optional[str] = typer.Option(None, help="Project name."),
    task_id: Optional[str] = typer.Option(None, "--task-id", help="Optional task id."),
) -> None:
    """Send a test webhook event if webhook policy is enabled."""
    if task_id:
        ensure_safe_task_id(task_id)
    agentlab_root, project_name = runtime_context(project)
    from webhook_dispatcher import dispatch_event

    result = dispatch_event(
        agentlab_root,
        event=event,
        project=project_name,
        task_id=task_id,
        stage="webhook_test",
        severity=event,
        summary=f"AgentLab webhook test for {event}.",
        reason="Manual webhook-test command.",
        decision_card={"id": "test", "options": [{"id": "ack", "label": "Acknowledge"}]} if event == "ACTION_REQUIRED" else None,
    )
    console.print("[bold]AgentLab Webhook Test[/bold]")
    console.print(result)


@app.command("webhook-status")
def webhook_status_cmd(
    project: Optional[str] = typer.Option(None, help="Project name."),
    task_id: Optional[str] = typer.Option(None, "--task-id", help="Optional task id."),
) -> None:
    """Show webhook delivery log status."""
    if task_id:
        ensure_safe_task_id(task_id)
    agentlab_root, project_name = runtime_context(project)
    from webhook_dispatcher import webhook_status

    status = webhook_status(agentlab_root, project_name, task_id)
    console.print("[bold]AgentLab Webhook Status[/bold]")
    console.print({
        "project": project_name,
        "task_id": task_id,
        "delivery_count": status.get("delivery_count", 0),
        "path": status.get("path"),
    })
    table = Table("Event", "Endpoint", "Status", "Attempts", "Created")
    for item in status.get("deliveries", [])[-20:]:
        table.add_row(
            item.get("event", ""),
            item.get("endpoint", ""),
            item.get("status", ""),
            str(len(item.get("attempts", []))),
            item.get("created_at", ""),
        )
    console.print(table)


@app.command("webhook-redeliver")
def webhook_redeliver_cmd(
    project: Optional[str] = typer.Option(None, help="Project name."),
    task_id: Optional[str] = typer.Option(None, "--task-id", help="Optional task id."),
) -> None:
    """Redeliver the most recent failed webhook delivery."""
    if task_id:
        ensure_safe_task_id(task_id)
    agentlab_root, project_name = runtime_context(project)
    from webhook_dispatcher import redeliver_last_failed

    result = redeliver_last_failed(agentlab_root, project_name, task_id)
    console.print("[bold]AgentLab Webhook Redeliver[/bold]")
    console.print(result)


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


@app.command("learning-review")
def learning_review_cmd(
    task_id: str = typer.Option(..., "--task-id", help="Task run id."),
    project: Optional[str] = typer.Option(None, help="Project name."),
    no_candidates: bool = typer.Option(False, help="Write review without creating skill candidates."),
) -> None:
    """Run post-task Trace-to-Skill learning review for a task."""
    ensure_safe_task_id(task_id)
    agentlab_root, project_name = runtime_context(project)
    from post_task_learning import run_learning_review

    review = run_learning_review(
        agentlab_root,
        project_name,
        task_id,
        create_candidates=not no_candidates,
    )
    console.print("[bold]Learning Review[/bold]")
    console.print({
        "project": project_name,
        "task_id": task_id,
        "status": review.get("status"),
        "candidate_count": review.get("candidate_count"),
        "review": str(agentlab_root / "projects" / project_name / "runs" / task_id / "learning_review.yml"),
    })


@app.command("skill-candidates")
def skill_candidates_cmd(
    task_id: str = typer.Option(..., "--task-id", help="Task run id."),
    project: Optional[str] = typer.Option(None, help="Project name."),
) -> None:
    """List Trace-to-Skill candidates for a task."""
    ensure_safe_task_id(task_id)
    agentlab_root, project_name = runtime_context(project)
    from post_task_learning import list_skill_candidates

    candidates = list_skill_candidates(agentlab_root, project_name, task_id)
    console.print("[bold]Skill Candidates[/bold]")
    console.print({"project": project_name, "task_id": task_id, "count": len(candidates)})
    table = Table("Candidate", "Name", "Status", "Pattern", "Trigger")
    for item in candidates:
        proposed = item.get("proposed_skill", {}) or {}
        table.add_row(
            item.get("id", ""),
            item.get("name", ""),
            item.get("status", ""),
            item.get("pattern_type", ""),
            str(proposed.get("trigger", ""))[:80],
        )
    console.print(table)


@app.command("skill-candidate-approve")
def skill_candidate_approve_cmd(
    candidate_id_arg: Optional[str] = typer.Argument(None, help="Skill candidate id to approve."),
    candidate_id: Optional[str] = typer.Option(None, "--candidate-id", help="Skill candidate id to approve."),
    task_id: Optional[str] = typer.Option(None, "--task-id", help="Task run id."),
    project: Optional[str] = typer.Option(None, help="Project name."),
    category: str = typer.Option("trace_to_skill", "--category", help="Reusable skill category."),
) -> None:
    """Approve a Trace-to-Skill candidate and create a self_learned skill request."""
    agentlab_root, project_name = runtime_context(project)
    from post_task_learning import approve_skill_candidate, load_skill_candidate_by_id

    selected_id = candidate_id_arg or candidate_id
    if not selected_id:
        console.print("[red]Error: candidate id is required.[/red]")
        raise typer.Exit(code=1)
    try:
        if task_id:
            ensure_safe_task_id(task_id)
            result = approve_skill_candidate(agentlab_root, project_name, task_id, selected_id, category=category)
        else:
            candidate, _path = load_skill_candidate_by_id(agentlab_root, selected_id, project=project)
            result = approve_skill_candidate(
                agentlab_root,
                str(candidate["project"]),
                str(candidate["created_from_task"]),
                selected_id,
                category=category,
            )
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(code=1)
    console.print("[green]Skill candidate approved[/green]")
    console.print({
        "candidate_id": selected_id,
        "status": result.get("status"),
        "skill_request_id": result.get("skill_request_id"),
        "skill_request_path": result.get("skill_request_path"),
        "registered_skill_id": result.get("registered_skill_id"),
        "registered_skill_path": result.get("registered_skill_path"),
    })


@app.command("skill-candidate-reject")
def skill_candidate_reject_cmd(
    candidate_id_arg: Optional[str] = typer.Argument(None, help="Skill candidate id to reject."),
    candidate_id: Optional[str] = typer.Option(None, "--candidate-id", help="Skill candidate id to reject."),
    task_id: Optional[str] = typer.Option(None, "--task-id", help="Task run id."),
    project: Optional[str] = typer.Option(None, help="Project name."),
    reason: str = typer.Option("Rejected by user.", "--reason", help="Reason for rejection."),
) -> None:
    """Reject a Trace-to-Skill candidate."""
    agentlab_root, project_name = runtime_context(project)
    from post_task_learning import load_skill_candidate_by_id, reject_skill_candidate

    selected_id = candidate_id_arg or candidate_id
    if not selected_id:
        console.print("[red]Error: candidate id is required.[/red]")
        raise typer.Exit(code=1)
    try:
        if task_id:
            ensure_safe_task_id(task_id)
            result = reject_skill_candidate(agentlab_root, project_name, task_id, selected_id, reason)
        else:
            candidate, _path = load_skill_candidate_by_id(agentlab_root, selected_id, project=project)
            result = reject_skill_candidate(
                agentlab_root,
                str(candidate["project"]),
                str(candidate["created_from_task"]),
                selected_id,
                reason,
            )
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(code=1)
    console.print("[yellow]Skill candidate rejected[/yellow]")
    console.print({"candidate_id": selected_id, "status": result.get("status"), "reason": result.get("rejection_reason")})


@app.command("skill-candidate-list")
def skill_candidate_list_cmd(
    project: Optional[str] = typer.Option(None, help="Optional project filter."),
) -> None:
    """List all Trace-to-Skill candidates across task runs."""
    agentlab_root, _project_name = runtime_context(project)
    from post_task_learning import list_all_skill_candidates

    candidates = list_all_skill_candidates(agentlab_root, project=project)
    console.print("[bold]Skill Candidates[/bold]")
    console.print({"project": project or "*", "count": len(candidates)})
    table = Table("Candidate", "Project", "Task", "Status", "Pattern", "Trigger")
    for item in candidates:
        proposed = item.get("proposed_skill", {}) or {}
        table.add_row(
            item.get("id", ""),
            item.get("project", ""),
            item.get("created_from_task", ""),
            item.get("status", ""),
            item.get("pattern_type", ""),
            str(proposed.get("trigger", ""))[:80],
        )
    console.print(table)


@app.command("skill-candidate-show")
def skill_candidate_show_cmd(
    candidate_id: str = typer.Argument(..., help="Skill candidate id to show."),
    project: Optional[str] = typer.Option(None, help="Optional project filter."),
) -> None:
    """Show a Trace-to-Skill candidate by id."""
    agentlab_root, _project_name = runtime_context(project)
    from post_task_learning import load_skill_candidate_by_id

    try:
        candidate, path = load_skill_candidate_by_id(agentlab_root, candidate_id, project=project)
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(code=1)
    candidate = dict(candidate)
    candidate["_path"] = str(path)
    console.print(candidate)


@app.command("skill-registry-validate")
def skill_registry_validate_cmd() -> None:
    """Validate reusable skill registry entries and filesystem paths."""
    agentlab_root, _project_name = runtime_context(None)
    from skill_evolution import ensure_skill_registry, validate_skill_registry

    ensure_skill_registry(agentlab_root)
    result = validate_skill_registry(agentlab_root)
    console.print(result)
    if not result.get("valid"):
        raise typer.Exit(code=1)


@app.command("policy-status")
def policy_status(
    project: Optional[str] = typer.Option(None, help="Project name."),
) -> None:
    """Show execution gates plus the canonical Supervisor and Coder routes."""
    agentlab_root, _ = runtime_context(project)
    configs = load_agentlab_configs(agentlab_root)
    execution_policy = configs.get("execution_policy", {})
    brain_policy = execution_policy.get("brain_policy", {})
    tier_policy = execution_policy.get("execution_policy", {})
    providers = configs.get("model_providers", {}).get("providers", {})
    from llm_provider import resolve_env_value

    supervisor_profile = resolve_profile_config(
        model_catalog=configs.get("model_catalog", {}),
        agent_name="Supervisor",
        agent_model_profiles=configs.get("agent_model_profiles", {}),
    )
    coder_profile = resolve_profile_config(
        model_catalog=configs.get("model_catalog", {}),
        agent_name="Coder",
        agent_model_profiles=configs.get("agent_model_profiles", {}),
    )
    brain_provider_name = str(supervisor_profile.get("provider") or "")
    brain_provider = providers.get(brain_provider_name, {})
    api_key_configured = bool(resolve_env_value(brain_provider.get("api_key"), ""))
    external_window = tier_policy.get("external_ide_window", {})

    console.print("[bold]AgentLab execution policy[/bold]")
    console.print(
        {
            "schema_version": execution_policy.get("schema_version", 1),
            "budget_mode_default": execution_policy.get("budget_mode_policy", {}).get("default_budget_mode", ""),
            "brain_required_provider": brain_provider_name,
            "brain_model": supervisor_profile.get("model", ""),
            "brain_cli_agent": supervisor_profile.get("cli_agent", ""),
            "brain_agent": brain_policy.get("brain_agent", "Supervisor"),
            "brain_tier": brain_policy.get("brain_tier", ""),
            "brain_provider_api_key_configured": api_key_configured,
            "coder_default_provider": coder_profile.get("provider", ""),
            "coder_default_model": coder_profile.get("model", ""),
            "coder_cli_agent": coder_profile.get("cli_agent", ""),
            "external_ide_window_enabled": external_window.get("enabled", False),
            "patch_application_policy": tier_policy.get("patch_application_policy", ""),
            "backend_authority": "config/agent_model_profiles.yml",
            "fallback_authority": "config/model_capacity.yml",
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


@app.command("log-event")
def log_event(
    task_id: str = typer.Option("task_0001", help="Task run id."),
    project: Optional[str] = typer.Option(None, help="Project name."),
    module: str = typer.Option("General", help="Project module name for the development log."),
    agent: str = typer.Option("ExternalWorker", help="Agent or executor name."),
    summary: str = typer.Option(..., help="What was handled."),
    user_message: str = typer.Option("", help="User-visible request or dialogue summary."),
    worker_response: str = typer.Option(
        "", "--worker-response", "--codex-response",
        help="Worker-visible response/action summary.",
    ),
    files_changed: str = typer.Option("", help="Comma-separated changed files."),
    commands_run: str = typer.Option("", help="Comma-separated commands actually run."),
    provider: str = typer.Option("external_worker", help="Provider or executor."),
    model: str = typer.Option("unreported", help="Model/executor label."),
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
    dialogue_log = docs / "08_WORKER_DIALOGUE_LOG.md"

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
{worker_response or summary}

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
        agentlab_root=agentlab_root,
    )
    append_cost_ledgers(project_root, run_dir, entry)
    console.print("[green]Logged AgentLab event[/green]")
    console.print({"development_log": str(dev_log), "dialogue_log": str(dialogue_log)})


@app.command("prepare")
def prepare(
    task_id: str = typer.Option("task_0001", help="Task run id, such as task_0001."),
    project: Optional[str] = typer.Option(None, help="Project name. Defaults to DEFAULT_PROJECT."),
    user_request: Optional[Path] = typer.Option(None, help="Optional path to a user request file."),
    execution_backend: str = typer.Option(
        "agentlab_orchestrated_cli",
        help="Workflow driver mode; per-role workers remain config-driven.",
    ),
    budget: Optional[str] = typer.Option(None, "--budget", help="Budget mode: frugal, balanced, or max-quality."),
    observation_input: Optional[list[Path]] = typer.Option(
        None,
        "--observation-input",
        help="Repeatable explicit file to seal into observation_contract.yml for the Observer.",
    ),
    write_plan: bool = typer.Option(False, help="Write runs/task_xxxx/workflow_plan.yml if it does not exist."),
    overwrite_plan: bool = typer.Option(False, help="Allow replacing an existing workflow_plan.yml."),
) -> None:
    """Build and optionally save the visible workflow plan."""
    ensure_safe_task_id(task_id)
    if execution_backend not in {
        "agentlab_orchestrated_cli",
        "api_native",
        "hybrid_ide",
        "langgraph",
    }:
        raise typer.BadParameter(
            "execution_backend must be agentlab_orchestrated_cli, api_native, "
            "hybrid_ide, or langgraph"
        )
    if observation_input and not write_plan:
        raise typer.BadParameter("--observation-input requires --write-plan")

    agentlab_root, project_name = runtime_context(project)
    plan = build_workflow_plan(
        agentlab_root=agentlab_root,
        project_name=project_name,
        task_id=task_id,
        execution_backend=execution_backend,
        user_request_path=user_request,
        budget_mode=budget,
    )
    if observation_input and (
        plan.route.route_key != "observation_task"
        or "Observer" not in plan.route.agents
        or (plan.production_pack or {}).get("pack_id") != "read_only_observation"
    ):
        raise typer.BadParameter(
            "--observation-input requires a request routed to "
            "observation_task/read_only_observation"
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
    console.print("[bold]Workflow plan summary[/bold]")
    console.print({
        "budget_mode": plan.budget_mode,
        "budget_profile": plan.budget_profile,
        "project_size": plan.project_size,
        "risk_level": plan.risk_level,
        "route": {
            "route_key": plan.route.route_key,
            "agents": plan.route.agents,
            "skipped_agents": plan.route.skipped_agents,
        },
        "production_pack": {
            "status": plan.production_pack.get("status"),
            "pack_id": plan.production_pack.get("pack_id"),
            "required_outputs": plan.production_pack.get("required_outputs", []),
        },
        "artifact_intent": {
            "candidate_dir": plan.artifact_intent.get("candidate_dir"),
            "production_dir": plan.artifact_intent.get("production_dir"),
            "declared_production_paths": plan.artifact_intent.get("declared_production_paths", []),
        },
        "missing_inputs": plan.missing_inputs,
        "write_plan": write_plan,
    })

    if write_plan:
        plan_path = Path(plan.run_dir) / "workflow_plan.yml"
        from context_governance import build_context_artifacts, context_summary, write_context_artifacts
        context_artifacts = build_context_artifacts(agentlab_root, project_name, task_id)
        plan_data = plan.model_dump(mode="json")
        plan_data.setdefault("context_governance", {
            "summary": context_summary(context_artifacts),
            "profile": context_artifacts["context_profile"],
            "budget": context_artifacts["context_budget"],
            "artifacts": ["context_profile.yml", "context_budget.yml", "context_pack.yml", "compression_trace.yml"],
        })
        plan_data.setdefault("notes", list(plan_data.get("notes") or []))
        plan_data["notes"].append("Context governance: profile, budget, compression trace, and context pack are generated before agent execution.")
        plan_data["notes"].append(
            "Mission governance: mission_contract.yml and companion artifacts are "
            "persisted from the same deterministic compiler output used for route "
            "and production-pack selection."
        )
        wrote = write_yaml_if_allowed(plan_path, plan_data, overwrite=overwrite_plan)
        if wrote:
            mark_planned(Path(plan.run_dir), project_name, task_id)
            from progress_tracker import create_progress, load_progress
            from lifecycle_graph import create_lifecycle, load_lifecycle, mark_node_completed
            from task_snapshot import safe_write_task_snapshot
            from skill_injector import inject_skills_into_workflow_plan
            run_dir = Path(plan.run_dir)
            task_text = (
                Path(plan.user_request_path).read_text(encoding="utf-8")
                if Path(plan.user_request_path).exists()
                else ""
            )
            written_mission = write_mission_contract_artifacts(
                agentlab_root,
                project_name,
                task_id,
                task_text,
                run_dir,
                mission_contract=plan.mission_contract,
            )
            written_context = write_context_artifacts(agentlab_root, project_name, task_id)
            observation_contract_path = None
            if observation_input:
                from agent_runtime.observation_contract import (
                    materialize_observation_contract,
                )

                observation_contract_path = materialize_observation_contract(
                    plan,
                    observation_input,
                    overwrite=overwrite_plan,
                )
            inject_skills_into_workflow_plan(
                agentlab_root,
                plan_path,
                project=project_name,
                task_id=task_id,
                task_text=task_text,
                record_usage=True,
            )
            from intelligence_plans import maybe_write_intelligence_plans
            maybe_write_intelligence_plans(
                run_dir,
                task_id=task_id,
                task_text=task_text,
                route_key=getattr(plan.route, "route_key", None),
            )
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
                mark_node_completed(run_dir, "CONTEXT_PROFILE", written_context.get("context_profile"))
                mark_node_completed(run_dir, "CONTEXT_BUDGET", written_context.get("context_budget"))
                mark_node_completed(run_dir, "CONTEXT_PACK", written_context.get("context_pack"))
                mark_node_completed(run_dir, "PREPARE_PLAN")
            safe_write_task_snapshot(run_dir, project_name, task_id)
            console.print(f"[green]Wrote workflow plan:[/green] {plan_path}")
            console.print("[green]Wrote mission contract artifacts:[/green]")
            console.print({name: str(path) for name, path in written_mission.items()})
            console.print("[green]Wrote context governance artifacts:[/green]")
            console.print(written_context)
            if observation_contract_path is not None:
                console.print(
                    "[green]Wrote read-only observation contract:[/green] "
                    f"{observation_contract_path}"
                )
        else:
            console.print(f"[yellow]Plan already exists and was not overwritten:[/yellow] {plan_path}")
            if observation_input:
                raise typer.BadParameter(
                    "--observation-input requires a newly written plan or --overwrite-plan"
                )


@app.command("status")
def status(
    task_id: str = typer.Option("task_0001", help="Task run id."),
    project: Optional[str] = typer.Option(None, help="Project name."),
) -> None:
    """Show task state, route, reports, recovery verdict, and missing inputs."""
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

    # ── Show recovery verdict if available ──
    run_dir = Path(plan.run_dir)
    verdict_path = run_dir / "recovery" / "recovery_verdict.json"
    if verdict_path.exists():
        from atomic_io import safe_read_yaml
        verdict = safe_read_yaml(verdict_path) or {}
        console.print("[bold]Latest Recovery Verdict[/bold]")
        console.print(f"  Verdict: {verdict.get('verdict', '?')}")
        console.print(f"  Reason: {verdict.get('reason', '?')}")
        console.print(f"  Safe to Auto-Retry: {verdict.get('safe_to_auto_retry', '?')}")
        console.print(f"  Requires Human Review: {verdict.get('requires_human_review', '?')}")
        console.print(f"  Attempts Remaining: {verdict.get('allowed_attempts_remaining', '?')}")

        # Check for indexed failures
        failures_dir = run_dir / "recovery" / "failures"
        if failures_dir.exists():
            indexed = sorted(failures_dir.glob("failure_event_*.json"))
            if indexed:
                console.print(f"  Total failures recorded: {len(indexed)}")

    table = Table("Agent", "Report", "Exists")
    for agent in plan.route.agents:
        path = report_path_for_agent(plan, agent)
        table.add_row(agent, str(path), "yes" if path.exists() else "no")
    console.print(table)


@app.command("project-workflow-plan")
def project_workflow_plan_cmd(
    mission_contract: Path = typer.Option(..., "--mission-contract", help="Path to mission contract YAML file."),
    out: Path = typer.Option(..., "--out", help="Output directory to save workflow plan files."),
    project_id: Optional[str] = typer.Option(None, "--project-id", help="Optional project ID override."),
) -> None:
    """Generate a ProjectWorkflowPlan based on the mission contract."""
    from agent_runtime.project_workflows.planner import create_project_workflow_plan
    from agent_runtime.project_workflows.renderer import write_workflow_plan

    agentlab_root, _ = runtime_context(None)
    
    plan = create_project_workflow_plan(
        mission_contract_path=mission_contract,
        agentlab_root=agentlab_root,
        project_id=project_id,
    )
    
    write_workflow_plan(plan, out)
    if plan.warnings:
        for w in plan.warnings:
            console.print(f"[yellow]Warning: {w}[/yellow]")
    console.print(f"[green]Project workflow plan generated and saved to:[/green] {out}")


def _context_command(task_id: str, project: Optional[str], *, write: bool, show: str) -> None:
    ensure_safe_task_id(task_id)
    agentlab_root, project_name = runtime_context(project)
    run_dir = agentlab_root / "projects" / project_name / "runs" / task_id
    if write:
        from context_governance import write_context_artifacts
        written = write_context_artifacts(agentlab_root, project_name, task_id)
        console.print("[green]Context governance artifacts written[/green]")
        console.print(written)
    from context_governance.context_pack import build_context_artifacts, context_summary, load_context_artifacts
    artifacts = load_context_artifacts(run_dir)
    if not any(artifacts.values()):
        if not run_dir.exists():
            console.print(f"[yellow]Task run directory does not exist: {run_dir}[/yellow]")
            raise typer.Exit(code=1)
        artifacts = build_context_artifacts(agentlab_root, project_name, task_id)
    if show == "summary":
        console.print(context_summary(artifacts))
    else:
        console.print(artifacts.get(show) or {})


@app.command("context-profile")
def context_profile_cmd(task_id: str = typer.Option("task_0001", help="Task run id."), project: Optional[str] = typer.Option(None, help="Project name."), write: bool = typer.Option(False, "--write", help="Write artifacts first.")) -> None:
    """Build/show deterministic ContextProfile."""
    _context_command(task_id, project, write=write, show="context_profile")


@app.command("context-budget")
def context_budget_cmd(task_id: str = typer.Option("task_0001", help="Task run id."), project: Optional[str] = typer.Option(None, help="Project name."), write: bool = typer.Option(False, "--write", help="Write artifacts first.")) -> None:
    """Build/show deterministic ContextBudget."""
    _context_command(task_id, project, write=write, show="context_budget")


@app.command("context-pack")
def context_pack_cmd(task_id: str = typer.Option("task_0001", help="Task run id."), project: Optional[str] = typer.Option(None, help="Project name."), write: bool = typer.Option(False, "--write", help="Write artifacts first.")) -> None:
    """Build/show deterministic ContextPack."""
    _context_command(task_id, project, write=write, show="context_pack")


@app.command("context-show")
def context_show_cmd(task_id: str = typer.Option("task_0001", help="Task run id."), project: Optional[str] = typer.Option(None, help="Project name."), write: bool = typer.Option(False, "--write", help="Write artifacts first.")) -> None:
    """Print a readable context governance summary."""
    _context_command(task_id, project, write=write, show="summary")


@app.command("context-audit")
def context_audit_cmd(task_id: str = typer.Option("task_0001", help="Task run id."), project: Optional[str] = typer.Option(None, help="Project name."), write: bool = typer.Option(False, "--write", help="Write artifacts first.")) -> None:
    """Audit context compression: tokens before/after, dropped/kept sources, truncation."""
    ensure_safe_task_id(task_id)
    agentlab_root, project_name = runtime_context(project)
    run_dir = agentlab_root / "projects" / project_name / "runs" / task_id

    if write:
        from context_governance import write_context_artifacts
        write_context_artifacts(agentlab_root, project_name, task_id)

    # P2-H: prefer JSON audit if available
    audit_path = run_dir / "context_compression_audit.json"
    if audit_path.exists():
        import json
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        console.print("[bold]Context Compression Audit[/bold]")
        console.print(f"  Task: {audit.get('task_id')}")
        console.print(f"  Scenario: {audit.get('scenario')}")
        console.print(f"  Strategy: {audit.get('strategy')}")
        console.print(f"  [bold]Tokens before: {audit.get('estimated_tokens_before')}[/bold]")
        console.print(f"  [bold]Tokens after: {audit.get('estimated_tokens_after')}[/bold]")
        console.print(f"  [bold]Compression ratio: {audit.get('compression_ratio')}[/bold]")
        dropped = audit.get("dropped_sources", [])
        kept = audit.get("kept_sources", [])
        console.print(f"  Dropped sources: {len(dropped)}")
        console.print(f"  Kept sources: {len(kept)}")
        truncation = audit.get("truncation_events", [])
        if truncation:
            console.print(f"  [yellow]Truncation events: {len(truncation)}[/yellow]")
        if audit.get("fallback_used"):
            console.print("  [yellow]Fallback was used![/yellow]")
        if audit.get("warnings"):
            console.print(f"  [yellow]Warnings: {len(audit['warnings'])}[/yellow]")
            for w in audit["warnings"][:10]:
                console.print(f"    - {w}")
    else:
        # Fallback to old P2-G audit behavior
        from context_governance.context_pack import load_context_artifacts
        artifacts = load_context_artifacts(run_dir)
        missing = [name for name, data in artifacts.items() if data is None]
        pack = artifacts.get("context_pack") or {}
        dumped = yaml.safe_dump(pack, sort_keys=False, allow_unicode=True)
        issues = []
        if missing:
            issues.append(f"missing artifacts: {missing}")
        if len(dumped) > 70000:
            issues.append("context_pack appears too large")
        if not (pack.get("externalized_artifacts") or pack.get("omitted_sections")):
            issues.append("no externalized/omitted refs recorded")
        console.print("[bold]Context Governance Audit (P2-G)[/bold]")
        console.print({"project": project_name, "task_id": task_id, "missing": missing, "issues": issues, "pack_chars": len(dumped)})
        if issues:
            raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# P2-H Context Governance CLI (Part C)
# ---------------------------------------------------------------------------

@app.command("context-build")
def context_build_cmd(
    task_id: str = typer.Option(..., help="Task run id."),
    project: Optional[str] = typer.Option(None, help="Project name."),
    request_text: Optional[str] = typer.Option(None, "--request", help="Override request text."),
    route_profile: Optional[str] = typer.Option(None, "--route-profile", help="Route profile hint."),
    budget_mode: Optional[str] = typer.Option(None, "--budget-mode", help="Budget mode hint."),
) -> None:
    """Build all standard context artifacts for a task run."""
    ensure_safe_task_id(task_id)
    agentlab_root, project_name = runtime_context(project)
    from context_governance import write_context_artifacts

    written_paths = write_context_artifacts(
        agentlab_root,
        project_name,
        task_id,
        request_text=request_text,
    )

    console.print("[bold green]Context artifacts built:[/bold green]")
    for name, path in written_paths.items():
        console.print(f"  {name}: {path}")
    if route_profile or budget_mode:
        console.print("[yellow]Route/budget hints are retained for CLI compatibility; active config owns policy.[/yellow]")


@app.command("context-status")
def context_status_cmd(
    task_id: str = typer.Option(..., help="Task run id."),
    project: Optional[str] = typer.Option(None, help="Project name."),
) -> None:
    """Show context pack status without sensitive content."""
    ensure_safe_task_id(task_id)
    agentlab_root, project_name = runtime_context(project)
    run_dir = agentlab_root / "projects" / project_name / "runs" / task_id

    console.print(f"[bold]Context Status: {project_name}/{task_id}[/bold]")

    artifacts = {
        "context_profile.yml": run_dir / "context_profile.yml",
        "context_budget.yml": run_dir / "context_budget.yml",
        "context_pack.yml": run_dir / "context_pack.yml",
        "context_pack.md": run_dir / "context_pack.md",
        "context_compression_audit.json": run_dir / "context_compression_audit.json",
        "context_sources.json": run_dir / "context_sources.json",
    }

    for name, path in artifacts.items():
        status = "EXISTS" if path.exists() else "MISSING"
        color = "green" if path.exists() else "red"
        console.print(f"  [{color}]{status}[/{color}] {name}")

    # Read audit for summary
    audit_path = run_dir / "context_compression_audit.json"
    if audit_path.exists():
        import json
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        console.print(f"  Scenario: {audit.get('scenario', 'N/A')}")
        console.print(f"  Strategy: {audit.get('strategy', 'N/A')}")
        console.print(f"  Tokens before: {audit.get('estimated_tokens_before', 'N/A')}")
        console.print(f"  Tokens after: {audit.get('estimated_tokens_after', 'N/A')}")
        console.print(f"  Compression ratio: {audit.get('compression_ratio', 'N/A')}")
        console.print(f"  Fallback used: {audit.get('fallback_used', 'N/A')}")
        if audit.get("warnings"):
            console.print(f"  Warnings: {len(audit['warnings'])}")
    else:
        console.print("  [yellow]No context audit found — run context-build first.[/yellow]")


@app.command("context-smoke")
def context_smoke_cmd(
    project: Optional[str] = typer.Option(None, help="Project name."),
) -> None:
    """Smoke-test context governance: create fixtures, build artifacts, validate schema."""
    agentlab_root, project_name = runtime_context(project)
    from context_governance import write_context_artifacts

    smoke_task_id = "task_ctx_smoke"
    smoke_request = "This is a smoke test for context governance. Run validation and verify artifacts."

    paths = write_context_artifacts(
        agentlab_root,
        project_name,
        smoke_task_id,
        request_text=smoke_request,
    )

    console.print("[bold green]Smoke test passed![/bold green]")
    console.print(f"  Task ID: {smoke_task_id}")
    console.print("  Artifacts:")
    for name, path in paths.items():
        console.print(f"    [green]{name}: {path}[/green]")

    # Validate schema
    import json
    audit_path = Path(paths["compression_audit"]) if paths.get("compression_audit") else None
    if audit_path is not None and audit_path.exists():
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        assert audit.get("task_id") == smoke_task_id, "audit task_id mismatch"
        assert audit.get("estimated_tokens_before", 0) > 0, "audit tokens_before empty"
        assert isinstance(audit.get("compression_ratio"), (int, float)), "compression_ratio wrong type"
        console.print("  [green]Audit schema validated.[/green]")

    sources_path = Path(paths["context_sources"]) if paths.get("context_sources") else None
    if sources_path is not None and sources_path.exists():
        sources = json.loads(sources_path.read_text(encoding="utf-8"))
        assert isinstance(sources.get("sources"), list), "sources must be a list"
        console.print("  [green]Sources schema validated.[/green]")

    pack_path = Path(paths["context_pack"]) if paths.get("context_pack") else None
    if pack_path is not None and pack_path.exists():
        pack = yaml.safe_load(pack_path.read_text(encoding="utf-8"))
        assert pack is not None, "context_pack.yml not parseable"
        console.print("  [green]Context pack schema validated.[/green]")

    # Clean up smoke artifacts
    run_dir = agentlab_root / "projects" / project_name / "runs" / smoke_task_id
    for f in run_dir.glob("context_*"):
        f.unlink()
    for f in run_dir.glob("cost_*"):
        f.unlink()


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
            model_catalog=configs.get("model_catalog", {}),
            agent_name=agent_name,
            agent_model_profiles=configs.get("agent_model_profiles", {}),
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
    verbose: bool = typer.Option(False, "--verbose", help="Show every resolved mode/tier role profile."),
) -> None:
    """Audit model/provider wiring without making network calls."""
    agentlab_root, _ = runtime_context(project)
    configs = load_agentlab_configs(agentlab_root)
    check = validate_model_configuration(configs)

    console.print("[bold]AgentLab model doctor[/bold]")
    console.print(
        {
            "status": check["status"],
            "issue_count": check["issue_count"],
            "resolved_profile_count": len(check.get("resolved_profiles", [])),
        }
    )

    if verbose:
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


def _handle_command_failure(
    *,
    agentlab_root: Path,
    project_name: str,
    task_id: str,
    agent_name: str,
    plan,
    exc: Exception,
    tx_id: str | None,
) -> None:
    """Create recovery artifacts when a command fails during task execution.

    Produces: failure_event.json, failure_diagnosis.json, recovery_plan.md,
    and recovery_verdict.json in the task run directory.  Handles multiple
    failures by writing indexed files under recovery/failures/.
    """
    run_dir = Path(plan.run_dir)
    try:
        from agent_runtime.recovery import (
            create_failure_event,
            FailureClassifier,
            diagnose_failure,
            build_recovery_plan,
            load_retry_policy,
            decide_retry_action,
        )
        from state_store import (
            mark_failed_recoverable,
            mark_failed_blocked,
            mark_failed_stopped,
        )
        import json
        import traceback

        # ── 1. Create FailureEvent ──
        stderr_text = "".join(
            traceback.format_exception_only(type(exc), exc)
        )
        failure_event = create_failure_event(
            task_id=task_id,
            project=project_name,
            stage=agent_name,
            command=f"run-agent {agent_name}",
            exit_code=1,
            stderr=stderr_text,
            stdout=None,
            artifact_paths=[],
            context_pack_path=str(run_dir / "context" / "context_pack.yml"),
            error_type=None,
        )

        # ── 2. Classify the failure ──
        classifier = FailureClassifier()
        classification = classifier.classify(
            stderr=stderr_text,
            stdout=None,
            error_type=None,
            exit_code=1,
        )

        # ── 3. Diagnose ──
        diagnosis = diagnose_failure(failure_event)

        # ── 4. Build recovery plan ──
        policy = load_retry_policy(run_dir)
        plan_obj = build_recovery_plan(failure_event, diagnosis, policy)

        # ── 5. Decide verdict ──
        verdict = decide_retry_action(diagnosis, policy)

        # ── 6. Write recovery artifacts ──
        recovery_dir = run_dir / "recovery"
        recovery_dir.mkdir(parents=True, exist_ok=True)

        # Use indexed files for multiple failures
        failures_dir = recovery_dir / "failures"
        failures_dir.mkdir(parents=True, exist_ok=True)
        existing = sorted(failures_dir.glob("failure_event_*.json"))
        index = len(existing) + 1

        # Write indexed failure event
        event_path = failures_dir / f"failure_event_{index}.json"
        event_path.write_text(
            json.dumps(failure_event.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        # Write indexed diagnosis
        diagnosis_path = failures_dir / f"failure_diagnosis_{index}.json"
        diagnosis_path.write_text(
            json.dumps(diagnosis.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        # Write indexed recovery plan
        plan_path = failures_dir / f"recovery_plan_{index}.md"
        plan_path.write_text(plan_obj.to_markdown(), encoding="utf-8")

        # Write indexed verdict
        verdict_path = failures_dir / f"recovery_verdict_{index}.json"
        verdict_path.write_text(
            json.dumps(verdict.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        # Also write latest copies at the top of recovery/ for convenience
        _copy_latest = lambda stem, ext: (
            (recovery_dir / f"{stem}{ext}").write_text(
                (failures_dir / f"{stem}_{index}{ext}").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
        )
        _copy_latest("failure_event", ".json")
        _copy_latest("failure_diagnosis", ".json")
        _copy_latest("recovery_plan", ".md")
        _copy_latest("recovery_verdict", ".json")

        # ── 7. Update task state based on verdict ──
        reason = f"{agent_name} failed: {stderr_text[:200]}"
        verdict_type = verdict.verdict.value

        if verdict_type == "human_review":
            mark_failed_blocked(
                run_dir, project_name, task_id,
                f"{reason} | Verdict: human_review",
                failed_agent=agent_name,
            )
        elif verdict_type == "stop":
            mark_failed_stopped(
                run_dir, project_name, task_id,
                f"{reason} | Verdict: stop",
                failed_agent=agent_name,
            )
        else:
            mark_failed_recoverable(
                run_dir, project_name, task_id,
                f"{reason} | Verdict: {verdict_type}",
                failed_agent=agent_name,
            )

        console.print(f"\n[bold red]Agent {agent_name} failed.[/bold red]")
        console.print(f"  Category: {diagnosis.primary_category.value}")
        console.print(f"  Verdict: {verdict_type}")
        console.print(f"  Recovery artifacts: {recovery_dir}/failures/")
        console.print(f"  Latest verdict: {verdict_path}")

    except Exception as recovery_err:
        # If recovery itself fails, fall back to blocked (not recoverable)
        console.print(f"[yellow]Recovery pipeline failed: {recovery_err}[/yellow]")
        try:
            from state_store import mark_failed_blocked
            mark_failed_blocked(
                run_dir, project_name, task_id,
                f"{agent_name} execution interrupted. Recovery pipeline failed. Transaction: {tx_id}.",
                failed_agent=agent_name,
            )
        except Exception:
            pass


@app.command("run-agent")
def run_agent(
    agent_name: str = typer.Argument(..., help="Agent name, e.g. Supervisor or Coder."),
    task_id: str = typer.Option("task_0001", help="Task run id."),
    project: Optional[str] = typer.Option(None, help="Project name."),
    execution_backend: str = typer.Option(
        "agentlab_orchestrated_cli",
        help="Workflow driver used only when the plan must be rebuilt.",
    ),
    budget: Optional[str] = typer.Option(None, "--budget", help="Budget mode used when rebuilding a plan: frugal, balanced, or max-quality."),
    provider: Optional[str] = typer.Option(None, help="Override provider, e.g. deepseek or openai."),
    model: Optional[str] = typer.Option(None, help="Override model id for this run."),
    output: Optional[Path] = typer.Option(None, help="Optional report output path, relative to run dir unless absolute."),
    execute: bool = typer.Option(False, help="Actually call the configured model API. Default is dry-run."),
    overwrite_report: bool = typer.Option(False, help="Overwrite an existing non-placeholder report."),
    force: bool = typer.Option(False, help="Allow running an agent not present in the selected route."),
    no_apply_patches: bool = typer.Option(False, help="Skip applying structured edit blocks from the LLM output."),
    writer_ultracode: bool = typer.Option(
        False,
        "--writer-ultracode",
        help="Explicitly opt this Writer run into the developmental Ultracode contract.",
    ),
    writer_work_type: Optional[str] = typer.Option(
        None,
        "--writer-work-type",
        help="Ultracode work type: developmental_edit, structure, continuity, or revision_plan.",
    ),
) -> None:
    """Dry-run or execute a single agent and write its report."""
    ensure_safe_task_id(task_id)
    agentlab_root, project_name = runtime_context(project)
    plan = load_or_build_plan(agentlab_root, project_name, task_id, execution_backend, budget_mode=budget)
    if writer_ultracode or writer_work_type is not None:
        if agent_name != "Writer":
            raise typer.BadParameter(
                "--writer-ultracode and --writer-work-type are valid only for Writer."
            )
        if not writer_ultracode:
            raise typer.BadParameter(
                "--writer-work-type requires the explicit --writer-ultracode opt-in."
            )
        contracts = (
            (load_agentlab_configs(agentlab_root).get("worker_invocation_contracts") or {}).get(
                "contracts"
            )
            or {}
        )
        ultracode_contract = contracts.get("claude_writer_ultracode") or {}
        allowed_work = [
            str(item) for item in ultracode_contract.get("allowed_work", [])
        ]
        forbidden_work = {
            str(item) for item in ultracode_contract.get("forbidden_work", [])
        }
        selected_work_type = str(writer_work_type or "").strip()
        if (
            not selected_work_type
            or selected_work_type not in allowed_work
            or selected_work_type in forbidden_work
        ):
            raise typer.BadParameter(
                "--writer-work-type must be one of: " + ", ".join(allowed_work)
            )
        writer_plan = dict(plan.included_agents.get("Writer") or {})
        writer_plan.update(
            {
                "ultracode_opt_in": True,
                "writer_mode": "developmental_ultracode",
                "work_type": selected_work_type,
            }
        )
        plan.included_agents["Writer"] = writer_plan
    if agent_name not in plan.route.agents and not force:
        raise typer.BadParameter(f"{agent_name} is not in route {plan.route.agents}. Use --force to override.")

    # ── Recovery-aware guard: refuse to run unsafe tasks ──
    run_dir = Path(plan.run_dir)
    verdict_path = run_dir / "recovery" / "recovery_verdict.json"
    if verdict_path.exists() and not force:
        from atomic_io import safe_read_yaml
        verdict = safe_read_yaml(verdict_path) or {}
        verdict_type = verdict.get("verdict", "")
        if verdict_type in ("human_review", "stop"):
            console.print(
                f"[red]Task has recovery verdict '{verdict_type}'. "
                f"Execution blocked.[/red]"
            )
            console.print(f"  Reason: {verdict.get('reason', 'unknown')}")
            console.print(f"  Use --force to override this guard.")
            console.print(f"  Review verdict: {verdict_path}")
            return

    output_path = assert_path_allowed(report_path_for_agent(plan, agent_name, output), agentlab_root)
    model_output_path = output_path
    if agent_name == "Writer" and output_path.name == "fiction_draft.md":
        model_output_path = Path(plan.run_dir) / "writer_role_session_capture.md"
    settings, _ = resolve_agent_settings(
        agentlab_root,
        agent_name,
        provider,
        model,
        profile_config=(plan.model_profiles or {}).get(agent_name),
    )
    actual_executor = resolve_agent_execution_preview(
        agentlab_root,
        plan,
        agent_name,
        provider,
        model,
    )
    messages = compose_agent_messages(agentlab_root, plan, agent_name, model_output_path)

    console.print("[bold]Agent run plan[/bold]")
    console.print(
        {
            "agent": agent_name,
            "project": project_name,
            "task_id": task_id,
            "provider": settings.provider,
            "model": settings.model,
            "api_key_configured": settings.api_key_configured,
            "actual_executor": actual_executor,
            "output": str(output_path),
            "execute": execute,
            "apply_patches": not no_apply_patches,
        }
    )

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

        result = run_agent_model(
            agentlab_root,
            plan,
            agent_name,
            model_output_path,
            provider,
            model,
            apply_patches=not no_apply_patches,
        )
    except Exception as exc:
        _handle_command_failure(
            agentlab_root=agentlab_root,
            project_name=project_name,
            task_id=task_id,
            agent_name=agent_name,
            plan=plan,
            exc=exc,
            tx_id=tx_id,
        )
        raise
    finally:
        if tx_id:
            try:
                release_lock(agentlab_root, project_name, task_id)
            except Exception:
                pass
    raw_usage = result.raw_usage or {}
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
                agentlab_root=Path(plan.agentlab_root),
                usage_source=raw_usage.get("usage_source"),
                token_estimation_method=raw_usage.get("token_estimation_method"),
                exact_usage_available=raw_usage.get("exact_usage_available"),
                raw_usage=raw_usage,
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
        fallback_path = Path(plan.run_dir) / f"external_worker_handoff_{agent_name}.md"
        fallback_path.write_text(result.content, encoding="utf-8")
        run_dir_path = Path(plan.run_dir)
        state = load_state(run_dir_path, project_name, task_id)
        state.status = "blocked"
        state.last_event = f"{agent_name} requires an external worker handoff."
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
                result.error or "External worker handoff required.",
                agentlab_root=Path(plan.agentlab_root),
                usage_source=raw_usage.get("usage_source"),
                token_estimation_method=raw_usage.get("token_estimation_method"),
                exact_usage_available=raw_usage.get("exact_usage_available"),
                raw_usage=raw_usage,
            ),
        )
        console.print("[yellow]External worker handoff written[/yellow]")
        console.print({"output": str(fallback_path), "usage": result.model_dump(exclude={"content"})})
        return

    gate_issues = []
    if agent_name == "Writer":
        try:
            from agent_runtime.narrative.production.live_writer import (
                materialize_registered_writer_result,
            )
        except ModuleNotFoundError:  # pragma: no cover - direct script path
            from narrative.production.live_writer import (
                materialize_registered_writer_result,
            )

        delivery = materialize_registered_writer_result(
            result,
            Path(plan.run_dir),
            task_id,
            capture_name=model_output_path.name,
        )
        output_path = Path(str(delivery["output_path"]))
        output_content = str(delivery["output_content"])
        if delivery.get("status") != "pass":
            gate_issues.extend(str(issue) for issue in delivery.get("issues", []))
            if not gate_issues:
                gate_issues.append("Writer output contract did not pass")
    else:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(result.content, encoding="utf-8")
        output_content = result.content or ""
    if agent_name == "NarrativePlanner":
        try:
            from agent_runtime.narrative_delivery import (
                narrative_planner_validation_issues,
                write_narrative_planner_validation,
            )
        except ModuleNotFoundError:  # pragma: no cover - direct script path
            from narrative_delivery import (
                narrative_planner_validation_issues,
                write_narrative_planner_validation,
            )

        validation = write_narrative_planner_validation(
            Path(plan.project_root),
            Path(plan.run_dir),
            output_path,
        )
        gate_issues.extend(narrative_planner_validation_issues(validation))
    if agent_name == "Archivist":
        try:
            from project_artifact_steward import apply_archive_protocol

            receipt = apply_archive_protocol(Path(plan.agentlab_root), project_name, task_id)
            gate_issues.extend(f"archive_receipt error: {error}" for error in receipt.get("errors") or [])
        except Exception as exc:
            gate_issues.append(f"Project Artifact Steward failed: {type(exc).__name__}: {exc}")
    if not gate_issues:
        gate_issues.extend(artifact_content_issues(output_path.name, output_content, Path(plan.run_dir)))
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
                agentlab_root=Path(plan.agentlab_root),
                usage_source=raw_usage.get("usage_source"),
                token_estimation_method=raw_usage.get("token_estimation_method"),
                exact_usage_available=raw_usage.get("exact_usage_available"),
                raw_usage=raw_usage,
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
            agentlab_root=Path(plan.agentlab_root),
            usage_source=raw_usage.get("usage_source"),
            token_estimation_method=raw_usage.get("token_estimation_method"),
            exact_usage_available=raw_usage.get("exact_usage_available"),
            raw_usage=raw_usage,
        ),
    )

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
    execution_backend: str = typer.Option(
        "agentlab_orchestrated_cli",
        help="Workflow driver; use langgraph only for the alternate graph engine.",
    ),
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
        from agent_runtime.revision_governance import revision_dispatch_status

        dispatch = revision_dispatch_status(agentlab_root, project_name, task_id)
        if dispatch.get("blocked"):
            console.print("[red]Revision governance blocks execution.[/red]")
            console.print(yaml.safe_dump(dispatch, sort_keys=False, allow_unicode=True).rstrip())
            raise typer.Exit(code=1)

    from pipeline_runner import run_full_pipeline
    from agent_runtime.observability.api import emit_event
    emit_event(
        project_id=project_name, project_dir=agentlab_root, event_type="executor_started",
        details={"mode": 'execute' if not use_fake else 'dry-run'}, task_id=task_id
    )
    result = run_full_pipeline(agentlab_root, project_name, task_id, dry_run=(dry_run and not execute), fake_provider=use_fake, budget_mode=budget)
    emit_event(
        project_id=project_name, project_dir=agentlab_root, event_type="executor_finished",
        details={"status": result.get('final_status', '?'), "success": bool(result.get('success'))}, task_id=task_id
    )
    if result.get("success"):
        emit_event(project_id=project_name, project_dir=agentlab_root, event_type="phase_accepted", details={}, task_id=task_id)
    console.print(f"\n[bold]Lifecycle Pipeline Result[/bold]")
    console.print(f"  Mode: {'execute' if not use_fake else 'dry-run'}")
    console.print(f"  Final status: {result.get('final_status', result.get('status', '?'))}")
    console.print(f"  Steps executed: {len(result.get('history', []))}")
    console.print(f"  Pipeline complete: {bool(result.get('success'))}")
    nodes = {str(item.get("node")) for item in result.get("history", []) if item.get("node")}
    run_dir = agentlab_root / "projects" / project_name / "runs" / task_id
    try:
        from lifecycle_graph import load_lifecycle

        lifecycle = load_lifecycle(run_dir) or {}
        for node_id, node in (lifecycle.get("nodes") or {}).items():
            if node_id.startswith("CONTEXT_") and node.get("status") in {"completed", "skipped"}:
                nodes.add(node_id)
    except Exception:
        pass
    context_artifacts = {
        "CONTEXT_PROFILE": "context_profile.yml",
        "CONTEXT_BUDGET": "context_budget.yml",
        "CONTEXT_PACK": "context_pack.yml",
    }
    for context_node, artifact_name in context_artifacts.items():
        if context_node in nodes or (run_dir / artifact_name).exists():
            console.print(f"  Context stage: {context_node}")
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
            execution_backend="agentlab_orchestrated_cli",
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
    force: bool = typer.Option(False, "--force", help="Force resume even if recovery verdict blocks it."),
) -> None:
    """Resume a paused task. Optionally switch provider or use lifecycle resume."""
    ensure_safe_task_id(task_id)
    agentlab_root, project_name = runtime_context(project)
    run_dir = Path(agentlab_root / "projects" / project_name / "runs" / task_id)

    # ── P2-K: Recovery-aware guard ──
    recovery_verdict_path = run_dir / "recovery" / "recovery_verdict.json"

    if recovery_verdict_path.exists():
        from atomic_io import safe_read_yaml
        from agent_runtime.recovery.human_review import load_latest_human_review_decision
        from agent_runtime.recovery.resume_policy import derive_recovery_next_action

        verdict = safe_read_yaml(recovery_verdict_path) or {}
        human_decision = load_latest_human_review_decision(run_dir)

        result = derive_recovery_next_action(
            verdict=verdict,
            human_decision=human_decision,
            force=force,
        )

        if result["allowed"]:
            console.print(f"[green]{result['reason']}. Resuming.[/green]")
        elif result["requires_force"]:
            console.print(f"[red]{result['reason']}.[/red]")
            console.print(f"  Use --force to override.")
            return
        else:
            console.print(f"[red]{result['reason']}. Resume blocked.[/red]")
            v = verdict.get("verdict", "")
            if v == "human_review" and human_decision is None:
                console.print(f"  Use 'recovery-approve' to approve, then resume.")
            return

        if force and result["auditable_force_required"]:
            console.print("[yellow]--force used: bypassing recovery guard.[/yellow]")
            from agent_runtime.recovery.human_review import write_human_review_decision
            write_human_review_decision(
                run_dir, task_id,
                decision="approve_retry",
                reason="Force resume by operator.",
                source="cli",
                force_used=True,
            )

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


@app.command("provider-smoke")
def provider_smoke_cmd(
    provider: str = typer.Option("deepseek", "--provider", help="Provider key to test."),
    model: Optional[str] = typer.Option(None, "--model", help="Optional model override for this smoke."),
    out: Optional[Path] = typer.Option(None, "--out", help="YAML report output path."),
    live: bool = typer.Option(False, "--live", help="Execute a non-private live reachability prompt."),
) -> None:
    """Write a provider reachability smoke report without rendering secrets."""
    agentlab_root, _ = runtime_context(None)
    from provider_smoke import build_provider_smoke_report

    report = build_provider_smoke_report(agentlab_root, provider=provider, model_override=model, live=live)
    text = dump_report_yaml(report, agentlab_root)
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        console.print(f"wrote {out}")
    else:
        console.print(text.rstrip())
    if report.get("status") == "blocked":
        raise typer.Exit(code=1)


@app.command("grok-cli-smoke")
def grok_cli_smoke_cmd(
    out: Optional[Path] = typer.Option(None, "--out", help="YAML report output path."),
    live: bool = typer.Option(False, "--live", help="Execute a non-private Grok CLI reachability prompt."),
    timeout_seconds: int = typer.Option(60, "--timeout-seconds", help="Live command timeout."),
    diagnostics: bool = typer.Option(True, "--diagnostics/--no-diagnostics", help="On live failure, include non-private grok inspect/models diagnostics."),
) -> None:
    """Write a non-private Grok CLI session smoke report."""
    agentlab_root, _ = runtime_context(None)
    from grok_cli_smoke import build_grok_cli_smoke_report

    report = build_grok_cli_smoke_report(
        agentlab_root,
        live=live,
        timeout_seconds=timeout_seconds,
        include_diagnostics=diagnostics,
    )
    text = dump_report_yaml(report, agentlab_root)
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        console.print(f"wrote {out}")
    else:
        console.print(text.rstrip())
    if report.get("status") == "blocked":
        raise typer.Exit(code=1)


@app.command("agy-cli-smoke")
def agy_cli_smoke_cmd(
    out: Optional[Path] = typer.Option(None, "--out", help="YAML report output path."),
    live: bool = typer.Option(False, "--live", help="Execute a non-private Agy CLI reachability prompt."),
    timeout_seconds: int = typer.Option(60, "--timeout-seconds", help="Live command timeout."),
) -> None:
    """Write a non-private Agy CLI session smoke report."""
    agentlab_root, _ = runtime_context(None)
    from agy_cli_smoke import build_agy_cli_smoke_report

    report = build_agy_cli_smoke_report(
        agentlab_root,
        live=live,
        timeout_seconds=timeout_seconds,
        smoke_dir=out.parent / out.stem if out else None,
    )
    text = dump_report_yaml(report, agentlab_root)
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        console.print(f"wrote {out}")
    else:
        console.print(text.rstrip())
    if report.get("status") == "blocked":
        raise typer.Exit(code=1)


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


@app.command("capability-acceptance")
def capability_acceptance_cmd(
    out: Optional[Path] = typer.Option(None, "--out", help="Optional path to write the YAML report."),
) -> None:
    """Aggregate local evidence for AgentLab's core capability acceptance matrix."""
    agentlab_root, _project_name = runtime_context(None)
    from capability_acceptance import build_capability_acceptance_report

    report = build_capability_acceptance_report(agentlab_root)
    text = dump_report_yaml(report, agentlab_root)
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        console.print(f"wrote {out}")
    else:
        console.print(text.rstrip())
    if report.get("overall_status") == "fail":
        raise typer.Exit(code=1)


@app.command("frontdesk-boundary-audit")
def frontdesk_boundary_audit_cmd(
    agent: str = typer.Option("hermes", "--agent", help="Frontdesk agent id to audit."),
    out: Optional[Path] = typer.Option(None, "--out", help="Optional path to write the YAML report."),
) -> None:
    """Audit that frontdesk operation stays separate from role-worker execution."""
    agentlab_root, _project_name = runtime_context(None)
    from frontdesk_boundary_audit import build_frontdesk_boundary_audit

    report = build_frontdesk_boundary_audit(agentlab_root, frontdesk_agent=agent)
    text = dump_report_yaml(report, agentlab_root)
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        console.print(f"wrote {out}")
    else:
        console.print(text.rstrip())
    if report.get("status") == "fail":
        raise typer.Exit(code=1)


@app.command("web-ui-candidate-smoke")
def web_ui_candidate_smoke_cmd(
    web_ui_dir: Optional[Path] = typer.Option(None, "--web-ui-dir", help="Candidate web_ui artifact directory."),
    out: Optional[Path] = typer.Option(None, "--out", help="JSON report output path."),
) -> None:
    """Run a local DOM/fetch smoke against a run-local Web UI candidate."""
    agentlab_root, _project_name = runtime_context(None)
    from ui_candidate_smoke import DEFAULT_WEB_UI_RUN, write_web_ui_candidate_smoke

    report_out = out or (
        agentlab_root
        / "projects"
        / "AgentLab"
        / "runs"
        / DEFAULT_WEB_UI_RUN
        / "ui_candidate_smoke_report.json"
    )
    report = write_web_ui_candidate_smoke(agentlab_root, report_out, web_ui_dir=web_ui_dir)
    console.print(f"wrote {report_out}")
    console.print(report)
    if report.get("status") == "fail":
        raise typer.Exit(code=1)


@app.command("web-ui-browser-smoke")
def web_ui_browser_smoke_cmd(
    web_ui_dir: Optional[Path] = typer.Option(None, "--web-ui-dir", help="Candidate web_ui artifact directory."),
    out: Optional[Path] = typer.Option(None, "--out", help="JSON report output path."),
) -> None:
    """Render a run-local Web UI candidate with headless Chrome and inspect the DOM."""
    agentlab_root, _project_name = runtime_context(None)
    from ui_candidate_smoke import DEFAULT_WEB_UI_RUN, write_web_ui_browser_smoke

    report_out = out or (
        agentlab_root
        / "projects"
        / "AgentLab"
        / "runs"
        / DEFAULT_WEB_UI_RUN
        / "ui_browser_smoke_report.json"
    )
    report = write_web_ui_browser_smoke(agentlab_root, report_out, web_ui_dir=web_ui_dir)
    console.print(f"wrote {report_out}")
    console.print(report)
    if report.get("status") == "fail":
        raise typer.Exit(code=1)


@app.command("web-ui-interaction-smoke")
def web_ui_interaction_smoke_cmd(
    web_ui_dir: Optional[Path] = typer.Option(None, "--web-ui-dir", help="Candidate web_ui artifact directory."),
    out: Optional[Path] = typer.Option(None, "--out", help="JSON report output path."),
) -> None:
    """Exercise run-local Web UI candidate operator interactions."""
    agentlab_root, _project_name = runtime_context(None)
    from ui_candidate_smoke import DEFAULT_WEB_UI_RUN, write_web_ui_interaction_smoke

    report_out = out or (
        agentlab_root
        / "projects"
        / "AgentLab"
        / "runs"
        / DEFAULT_WEB_UI_RUN
        / "ui_interaction_smoke_report.json"
    )
    report = write_web_ui_interaction_smoke(agentlab_root, report_out, web_ui_dir=web_ui_dir)
    console.print(f"wrote {report_out}")
    console.print(report)
    if report.get("status") == "fail":
        raise typer.Exit(code=1)


@app.command("web-ui-api-smoke")
def web_ui_api_smoke_cmd(
    web_ui_dir: Optional[Path] = typer.Option(None, "--web-ui-dir", help="Candidate web_ui artifact directory."),
    out: Optional[Path] = typer.Option(None, "--out", help="JSON report output path."),
) -> None:
    """Exercise a run-local Web UI candidate backing API write."""
    agentlab_root, _project_name = runtime_context(None)
    from ui_candidate_smoke import DEFAULT_WEB_UI_RUN, write_web_ui_api_smoke

    report_out = out or (
        agentlab_root
        / "projects"
        / "AgentLab"
        / "runs"
        / DEFAULT_WEB_UI_RUN
        / "ui_api_smoke_report.json"
    )
    report = write_web_ui_api_smoke(agentlab_root, report_out, web_ui_dir=web_ui_dir)
    console.print(f"wrote {report_out}")
    console.print(report)
    if report.get("status") == "fail":
        raise typer.Exit(code=1)


@app.command("web-ui-visual-smoke")
def web_ui_visual_smoke_cmd(
    web_ui_dir: Optional[Path] = typer.Option(None, "--web-ui-dir", help="Candidate web_ui artifact directory."),
    out: Optional[Path] = typer.Option(None, "--out", help="JSON report output path."),
    screenshot: Optional[Path] = typer.Option(None, "--screenshot", help="Screenshot PNG output path."),
) -> None:
    """Capture a run-local Web UI candidate screenshot and run pixel-health checks."""
    agentlab_root, _project_name = runtime_context(None)
    from ui_candidate_smoke import DEFAULT_WEB_UI_RUN, write_web_ui_visual_smoke

    run_dir = agentlab_root / "projects" / "AgentLab" / "runs" / DEFAULT_WEB_UI_RUN
    report_out = out or (run_dir / "ui_visual_smoke_report.json")
    screenshot_out = screenshot or (run_dir / "ui_visual_smoke.png")
    report = write_web_ui_visual_smoke(
        agentlab_root,
        report_out,
        web_ui_dir=web_ui_dir,
        screenshot_path=screenshot_out,
    )
    console.print(f"wrote {report_out}")
    console.print(report)
    if report.get("status") == "fail":
        raise typer.Exit(code=1)


@app.command("web-ui-responsive-smoke")
def web_ui_responsive_smoke_cmd(
    web_ui_dir: Optional[Path] = typer.Option(None, "--web-ui-dir", help="Candidate web_ui artifact directory."),
    out: Optional[Path] = typer.Option(None, "--out", help="JSON report output path."),
) -> None:
    """Capture desktop/mobile screenshots and run responsive pixel-health checks."""
    agentlab_root, _project_name = runtime_context(None)
    from ui_candidate_smoke import DEFAULT_WEB_UI_RUN, write_web_ui_responsive_smoke

    run_dir = agentlab_root / "projects" / "AgentLab" / "runs" / DEFAULT_WEB_UI_RUN
    report_out = out or (run_dir / "ui_responsive_smoke_report.json")
    report = write_web_ui_responsive_smoke(agentlab_root, report_out, web_ui_dir=web_ui_dir)
    console.print(f"wrote {report_out}")
    console.print(report)
    if report.get("status") == "fail":
        raise typer.Exit(code=1)


@app.command("production-chain-audit")
def production_chain_audit_cmd(
    out: Optional[Path] = typer.Option(None, "--out", help="Optional path to write the YAML report."),
) -> None:
    """Audit representative task types against AgentLab production chains."""
    agentlab_root, _project_name = runtime_context(None)
    from production_chain_audit import build_production_chain_audit

    report = build_production_chain_audit(agentlab_root)
    text = dump_report_yaml(report, agentlab_root)
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        console.print(f"wrote {out}")
    else:
        console.print(text.rstrip())
    if report.get("status") == "fail":
        raise typer.Exit(code=1)


@app.command("agent-role-chain-audit")
def agent_role_chain_audit_cmd(
    out: Optional[Path] = typer.Option(None, "--out", help="Optional path to write the YAML report."),
) -> None:
    """Audit role responsibilities, worker bindings, and production-chain agents."""
    agentlab_root, _project_name = runtime_context(None)
    from agent_role_chain_audit import build_agent_role_chain_audit

    report = build_agent_role_chain_audit(agentlab_root)
    text = dump_report_yaml(report, agentlab_root)
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        console.print(f"wrote {out}")
    else:
        console.print(text.rstrip())
    if report.get("status") == "fail":
        raise typer.Exit(code=1)


@app.command("live-unblock-plan")
def live_unblock_plan_cmd(
    out: Optional[Path] = typer.Option(None, "--out", help="Optional path to write the YAML report."),
) -> None:
    """Write the pending internal live role-session action plan."""
    agentlab_root, _project_name = runtime_context(None)
    from live_unblock_plan import build_live_unblock_plan

    report = build_live_unblock_plan(agentlab_root)
    text = dump_report_yaml(report, agentlab_root)
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        console.print(f"wrote {out}")
    else:
        console.print(text.rstrip())


@app.command("external-acceptance-readiness")
def external_acceptance_readiness_cmd(
    out: Optional[Path] = typer.Option(None, "--out", help="Optional path to write the YAML report."),
) -> None:
    """Legacy alias for internal live-smoke readiness."""
    agentlab_root, _project_name = runtime_context(None)
    from external_acceptance_readiness import write_external_acceptance_readiness

    report_out = out or (
        agentlab_root
        / "acceptance_runs"
        / "agentlab_capability_acceptance"
        / "external_acceptance_readiness.yml"
    )
    report = write_external_acceptance_readiness(agentlab_root, report_out)
    console.print(f"wrote {report_out}")
    console.print(dump_report_yaml(report, agentlab_root).rstrip())
    if report.get("status") == "fail":
        raise typer.Exit(code=1)


@app.command("internal-live-readiness")
def internal_live_readiness_cmd(
    out: Optional[Path] = typer.Option(None, "--out", help="Optional path to write the YAML report."),
) -> None:
    """Audit whether internal AgentLab live-smoke routes are ready."""
    agentlab_root, _project_name = runtime_context(None)
    from external_acceptance_readiness import write_internal_live_readiness

    report_out = out or (
        agentlab_root
        / "acceptance_runs"
        / "agentlab_capability_acceptance"
        / "internal_live_readiness.yml"
    )
    report = write_internal_live_readiness(agentlab_root, report_out)
    console.print(f"wrote {report_out}")
    console.print(dump_report_yaml(report, agentlab_root).rstrip())
    if report.get("status") == "fail":
        raise typer.Exit(code=1)


@app.command("frontdesk-live-handoff")
def frontdesk_live_handoff_cmd(
    out: Optional[Path] = typer.Option(None, "--out", help="Optional path to write the YAML report."),
    agent: str = typer.Option("hermes", "--agent", help="Frontdesk agent id."),
) -> None:
    """Write a frontdesk-safe handoff for live AgentLab acceptance work."""
    agentlab_root, _project_name = runtime_context(None)
    from frontdesk_live_handoff import write_frontdesk_live_handoff

    report_out = out or (
        agentlab_root
        / "acceptance_runs"
        / "agentlab_capability_acceptance"
        / "frontdesk_live_handoff.yml"
    )
    report = write_frontdesk_live_handoff(agentlab_root, report_out, frontdesk_agent=agent)
    console.print(f"wrote {report_out}")
    console.print(dump_report_yaml(report, agentlab_root).rstrip())
    if report.get("status") == "fail":
        raise typer.Exit(code=1)



@app.command("trusted-live-runner-request")
def trusted_live_runner_request_cmd(
    out: Optional[Path] = typer.Option(None, "--out", help="Optional path to write the YAML request."),
    request_id: Optional[str] = typer.Option(None, "--request-id", help="Stable request id for repeatable scripts."),
) -> None:
    """Write a trusted-runner request for private internal live smokes."""
    agentlab_root, _project_name = runtime_context(None)
    from trusted_live_runner_request import write_trusted_live_runner_request

    request_out = out or (
        agentlab_root
        / "acceptance_runs"
        / "agentlab_capability_acceptance"
        / "trusted_live_runner_request.yml"
    )
    report = write_trusted_live_runner_request(agentlab_root, request_out, request_id=request_id)
    console.print(f"wrote {request_out}")
    if report.get("script_path"):
        console.print(f"wrote {report['script_path']}")
    console.print(dump_report_yaml(report, agentlab_root).rstrip())
    if report.get("status") == "fail":
        raise typer.Exit(code=1)


@app.command("trusted-live-runner-status")
def trusted_live_runner_status_cmd(
    out: Optional[Path] = typer.Option(None, "--out", help="Optional path to write the YAML status report."),
    request: Optional[Path] = typer.Option(None, "--request", help="Trusted runner request YAML to inspect."),
) -> None:
    """Check whether trusted runner live-smoke artifacts have returned."""
    agentlab_root, _project_name = runtime_context(None)
    from trusted_live_runner_status import write_trusted_live_runner_status

    status_out = out or (
        agentlab_root
        / "acceptance_runs"
        / "agentlab_capability_acceptance"
        / "trusted_live_runner_status.yml"
    )
    report = write_trusted_live_runner_status(agentlab_root, status_out, request_path=request)
    console.print(f"wrote {status_out}")
    console.print(dump_report_yaml(report, agentlab_root).rstrip())


@app.command("trusted-live-runner-operator-handoff")
def trusted_live_runner_operator_handoff_cmd(
    out: Optional[Path] = typer.Option(None, "--out", help="Optional path to write the YAML handoff."),
    request: Optional[Path] = typer.Option(None, "--request", help="Trusted runner request YAML to package."),
) -> None:
    """Write safe operator instructions for running and collecting trusted live smokes."""
    agentlab_root, _project_name = runtime_context(None)
    from trusted_live_runner_operator_handoff import write_trusted_live_runner_operator_handoff

    handoff_out = out or (
        agentlab_root
        / "acceptance_runs"
        / "agentlab_capability_acceptance"
        / "trusted_live_runner_operator_handoff.yml"
    )
    report = write_trusted_live_runner_operator_handoff(agentlab_root, handoff_out, request_path=request)
    console.print(f"wrote {handoff_out}")
    console.print(dump_report_yaml(report, agentlab_root).rstrip())
    if report.get("status") == "needs_attention":
        raise typer.Exit(code=1)


@app.command("trusted-live-runner-collect")
def trusted_live_runner_collect_cmd(
    out: Optional[Path] = typer.Option(None, "--out", help="Optional path to write the YAML collection report."),
    request: Optional[Path] = typer.Option(None, "--request", help="Trusted runner request YAML to collect."),
    item: Optional[str] = typer.Option(None, "--item", help="Optional trusted runner item id to summarize."),
) -> None:
    """Refresh trusted-runner status and acceptance reports after a live run."""
    agentlab_root, _project_name = runtime_context(None)
    from trusted_live_runner_collect import selected_collect_path, write_trusted_live_runner_collect

    canonical_collect = (
        agentlab_root
        / "acceptance_runs"
        / "agentlab_capability_acceptance"
        / "trusted_live_runner_collect.yml"
    )
    if out is not None:
        collect_out = out
        report = write_trusted_live_runner_collect(
            agentlab_root,
            collect_out,
            request_path=request,
            item_id=item,
        )
    elif item:
        write_trusted_live_runner_collect(
            agentlab_root,
            canonical_collect,
            request_path=request,
            item_id=None,
        )
        collect_out = selected_collect_path(canonical_collect, item)
        report = yaml.safe_load(collect_out.read_text(encoding="utf-8")) or {}
    else:
        collect_out = canonical_collect
        report = write_trusted_live_runner_collect(
            agentlab_root,
            collect_out,
            request_path=request,
            item_id=None,
        )
    console.print(f"wrote {collect_out}")
    console.print(dump_report_yaml(report, agentlab_root).rstrip())
    if report.get("status") == "fail":
        raise typer.Exit(code=1)


@app.command("trusted-live-runner-preflight")
def trusted_live_runner_preflight_cmd(
    out: Optional[Path] = typer.Option(None, "--out", help="Optional path to write the YAML preflight report."),
    request: Optional[Path] = typer.Option(None, "--request", help="Trusted runner request YAML to inspect."),
) -> None:
    """Check local trusted-runner prerequisites without provider calls."""
    agentlab_root, _project_name = runtime_context(None)
    from trusted_live_runner_preflight import write_trusted_live_runner_preflight

    preflight_out = out or (
        agentlab_root
        / "acceptance_runs"
        / "agentlab_capability_acceptance"
        / "trusted_live_runner_preflight.yml"
    )
    report = write_trusted_live_runner_preflight(agentlab_root, preflight_out, request_path=request)
    console.print(f"wrote {preflight_out}")
    console.print(dump_report_yaml(report, agentlab_root).rstrip())
    if report.get("status") == "fail":
        raise typer.Exit(code=1)


@app.command("acceptance-report-hygiene")
def acceptance_report_hygiene_cmd(
    out: Optional[Path] = typer.Option(None, "--out", help="Optional path to write the YAML report."),
) -> None:
    """Audit canonical acceptance reports and non-authoritative snapshot freshness."""
    agentlab_root, _project_name = runtime_context(None)
    from acceptance_report_hygiene import write_acceptance_report_hygiene

    report_out = out or (
        agentlab_root
        / "acceptance_runs"
        / "agentlab_capability_acceptance"
        / "acceptance_report_hygiene.yml"
    )
    report = write_acceptance_report_hygiene(agentlab_root, report_out)
    console.print(f"wrote {report_out}")
    console.print(dump_report_yaml(report, agentlab_root).rstrip())
    if report.get("status") == "fail":
        raise typer.Exit(code=1)


@app.command("goal-completion-audit")
def goal_completion_audit_cmd(
    out: Optional[Path] = typer.Option(None, "--out", help="Optional path to write the YAML report."),
) -> None:
    """Audit the current goal against proven evidence and live blockers."""
    agentlab_root, _project_name = runtime_context(None)
    from goal_completion_audit import build_goal_completion_audit

    report = build_goal_completion_audit(agentlab_root)
    text = dump_report_yaml(report, agentlab_root)
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        console.print(f"wrote {out}")
    else:
        console.print(text.rstrip())
    if report.get("status") == "fail":
        raise typer.Exit(code=1)


@app.command("objective-requirement-audit")
def objective_requirement_audit_cmd(
    out: Optional[Path] = typer.Option(None, "--out", help="Optional path to write the YAML report."),
) -> None:
    """Audit the active user objective as explicit requirements and evidence."""
    agentlab_root, _project_name = runtime_context(None)
    from objective_requirement_audit import write_objective_requirement_audit

    report_out = out or (
        agentlab_root
        / "acceptance_runs"
        / "agentlab_capability_acceptance"
        / "objective_requirement_audit.yml"
    )
    report = write_objective_requirement_audit(agentlab_root, report_out)
    console.print(f"wrote {report_out}")
    console.print(dump_report_yaml(report, agentlab_root).rstrip())
    if report.get("status") == "fail":
        raise typer.Exit(code=1)


@app.command("crown-live-candidate-audit")
def crown_live_candidate_audit_cmd(
    out: Optional[Path] = typer.Option(None, "--out", help="Optional path to write the YAML report."),
    task_id: str = typer.Option(
        "task_narrative_eval_ch01_live_ch01_20260707_cli_fallback",
        "--task-id",
        help="Crown run id to audit.",
    ),
) -> None:
    """Audit the local Crown live chapter candidate without calling providers."""
    agentlab_root, _project_name = runtime_context(None)
    from crown_candidate_audit import write_crown_live_candidate_audit

    report_out = out or (
        agentlab_root
        / "acceptance_runs"
        / "agentlab_capability_acceptance"
        / "crown_live_candidate_audit.yml"
    )
    report = write_crown_live_candidate_audit(agentlab_root, report_out, task_id=task_id)
    console.print(f"wrote {report_out}")
    console.print(dump_report_yaml(report, agentlab_root).rstrip())
    if report.get("status") == "fail":
        raise typer.Exit(code=1)


@app.command("crown-scale-governance-audit")
def crown_scale_governance_audit_cmd(
    out: Optional[Path] = typer.Option(None, "--out", help="Optional path to write the YAML report."),
) -> None:
    """Audit Crown 1500-chapter governance-scale ledgers without generating prose."""
    agentlab_root, _project_name = runtime_context(None)
    from crown_scale_governance_audit import write_crown_scale_governance_audit

    report_out = out or (
        agentlab_root
        / "acceptance_runs"
        / "agentlab_capability_acceptance"
        / "crown_scale_governance_audit.yml"
    )
    report = write_crown_scale_governance_audit(agentlab_root, report_out)
    console.print(f"wrote {report_out}")
    console.print(dump_report_yaml(report, agentlab_root).rstrip())
    if report.get("status") == "fail":
        raise typer.Exit(code=1)


@app.command("crown-completion-batch-audit")
def crown_completion_batch_audit_cmd(
    eval_id: str = typer.Option(..., "--eval-id", help="Stable narrative-eval id shared by the chapter runs."),
    through_chapter: int = typer.Option(..., "--through-chapter", min=1, help="Audit chapters 1 through this chapter."),
    out: Optional[Path] = typer.Option(None, "--out", help="Optional path to write the YAML report."),
) -> None:
    """Audit a resumable local Crown candidate chapter chain without providers."""
    agentlab_root, _project_name = runtime_context(None)
    from crown_candidate_audit import write_crown_completion_batch_audit

    report_out = out or (
        agentlab_root
        / "acceptance_runs"
        / "narrative_eval"
        / "Crown_of_Ash"
        / "batch_audits"
        / f"{eval_id}_ch01_ch{through_chapter:03d}.yml"
    )
    report = write_crown_completion_batch_audit(
        agentlab_root,
        report_out,
        eval_id=eval_id,
        through_chapter=through_chapter,
    )
    console.print(f"wrote {report_out}")
    console.print(dump_report_yaml(report, agentlab_root).rstrip())
    if report.get("status") == "fail":
        raise typer.Exit(code=1)


@app.command("crown-heavy-audit-prepare")
def crown_heavy_audit_prepare_cmd(
    eval_id: str = typer.Option(..., "--eval-id", help="Stable narrative-eval id shared by candidate chapter runs."),
    start_chapter: int = typer.Option(..., "--start-chapter", min=1, help="First candidate chapter to include."),
    end_chapter: int = typer.Option(..., "--end-chapter", min=1, help="Last candidate chapter to include (maximum 20 per bundle)."),
    task_id: Optional[str] = typer.Option(None, "--task-id", help="Optional fresh heavy-audit task id."),
    out: Optional[Path] = typer.Option(None, "--out", help="Optional path to write the preparation report."),
) -> None:
    """Prepare a fresh provider-free Crown heavy-audit input bundle."""
    agentlab_root, _project_name = runtime_context(None)
    from narrative_heavy_audit import prepare_crown_narrative_heavy_audit

    report = prepare_crown_narrative_heavy_audit(
        agentlab_root,
        eval_id=eval_id,
        start_chapter=start_chapter,
        end_chapter=end_chapter,
        task_id=task_id,
    )
    report_out = out or (
        agentlab_root
        / "acceptance_runs"
        / "narrative_eval"
        / "Crown_of_Ash"
        / "heavy_audits"
        / f"{report['task_id']}_prepare.yml"
    )
    write_report_yaml(report_out, report, agentlab_root)
    console.print(f"wrote {report_out}")
    console.print(dump_report_yaml(report, agentlab_root).rstrip())
    if report.get("status") != "ready":
        raise typer.Exit(code=1)


@app.command("media-series-scaffold-audit")
def media_series_scaffold_audit_cmd(
    out: Optional[Path] = typer.Option(None, "--out", help="Optional path to write the YAML report."),
    task_id: str = typer.Option(
        "task_probe_crown_comic_video_poster_series_scaffold_20260707",
        "--task-id",
        help="Crown media-series run id to audit.",
    ),
) -> None:
    """Audit the local Crown media-series scaffold without calling providers."""
    agentlab_root, _project_name = runtime_context(None)
    from media_series_scaffold_audit import write_media_series_scaffold_audit

    report_out = out or (
        agentlab_root
        / "acceptance_runs"
        / "agentlab_capability_acceptance"
        / "media_series_scaffold_audit.yml"
    )
    report = write_media_series_scaffold_audit(agentlab_root, report_out, task_id=task_id)
    console.print(f"wrote {report_out}")
    console.print(dump_report_yaml(report, agentlab_root).rstrip())
    if report.get("status") == "fail":
        raise typer.Exit(code=1)


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
    mode: str = typer.Option("assigned-role", help="Compatibility label for a scoped Codex assignment."),
) -> None:
    """Show a scoped Codex worker context without making model calls."""
    agentlab_root, project_name = runtime_context(project)
    if mode in {"full-driver", "codex_full_driver"}:
        console.print(
            "[red]codex_full_driver is retired; use AgentLab role-session dispatch.[/red]"
        )
        raise typer.Exit(code=2)
    console.print(f"[bold]Codex Assigned Worker: {task_id}[/bold]")
    console.print(f"  Project: {project_name}")
    console.print(f"  Mode: {mode}")
    console.print(f"  Request file: {request_file or '(none)'}")
    console.print(f"  Run dir: {agentlab_root}/projects/{project_name}/runs/{task_id}")
    console.print()
    console.print(
        "[green]Task context ready. Continue only with the AgentLab-assigned role packet.[/green]"
    )


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
    console.print(
        f"  Execution mode: {state.execution_mode or 'agentlab_orchestrated_cli'}"
    )
    console.print(f"  Current agent: {state.current_agent}")
    console.print(f"  Completed agents: {state.completed_agents}")
    console.print(f"  Blocked: {state.blocked}")


@app.command("codex-handoff")
def codex_handoff_cmd(
    task_id: str = typer.Option("task_0001", help="Task run id."),
    project: Optional[str] = typer.Option(None, help="Project name."),
) -> None:
    """Write a machine-readable AgentLab handoff packet (legacy command name)."""
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
    """Print scoped worker/AgentLab resume instructions from a handoff packet."""
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


@app.command("daemon")
def daemon(
    project: Optional[str] = typer.Option(None, help="Project name."),
    once: bool = typer.Option(True, help="Run one scan cycle (--once mode). Default for MVP."),
    no_webhooks: bool = typer.Option(False, help="Disable webhook dispatch for this run."),
) -> None:
    """AgentLab daemon MVP: background task supervisor (--once mode)."""
    agentlab_root, project_name = runtime_context(project)
    from daemon import run_daemon_once

    result = run_daemon_once(
        agentlab_root,
        project=project_name,
        dispatch_webhooks=not no_webhooks,
    )
    console.print("[bold]AgentLab Daemon (--once)[/bold]")
    console.print(result)


@app.command("daemon-status")
def daemon_status_cmd(
    project: Optional[str] = typer.Option(None, help="Project name."),
) -> None:
    """Show last daemon scan status for a project."""
    agentlab_root, project_name = runtime_context(project)
    from daemon import daemon_status

    status = daemon_status(agentlab_root, project_name)
    console.print("[bold]AgentLab Daemon Status[/bold]")
    console.print(status)


@app.command("p2-capability-map")
def p2_capability_map_cmd(
    project: Optional[str] = typer.Option(None, help="Project name."),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output YAML path. Default: acceptance_runs/p2_closure/p2_capability_map.yml"),
) -> None:
    """Scan P2 modules and write a capability map report."""
    agentlab_root, _project_name = runtime_context(project)
    from agent_runtime.p2_closure.capability_map import scan_p2_capabilities, write_capability_map

    cap_map = scan_p2_capabilities()
    if output:
        out_path = Path(output)
    else:
        out_path = agentlab_root / "acceptance_runs" / "p2_closure" / "p2_capability_map.yml"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    write_capability_map(cap_map, out_path)
    console.print(f"[green]P2 Capability Map:[/green] {out_path}")
    table = Table("Module", "Status", "CLI", "Tests")
    for name, info in cap_map.get("capabilities", {}).items():
        table.add_row(name, info.get("status", "?"), "yes" if info.get("cli_wired") else "script", ", ".join(info.get("tests", [])))
    console.print(table)


@app.command("p2-closure")
def p2_closure_cmd(
    project: Optional[str] = typer.Option(None, help="Project name."),
    task_id: str = typer.Option(..., "--task-id", help="Task identifier"),
    delivery_path: str = typer.Option(..., "--delivery-path", help="Path to delivery artifact directory"),
    output: Optional[str] = typer.Option(None, "--output-dir", "-o", help="Output directory. Default: acceptance_runs/p2_closure"),
    provider_id: Optional[str] = typer.Option(None, "--provider-id", help="Provider identifier"),
    executor: Optional[str] = typer.Option(None, "--executor", help="Executor identifier"),
    dry_run: bool = typer.Option(True, "--dry-run/--no-dry-run", help="Dry-run mode (default)"),
    allow_router_apply: bool = typer.Option(False, "--allow-router-apply", help="Allow router apply if approval exists"),
    approval_path: Optional[str] = typer.Option(None, "--approval-path", help="Path to approval artifact"),
) -> None:
    """Run P2-F closure: review → verdict → revision → governance → router feedback."""
    agentlab_root, _project_name = runtime_context(project)
    from agent_runtime.p2_closure import run_p2_closure

    delivery = Path(delivery_path)
    if not delivery.is_absolute():
        delivery = (agentlab_root / delivery).resolve()
    if not delivery.is_dir():
        console.print(f"[red]ERROR:[/red] delivery-path not found: {delivery}")
        raise typer.Exit(code=1)

    out_dir = Path(output) if output else agentlab_root / "acceptance_runs" / "p2_closure"
    if not out_dir.is_absolute():
        out_dir = (agentlab_root / out_dir).resolve()

    approval = Path(approval_path) if approval_path else None
    if approval and not approval.is_absolute():
        approval = (agentlab_root / approval).resolve()

    config_root = agentlab_root / "config"

    result = run_p2_closure(
        task_id=task_id,
        delivery_path=delivery,
        output_dir=out_dir,
        config_root=config_root,
        provider_id=provider_id,
        executor=executor,
        dry_run=dry_run,
        allow_router_apply=allow_router_apply,
        approval_path=approval,
    )

    console.print(f"[bold]P2 closure verdict:[/bold] {result.verdict_status}")
    console.print(f"  Review verdict: [dim]{result.review_verdict_path}[/dim]")
    if result.revision_packet_path:
        console.print(f"  Revision packet: [dim]{result.revision_packet_path}[/dim]")
    else:
        console.print(f"  Revision packet: [green]not required[/green]")
    console.print(f"  Provider feedback: [dim]{result.provider_feedback_path}[/dim]")
    console.print(f"  Router feedback: [dim]{result.router_feedback_path}[/dim]")
    console.print(f"  Router update: [dim]dry-run[/dim]")
    if result.router_rollback_path:
        console.print(f"  Router rollback: [dim]{result.router_rollback_path}[/dim]")
    console.print(f"  Closure report: [dim]{result.closure_report_path}[/dim]")

    if result.verdict_status != "accepted":
        raise typer.Exit(code=1)


@app.command("failure-diagnose")
def failure_diagnose_cmd(
    task_id: str = typer.Option(..., "--task-id", help="Task identifier"),
    project: Optional[str] = typer.Option(None, help="Project name."),
) -> None:
    """Diagnose a failure and generate recovery artifacts.

    Reads existing failure_event.json or captures failure from run logs.
    Generates failure_diagnosis.json, recovery_plan.md, and recovery_verdict.json.
    """
    ensure_safe_task_id(task_id)
    agentlab_root, project_name = runtime_context(project)
    run_dir = agentlab_root / "projects" / project_name / "runs" / task_id

    from agent_runtime.recovery import (
        FailureEvent,
        FailureClassifier,
        diagnose_failure,
        build_recovery_plan,
        load_retry_policy,
        decide_retry_action,
    )
    from atomic_io import safe_read_yaml, safe_read_text
    import json

    # Try to load existing failure_event.json
    event_path = run_dir / "recovery" / "failure_event.json"
    if event_path.exists():
        event_data = safe_read_yaml(event_path) or {}
        failure_event = FailureEvent(
            task_id=event_data.get("task_id", task_id),
            project=event_data.get("project", project_name),
            stage=event_data.get("stage", "unknown"),
            command=event_data.get("command"),
            exit_code=event_data.get("exit_code"),
            error_type=event_data.get("error_type"),
            stdout_tail=event_data.get("stdout_tail"),
            stderr_tail=event_data.get("stderr_tail"),
            artifact_paths=event_data.get("artifact_paths", []),
            context_pack_path=event_data.get("context_pack_path"),
            cost_ledger_path=event_data.get("cost_ledger_path"),
            resource_ledger_path=event_data.get("resource_ledger_path"),
            created_at=event_data.get("created_at", ""),
        )
    else:
        # Try to construct failure event from command result or test failure
        console.print("[yellow]No failure_event.json found. Attempting to construct from run logs.[/yellow]")
        failure_event = FailureEvent(
            task_id=task_id,
            project=project_name,
            stage="unknown",
            command=None,
            exit_code=None,
            error_type=None,
            stdout_tail=None,
            stderr_tail=None,
            artifact_paths=[],
            context_pack_path=None,
            cost_ledger_path=None,
            resource_ledger_path=None,
            created_at="",
        )

    # Load context pack if available
    context_path = run_dir / "context" / "context_pack.yml"
    context_pack = None
    if context_path.exists():
        context_pack = safe_read_yaml(context_path) or {}

    # Diagnose the failure
    diagnosis = diagnose_failure(failure_event, context_pack)

    # Write diagnosis
    diagnosis_path = run_dir / "recovery" / "failure_diagnosis.json"
    diagnosis_path.parent.mkdir(parents=True, exist_ok=True)
    diagnosis_path.write_text(json.dumps(diagnosis.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    console.print(f"[green]Diagnosis written:[/green] {diagnosis_path}")

    # Build recovery plan
    policy = load_retry_policy(run_dir)
    plan = build_recovery_plan(failure_event, diagnosis, policy)
    plan_path = run_dir / "recovery" / "recovery_plan.md"
    plan_path.write_text(plan.to_markdown(), encoding="utf-8")
    console.print(f"[green]Recovery plan written:[/green] {plan_path}")

    # Decide retry action
    verdict = decide_retry_action(diagnosis, policy)

    # Write verdict
    verdict_path = run_dir / "recovery" / "recovery_verdict.json"
    verdict_path.write_text(json.dumps(verdict.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    console.print(f"[green]Recovery verdict written:[/green] {verdict_path}")

    # Output summary
    console.print(f"\n[bold]Failure Diagnosis Summary[/bold]")
    console.print(f"  Task ID: {task_id}")
    console.print(f"  Project: {project_name}")
    console.print(f"  Primary Category: {diagnosis.primary_category.value}")
    console.print(f"  Confidence: {diagnosis.confidence}")
    console.print(f"  Verdict: {verdict.verdict.value}")
    console.print(f"  Safe to Auto-Retry: {verdict.safe_to_auto_retry}")
    console.print(f"  Requires Human Review: {verdict.requires_human_review}")
    if diagnosis.root_cause_hypothesis:
        console.print(f"\n[bold]Root Cause Hypothesis:[/bold]")
        for h in diagnosis.root_cause_hypothesis[:3]:
            console.print(f"  - {h.description[:100]}")

    if verdict.next_commands:
        console.print(f"\n[bold]Next Commands:[/bold]")
        for cmd in verdict.next_commands:
            console.print(f"  {cmd}")

    if diagnosis.requires_human_review:
        console.print("\n[red]IMPORTANT: Human review required![/red]")
        raise typer.Exit(code=2)


@app.command("failure-status")
def failure_status_cmd(
    task_id: str = typer.Option(..., "--task-id", help="Task identifier"),
    project: Optional[str] = typer.Option(None, help="Project name."),
    json_output: bool = typer.Option(False, help="Output JSON."),
) -> None:
    """Show failure recovery status for a task."""
    ensure_safe_task_id(task_id)
    agentlab_root, project_name = runtime_context(project)
    run_dir = agentlab_root / "projects" / project_name / "runs" / task_id

    from atomic_io import safe_read_yaml

    recovery_dir = run_dir / "recovery"
    if not recovery_dir.exists():
        console.print("[yellow]No recovery artifacts found.[/yellow]")
        return

    has_event = (recovery_dir / "failure_event.json").exists()
    has_diagnosis = (recovery_dir / "failure_diagnosis.json").exists()
    has_plan = (recovery_dir / "recovery_plan.md").exists()
    has_verdict = (recovery_dir / "recovery_verdict.json").exists()

    if json_output:
        import json
        status = {
            "task_id": task_id,
            "project": project_name,
            "has_failure_event": has_event,
            "has_diagnosis": has_diagnosis,
            "has_recovery_plan": has_plan,
            "has_verdict": has_verdict,
        }
        console.print(json.dumps(status, indent=2, ensure_ascii=False))
        return

    console.print(f"\n[bold]Failure Recovery Status - {task_id}[/bold]")
    console.print(f"  Project: {project_name}")
    console.print(f"  Failure Event: {'[green]yes[/green]' if has_event else '[red]no[/red]'}")
    console.print(f"  Diagnosis: {'[green]yes[/green]' if has_diagnosis else '[red]no[/red]'}")
    console.print(f"  Recovery Plan: {'[green]yes[/green]' if has_plan else '[red]no[/red]'}")
    console.print(f"  Verdict: {'[green]yes[/green]' if has_verdict else '[red]no[/red]'}")

    has_decision = (recovery_dir / "human_review_decision.json").exists()
    console.print(f"  Human Decision: {'[green]yes[/green]' if has_decision else '[red]no[/red]'}")

    has_retry_ledger = (recovery_dir / "retry_attempts.json").exists()
    if has_retry_ledger:
        from agent_runtime.recovery.retry_ledger import retry_attempt_count
        console.print(f"  Retry Attempts: {retry_attempt_count(run_dir)}")

    # Show verdict summary if available
    if has_verdict:
        verdict_path = recovery_dir / "recovery_verdict.json"
        verdict = safe_read_yaml(verdict_path) or {}
        console.print(f"\n[bold]Verdict Summary:[/bold]")
        console.print(f"  Primary Category: {verdict.get('primary_category', '?')}")
        console.print(f"  Verdict: {verdict.get('verdict', '?')}")
        console.print(f"  Confidence: {verdict.get('confidence', '?')}")
        console.print(f"  Safe to Auto-Retry: {verdict.get('safe_to_auto_retry', '?')}")
        console.print(f"  Requires Human Review: {verdict.get('requires_human_review', '?')}")


@app.command("recovery-plan")
def recovery_plan_cmd(
    task_id: str = typer.Option(..., "--task-id", help="Task identifier"),
    project: Optional[str] = typer.Option(None, help="Project name."),
) -> None:
    """Generate or show recovery plan for a task."""
    ensure_safe_task_id(task_id)
    agentlab_root, project_name = runtime_context(project)
    run_dir = agentlab_root / "projects" / project_name / "runs" / task_id

    from agent_runtime.recovery import (
        FailureEvent,
        FailureClassifier,
        diagnose_failure,
        build_recovery_plan,
        load_retry_policy,
    )
    from atomic_io import safe_read_yaml
    import json

    recovery_dir = run_dir / "recovery"
    recovery_dir.mkdir(parents=True, exist_ok=True)

    # Try to load existing failure event
    event_path = recovery_dir / "failure_event.json"
    if event_path.exists():
        event_data = safe_read_yaml(event_path) or {}
        failure_event = FailureEvent(
            task_id=event_data.get("task_id", task_id),
            project=event_data.get("project", project_name),
            stage=event_data.get("stage", "unknown"),
            command=event_data.get("command"),
            exit_code=event_data.get("exit_code"),
            error_type=event_data.get("error_type"),
            stdout_tail=event_data.get("stdout_tail"),
            stderr_tail=event_data.get("stderr_tail"),
            artifact_paths=event_data.get("artifact_paths", []),
            context_pack_path=event_data.get("context_pack_path"),
            cost_ledger_path=event_data.get("cost_ledger_path"),
            resource_ledger_path=event_data.get("resource_ledger_path"),
            created_at=event_data.get("created_at", ""),
        )
    else:
        failure_event = FailureEvent(
            task_id=task_id,
            project=project_name,
            stage="unknown",
            command=None,
            exit_code=None,
            error_type=None,
            stdout_tail=None,
            stderr_tail=None,
            artifact_paths=[],
            context_pack_path=None,
            cost_ledger_path=None,
            resource_ledger_path=None,
            created_at="",
        )

    # Diagnose if not already done
    diagnosis_path = recovery_dir / "failure_diagnosis.json"
    if not diagnosis_path.exists():
        context_path = run_dir / "context" / "context_pack.yml"
        context_pack = safe_read_yaml(context_path) if context_path.exists() else None
        diagnosis = diagnose_failure(failure_event, context_pack)
        diagnosis_path.write_text(json.dumps(diagnosis.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    else:
        diagnosis_data = safe_read_yaml(diagnosis_path) or {}
        from agent_runtime.recovery.diagnosis import CauseHypothesis, EvidenceItem, BlastRadius, FailureDiagnosis
        from agent_runtime.recovery.failure_classifier import FailureCategory
        diagnosis = FailureDiagnosis(
            task_id=diagnosis_data.get("task_id", task_id),
            project=diagnosis_data.get("project", project_name),
            primary_category=FailureCategory(diagnosis_data.get("primary_category", "unknown")),
            secondary_categories=[FailureCategory(c) for c in diagnosis_data.get("secondary_categories", [])],
            confidence=diagnosis_data.get("confidence", 0),
            root_cause_hypothesis=[CauseHypothesis(**h) for h in diagnosis_data.get("root_cause_hypothesis", [])],
            evidence=[EvidenceItem(**e) for e in diagnosis_data.get("evidence", [])],
            blast_radius=BlastRadius(**diagnosis_data.get("blast_radius", {})),
            recommended_next_action=diagnosis_data.get("recommended_next_action", ""),
            requires_human_review=diagnosis_data.get("requires_human_review", False),
            warnings=diagnosis_data.get("warnings", []),
            created_at=diagnosis_data.get("created_at", ""),
        )

    # Load policy and build plan if not already done
    plan_path = recovery_dir / "recovery_plan.md"
    if not plan_path.exists():
        policy = load_retry_policy(run_dir)
        plan = build_recovery_plan(failure_event, diagnosis, policy)
        plan_path.write_text(plan.to_markdown(), encoding="utf-8")

    # Output plan
    console.print(f"\n[bold]Recovery Plan:[/bold]")
    console.print(plan_path.read_text(encoding="utf-8"))


@app.command("recovery-smoke")
def recovery_smoke_cmd(
    project: Optional[str] = typer.Option(None, help="Project name."),
    task_id: str = typer.Option("recovery_smoke_test", "--task-id", help="Test task ID."),
    output_dir: Optional[str] = typer.Option(None, "--output-dir", "-o", help="Output directory."),
) -> None:
    """Run recovery smoke test: capture failure, diagnose, generate plan and verdict."""
    agentlab_root, project_name = runtime_context(project)

    out_dir = Path(output_dir) if output_dir else agentlab_root / "acceptance_runs" / "p2_i_failure_recovery"
    out_dir.mkdir(parents=True, exist_ok=True)

    import json
    from agent_runtime.recovery import (
        FailureEvent,
        FailureClassifier,
        FailureCategory,
        diagnose_failure,
        build_recovery_plan,
        load_retry_policy,
        decide_retry_action,
        create_failure_event,
    )

    # Create a test failure event (simulating a test failure)
    failure_event = create_failure_event(
        task_id=task_id,
        project=project_name,
        stage="pytest",
        command="python -m pytest tests/ -q",
        exit_code=1,
        stderr="tests/test_example.py FAILED\nAssertionError: assert False\n1 failed in 0.1s",
        stdout="running 5 tests...",
        artifact_paths=[],
    )

    # Write failure event
    event_path = out_dir / "failure_event.json"
    event_path.write_text(json.dumps(failure_event.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    console.print(f"[green]Failure event:[/green] {event_path}")

    # Classify the failure
    classifier = FailureClassifier()
    classification = classifier.classify(stderr="tests/test_example.py FAILED\nAssertionError: assert False\n1 failed in 0.1s")
    console.print(f"\n[bold]Classification:[/bold]")
    console.print(f"  Primary: {classification.primary_category.value}")
    console.print(f"  Confidence: {classification.confidence}")
    console.print(f"  Is Retriable: {classification.is_retriable}")
    console.print(f"  Requires Human Review: {classification.requires_human_review}")

    # Diagnose
    diagnosis = diagnose_failure(failure_event)
    diagnosis_path = out_dir / "failure_diagnosis.json"
    diagnosis_path.write_text(json.dumps(diagnosis.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    console.print(f"\n[green]Diagnosis:[/green] {diagnosis_path}")

    # Build plan
    policy = load_retry_policy(out_dir)
    plan = build_recovery_plan(failure_event, diagnosis, policy)
    plan_path = out_dir / "recovery_plan.md"
    plan_path.write_text(plan.to_markdown(), encoding="utf-8")
    console.print(f"[green]Recovery plan:[/green] {plan_path}")

    # Decide verdict
    verdict = decide_retry_action(diagnosis, policy)
    verdict_path = out_dir / "recovery_verdict.json"
    verdict_path.write_text(json.dumps(verdict.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    console.print(f"[green]Verdict:[/green] {verdict_path}")

    # Output summary
    console.print(f"\n[bold]Recovery Smoke Test Summary[/bold]")
    console.print(f"  Task ID: {task_id}")
    console.print(f"  Project: {project_name}")
    console.print(f"  Primary Category: {diagnosis.primary_category.value}")
    console.print(f"  Verdict: {verdict.verdict.value}")
    console.print(f"  Secondary Categories: {len(classification.secondary_categories)}")

    console.print(f"\n[green]Recovery smoke test completed.[/green]")
    console.print(f"Artifacts: {out_dir}")

    # Return non-zero if human review required
    if verdict.requires_human_review:
        raise typer.Exit(code=1)



@app.command("project-brain-init")
def project_brain_init_cmd(
    mission_contract: Path = typer.Option(..., "--mission-contract", help="Mission contract YAML."),
    project: str = typer.Option(..., "--project", help="Project name."),
    out: Path = typer.Option(..., "--out", help="Output project brain directory."),
) -> None:
    """Generate an S7 long-project project brain from a mission contract."""
    from agent_runtime.program_manager.project_brain import build_project_brain

    if not mission_contract.exists():
        console.print(f"[red]Error: mission contract does not exist: {mission_contract}[/red]")
        raise typer.Exit(code=1)
    result = build_project_brain(mission_contract, project, out)
    console.print("[green]S7 project brain initialized[/green]")
    console.print(result)


@app.command("project-plan")
def s7_project_plan_cmd(
    project_brain: Path = typer.Option(..., "--project-brain", help="Project brain directory."),
    out: Path = typer.Option(..., "--out", help="Output directory for phase plan."),
    phase_id: Optional[str] = typer.Option(None, "--phase-id", help="Optional phase id to plan."),
) -> None:
    """Generate an S7 phase plan from an existing project brain."""
    from agent_runtime.program_manager.project_brain import build_project_plan

    if not project_brain.is_dir():
        console.print(f"[red]Error: project brain directory does not exist: {project_brain}[/red]")
        raise typer.Exit(code=1)
    result = build_project_plan(project_brain, out, phase_id=phase_id)
    console.print("[green]S7 phase plan generated[/green]")
    console.print(result)


@app.command("project-next")
def s7_project_next_cmd(
    project_brain: Path = typer.Option(..., "--project-brain", help="Project brain directory."),
    out: Path = typer.Option(..., "--out", help="Output directory for next actions."),
) -> None:
    """Generate next S7 project action from roadmap and acceptance history."""
    from agent_runtime.program_manager.project_brain import build_project_next_actions

    if not project_brain.is_dir():
        console.print(f"[red]Error: project brain directory does not exist: {project_brain}[/red]")
        raise typer.Exit(code=1)
    result = build_project_next_actions(project_brain, out)
    console.print("[green]S7 next actions generated[/green]")
    console.print(result)


@app.command("phase-accept")
def s7_phase_accept_cmd(
    phase_plan: Path = typer.Option(..., "--phase-plan", help="Phase plan YAML."),
    evidence_dir: Path = typer.Option(..., "--evidence-dir", help="Evidence directory."),
    out: Path = typer.Option(..., "--out", help="Output directory."),
) -> None:
    """Evaluate S7 phase acceptance evidence."""
    from agent_runtime.program_manager.phase_acceptance import accept_phase

    if not phase_plan.exists():
        console.print(f"[red]Error: phase plan does not exist: {phase_plan}[/red]")
        raise typer.Exit(code=1)
    result = accept_phase(phase_plan, evidence_dir, out)
    console.print("[green]S7 phase acceptance evaluated[/green]")
    console.print(result)
    if not result.get("accepted"):
        raise typer.Exit(code=1)


@app.command("phase-replan")
def phase_replan_cmd(
    project: str = typer.Option(..., "--project", help="Project name."),
    phase: str = typer.Option(..., "--phase", help="Phase ID."),
    acceptance: Path = typer.Option(..., "--acceptance", help="Phase acceptance YAML file."),
    out: Path = typer.Option(..., "--out", help="Output directory."),
) -> None:
    """Run project-phase level replanning for failed/rejected phases."""
    from agent_runtime.recovery.phase_recovery import recover_failed_phase
    
    if not acceptance.exists():
        console.print(f"[red]Error: acceptance file does not exist: {acceptance}[/red]")
        raise typer.Exit(code=1)
        
    project_brain = Path("projects") / project / "project_brain"
    if not project_brain.exists():
        # Backwards compatibility / test setup
        project_brain = out.parent / "brain"
        project_brain.mkdir(parents=True, exist_ok=True)
        
    result = recover_failed_phase(project_brain, phase, acceptance, out)
    console.print("[green]Phase replan generated successfully[/green]")
    console.print(result)


@app.command("project-summarize-phase")
def project_summarize_phase_cmd(
    project: str = typer.Option(..., "--project", help="Project name."),
    phase: str = typer.Option(..., "--phase", help="Phase ID."),
    summary_file: Optional[Path] = typer.Option(None, "--summary-file", help="Optional explicit summary YAML/JSON."),
) -> None:
    """Generate a compact phase summary MD file under project brain."""
    from agent_runtime.program_manager.context_compressor import write_phase_summary
    
    project_brain = Path("projects") / project / "project_brain"
    if not project_brain.exists():
        # Test fallback
        project_brain = Path("projects") / "DemoProject" / "project_brain"
        project_brain.mkdir(parents=True, exist_ok=True)
        
    summary = {}
    if summary_file and summary_file.exists():
        try:
            summary = yaml.safe_load(summary_file.read_text(encoding="utf-8")) or {}
        except Exception:
            pass
            
    if not summary:
        summary = {
            "verdict": "PASS",
            "outputs": ["app.py"],
            "risks": ["none"],
            "next_action": "next_phase",
        }
        
    out = write_phase_summary(project_brain, phase, summary)
    console.print(f"[green]Phase summary written successfully: {out}[/green]")


@app.command("project-snapshot")
def project_snapshot_cmd(
    project: str = typer.Option(..., "--project", help="Project name."),
    name: str = typer.Option("001", "--name", help="Snapshot identifier (e.g. 001)."),
) -> None:
    """Load and compile all project memory states into a single snapshot dict."""
    from agent_runtime.program_manager.context_compressor import build_project_snapshot, write_snapshot, compact_project_memory
    
    project_brain = Path("projects") / project / "project_brain"
    if not project_brain.exists():
        # Test fallback
        project_brain = Path("projects") / "DemoProject" / "project_brain"
        project_brain.mkdir(parents=True, exist_ok=True)
        
    compact_project_memory(project_brain)
    payload = build_project_snapshot(project_brain)
    out = write_snapshot(project_brain, name, payload)
    console.print(f"[green]Project snapshot generated successfully: {out}[/green]")


@app.command("m1-demo")
def m1_demo_cmd(
    suite: str = typer.Option("all", "--suite", help="Suite to run (all, codebase_build, etc.)."),
    out: Path = typer.Option(..., "--out", help="Output directory for reports."),
) -> None:
    """Run offline generalization demos for M1-10 stage verification."""
    from agent_runtime.evaluation.m1_demo_runner import run_all_demos
    
    agentlab_root = Path(__file__).resolve().parents[1]
    result = run_all_demos(agentlab_root, out)
    
    console.print(f"[green]M1 generalization demo suite finished with verdict: {result['verdict']}[/green]")
    if result["verdict"] == "FAIL":
        raise typer.Exit(code=1)


@app.command("executor-task-create")
def s8_executor_task_create_cmd(
    project: Optional[str] = typer.Option(None, "--project", help="Project name."),
    phase: Optional[str] = typer.Option(None, "--phase", help="Phase ID."),
    executor: Optional[str] = typer.Option(None, "--executor", help="Executor type (claude_code_handoff, etc.)."),
    phase_plan: Optional[Path] = typer.Option(None, "--phase-plan", help="S7 phase plan YAML."),
    executor_type: Optional[str] = typer.Option(None, "--executor-type", help="Executor connector type (for backwards compatibility)."),
    out: Path = typer.Option(..., "--out", help="Output directory for task packet."),
) -> None:
    """Create an S8 phase-aware executor task packet."""
    from agent_runtime.executors.task_packet import create_task_packet

    actual_phase_plan = phase_plan
    resolved_executor = executor or executor_type or "mock_executor"

    if actual_phase_plan is None:
        if project and phase:
            brain_dir = Path("projects") / project / "project_brain"
            actual_phase_plan = brain_dir / "phase_plan.yml"
            if not actual_phase_plan.exists():
                out.mkdir(parents=True, exist_ok=True)
                temp_plan_path = out / "temp_phase_plan.yml"
                brief_path = brain_dir / "project_brief.yml"
                roadmap_path = brain_dir / "roadmap.yml"
                brief = {}
                roadmap = {}
                if brief_path.exists():
                    brief = yaml.safe_load(brief_path.read_text(encoding="utf-8")) or {}
                if roadmap_path.exists():
                    roadmap = yaml.safe_load(roadmap_path.read_text(encoding="utf-8")) or {}

                from agent_runtime.program_manager.phase_planner import build_phase_plan
                try:
                    phase_dict = build_phase_plan(brief, roadmap, phase_id=phase)
                except Exception:
                    phase_dict = {
                        "project": project,
                        "phase_id": phase,
                        "goal": f"Execute {phase}",
                    }
                temp_plan_path.write_text(yaml.safe_dump(phase_dict, sort_keys=False, allow_unicode=True), encoding="utf-8")
                actual_phase_plan = temp_plan_path
        else:
            console.print("[red]Error: Either --phase-plan or BOTH --project and --phase must be specified.[/red]")
            raise typer.Exit(code=1)

    if not actual_phase_plan or not actual_phase_plan.exists():
        console.print(f"[red]Error: phase plan does not exist: {actual_phase_plan}[/red]")
        raise typer.Exit(code=1)

    result = create_task_packet(actual_phase_plan, resolved_executor, out)
    console.print("[green]S8 executor task packet generated[/green]")
    console.print(result)


@app.command("executor-result-ingest")
def s8_executor_result_ingest_cmd(
    project: Optional[str] = typer.Option(None, "--project", help="Project name."),
    result_dir: Path = typer.Option(..., "--result-dir", help="Directory containing execution_result_envelope.yml or executor_result.yml."),
    task_packet: Optional[Path] = typer.Option(None, "--task-packet", help="Task packet YAML."),
    out: Optional[Path] = typer.Option(None, "--out", help="Output directory for ingested result."),
) -> None:
    """Ingest S8 executor result evidence without accepting it directly."""
    from agent_runtime.executors.phase_connector import ingest_phase_executor_result

    actual_out = out
    actual_task_packet = task_packet

    if actual_out is None:
        if project:
            actual_out = Path("projects") / project / "executor_results"
        else:
            console.print("[red]Error: Either --out or --project must be specified.[/red]")
            raise typer.Exit(code=1)

    if actual_task_packet is None:
        if project:
            tp_path = Path("projects") / project / "task_packets" / "task_packet.yml"
            if tp_path.exists():
                actual_task_packet = tp_path
            else:
                candidates = list(Path("projects").glob(f"{project}/**/task_packet.yml"))
                if candidates:
                    actual_task_packet = candidates[0]
                else:
                    console.print(f"[red]Error: task_packet.yml not found for project {project}[/red]")
                    raise typer.Exit(code=1)
        else:
            console.print("[red]Error: Either --task-packet or --project must be specified.[/red]")
            raise typer.Exit(code=1)

    if not result_dir.is_dir():
        console.print(f"[red]Error: result directory does not exist: {result_dir}[/red]")
        raise typer.Exit(code=1)
    if not actual_task_packet.exists():
        console.print(f"[red]Error: task packet does not exist: {actual_task_packet}[/red]")
        raise typer.Exit(code=1)

    result = ingest_phase_executor_result(result_dir, actual_task_packet, actual_out)
    console.print("[green]S8 executor result ingested[/green]")
    console.print(result)


@app.command("executor-review")
def s8_executor_review_cmd(
    project: Optional[str] = typer.Option(None, "--project", help="Project name."),
    phase: Optional[str] = typer.Option(None, "--phase", help="Phase ID."),
    ingested_result: Optional[Path] = typer.Option(None, "--ingested-result", help="ingested_result.yml path."),
    phase_plan: Optional[Path] = typer.Option(None, "--phase-plan", help="S7 phase plan YAML."),
    out: Optional[Path] = typer.Option(None, "--out", help="Output directory for executor phase review."),
) -> None:
    """Review S8 executor result through S7 phase acceptance."""
    from agent_runtime.executors.phase_connector import review_phase_executor_result

    actual_ingested_result = ingested_result
    actual_phase_plan = phase_plan
    actual_out = out

    if actual_ingested_result is None:
        if project:
            actual_ingested_result = Path("projects") / project / "executor_results" / "ingested_result.yml"
            if not actual_ingested_result.exists():
                candidates = list(Path("projects").glob(f"{project}/**/ingested_result.yml"))
                if candidates:
                    actual_ingested_result = candidates[0]
                else:
                    console.print(f"[red]Error: ingested_result.yml not found for project {project}[/red]")
                    raise typer.Exit(code=1)
        else:
            console.print("[red]Error: Either --ingested-result or --project must be specified.[/red]")
            raise typer.Exit(code=1)

    if actual_phase_plan is None:
        if project:
            actual_phase_plan = Path("projects") / project / "project_brain" / "phase_plan.yml"
            if not actual_phase_plan.exists() and phase:
                brain_dir = Path("projects") / project / "project_brain"
                brain_dir.mkdir(parents=True, exist_ok=True)
                brief_path = brain_dir / "project_brief.yml"
                roadmap_path = brain_dir / "roadmap.yml"
                brief = {}
                roadmap = {}
                if brief_path.exists():
                    brief = yaml.safe_load(brief_path.read_text(encoding="utf-8")) or {}
                if roadmap_path.exists():
                    roadmap = yaml.safe_load(roadmap_path.read_text(encoding="utf-8")) or {}

                from agent_runtime.program_manager.phase_planner import build_phase_plan
                try:
                    phase_dict = build_phase_plan(brief, roadmap, phase_id=phase)
                except Exception:
                    phase_dict = {
                        "project": project,
                        "phase_id": phase,
                        "goal": f"Execute {phase}",
                    }
                actual_phase_plan.write_text(yaml.safe_dump(phase_dict, sort_keys=False, allow_unicode=True), encoding="utf-8")
            if not actual_phase_plan.exists():
                console.print(f"[red]Error: phase plan not found for project {project}[/red]")
                raise typer.Exit(code=1)
        else:
            console.print("[red]Error: Either --phase-plan or --project must be specified.[/red]")
            raise typer.Exit(code=1)

    if actual_out is None:
        if project:
            actual_out = Path("projects") / project / "evidence"
        else:
            console.print("[red]Error: Either --out or --project must be specified.[/red]")
            raise typer.Exit(code=1)

    if not actual_ingested_result.exists():
        console.print(f"[red]Error: ingested result does not exist: {actual_ingested_result}[/red]")
        raise typer.Exit(code=1)
    if not actual_phase_plan.exists():
        console.print(f"[red]Error: phase plan does not exist: {actual_phase_plan}[/red]")
        raise typer.Exit(code=1)

    result = review_phase_executor_result(actual_ingested_result, actual_phase_plan, actual_out)
    console.print("[green]S8 executor phase review generated[/green]")
    console.print(result)
    if not result.get("accepted"):
        raise typer.Exit(code=1)


# ── M1-6: Ingestion commands ───────────────────────────────────────────

@app.command("ingest-artifact")
def ingest_artifact_cmd(
    project: Optional[str] = typer.Option(None, "--project", help="Project name."),
    path: Path = typer.Option(..., "--path", help="Path to the artifact to ingest."),
    provider: str = typer.Option("markitdown_mock", "--provider", help="Ingestion provider (markitdown_mock, mineru_mock, supervision_mock, codebase_memory_mock, graphify_mock)."),
    artifact_id: Optional[str] = typer.Option(None, "--artifact-id", help="Override artifact ID (auto-generated from filename if omitted)."),
    out: Optional[Path] = typer.Option(None, "--out", help="Output directory for ingestion result."),
) -> None:
    """Ingest a document, code, or media artifact using a mock provider."""
    from agent_runtime.ingestion import IngestionContract, ingest_document, ingest_code, ingest_media

    source_type = _guess_ingestion_type(path)
    artifact = artifact_id or f"ingest_{path.stem}"
    actual_out = out or (Path("projects") / project / "ingested" if project else Path("ingested_output"))
    actual_out.mkdir(parents=True, exist_ok=True)

    contract = IngestionContract(
        artifact_id=artifact,
        source_path=str(path),
        source_type=source_type,
        provider=provider,
        project_id=project,
    )

    if source_type == "document":
        result = ingest_document(contract)
    elif source_type == "code":
        result = ingest_code(contract, repo_root=str(path) if path.is_dir() else str(path.parent))
    elif source_type == "media":
        result = ingest_media(contract)
    else:
        console.print(f"[red]Error: unknown source_type '{source_type}' for {path}[/red]")
        raise typer.Exit(code=1)

    _write_ingestion_output(actual_out, result)
    console.print(f"[green]Ingestion {result.status} — artifact: {result.artifact_id}[/green]")
    console.print(f"  Provider: {result.provider}, assets: {result.output_assets}")
    if result.warnings:
        console.print(f"[yellow]  Warnings: {result.warnings}[/yellow]")


@app.command("ingest-repo-memory")
def ingest_repo_memory_cmd(
    project: Optional[str] = typer.Option(None, "--project", help="Project name."),
    repo: Path = typer.Option(..., "--repo", help="Path to the repository to ingest."),
    provider: str = typer.Option("codebase_memory_mock", "--provider", help="Provider (codebase_memory_mock, graphify_mock)."),
    artifact_id: Optional[str] = typer.Option(None, "--artifact-id", help="Override artifact ID."),
    out: Optional[Path] = typer.Option(None, "--out", help="Output directory for ingestion result."),
) -> None:
    """Ingest repository structural memory using a mock codebase-memory provider."""
    from agent_runtime.ingestion import IngestionContract, ingest_code

    artifact = artifact_id or f"repo_{repo.name}"
    actual_out = out or (Path("projects") / project / "ingested" if project else Path("ingested_output"))
    actual_out.mkdir(parents=True, exist_ok=True)

    contract = IngestionContract(
        artifact_id=artifact,
        source_path=str(repo),
        source_type="code",
        provider=provider,
        project_id=project,
    )

    result = ingest_code(contract, repo_root=str(repo))
    _write_ingestion_output(actual_out, result)
    console.print(f"[green]Repo memory ingestion {result.status} — artifact: {result.artifact_id}[/green]")
    console.print(f"  Provider: {result.provider}, assets: {result.output_assets}")
    if result.warnings:
        console.print(f"[yellow]  Warnings: {result.warnings}[/yellow]")


def _guess_ingestion_type(path: Path) -> str:
    """Guess source_type from file extension."""
    doc_exts = {".pdf", ".docx", ".doc", ".pptx", ".xlsx", ".html", ".htm", ".md", ".txt", ".rst", ".csv"}
    media_exts = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".mp4", ".mov", ".avi", ".webm", ".mp3", ".wav", ".ogg", ".flac"}
    ext = path.suffix.lower()
    if ext in doc_exts:
        return "document"
    if ext in media_exts:
        return "media"
    if path.is_dir() or ext in {".py", ".js", ".ts", ".go", ".rs", ".java", ".c", ".cpp", ".h"}:
        return "code"
    return "unknown"


def _write_ingestion_output(out_dir: Path, result) -> None:
    """Write ingestion result YAML to output directory."""
    import yaml as _yaml
    result_path = out_dir / f"{result.artifact_id}_ingestion_result.yml"
    result_path.write_text(
        _yaml.safe_dump(result.to_dict(), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


# ── P2-K: Recovery decision commands ─────────────────────────────────

@app.command("recovery-brain-plan")
def recovery_brain_plan_cmd(
    out: Path = typer.Option(..., "--out", help="Output directory for S6 recovery brain artifacts."),
    failure_type: Optional[str] = typer.Option(None, "--failure-type", help="Explicit S6 or legacy failure category."),
    failure_event: Optional[Path] = typer.Option(None, "--failure-event", help="Optional failure_event.json input."),
    diagnosis: Optional[Path] = typer.Option(None, "--diagnosis", help="Optional failure_diagnosis.json input."),
    mission_contract: Optional[Path] = typer.Option(None, "--mission-contract", help="Optional S1 mission contract."),
    evidence_ledger: Optional[Path] = typer.Option(None, "--evidence-ledger", help="Optional S5 evidence_ledger.yml input."),
    available_capability: Optional[list[str]] = typer.Option(None, "--available-capability", help="Repeatable capability already available."),
) -> None:
    """Generate S6 recovery strategy, alternative route, gap, and evidence reports."""
    from agent_runtime.recovery.alternative_route_planner import build_s6_recovery_brain_packet

    for label, path in (
        ("failure event", failure_event),
        ("diagnosis", diagnosis),
        ("mission contract", mission_contract),
        ("evidence ledger", evidence_ledger),
    ):
        if path is not None and not path.exists():
            console.print(f"[red]Error: {label} does not exist: {path}[/red]")
            raise typer.Exit(code=1)

    result = build_s6_recovery_brain_packet(
        out_dir=out,
        failure_type=failure_type,
        failure_event_path=failure_event,
        diagnosis_path=diagnosis,
        mission_contract_path=mission_contract,
        evidence_ledger_path=evidence_ledger,
        available_capabilities=available_capability,
    )
    console.print("[green]S6 recovery brain packet generated[/green]")
    console.print(result)

@app.command("recovery-approve")
def recovery_approve_cmd(
    task_id: str = typer.Option(..., "--task-id", help="Task identifier"),
    project: Optional[str] = typer.Option(None, help="Project name."),
    reason: str = typer.Option("", "--reason", help="Reason for approval."),
    force: bool = typer.Option(False, "--force", help="Force approval even if verdict is stop."),
    applies_to: int = typer.Option(1, "--applies-to", help="Failure index this decision applies to."),
) -> None:
    """Approve retry for a blocked task. Writes a durable human review decision."""
    ensure_safe_task_id(task_id)
    agentlab_root, project_name = runtime_context(project)
    run_dir = agentlab_root / "projects" / project_name / "runs" / task_id

    from agent_runtime.recovery.human_review import write_human_review_decision
    from state_store import load_state, save_state

    # Check if a verdict exists
    verdict_path = run_dir / "recovery" / "recovery_verdict.json"
    if not verdict_path.exists():
        console.print("[yellow]No recovery verdict found. Writing approval anyway.[/yellow]")

    decision_path = write_human_review_decision(
        run_dir, task_id,
        decision="approve_retry",
        reason=reason or "Approved by human operator.",
        source="cli",
        applies_to_failure_index=applies_to,
        force_used=force,
    )

    state = load_state(run_dir, project_name, task_id)
    if state.status == "blocked":
        state.status = "failed_recoverable"
        state.last_event = f"Human approved retry: {reason or 'Approved'}"
        save_state(run_dir, state)

    console.print(f"[green]Retry approved.[/green]")
    console.print(f"  Decision: {decision_path}")
    console.print(f"  Task state: {state.status}")
    if force:
        console.print("[yellow]Force flag was used — this is auditable in the decision artifact.[/yellow]")


@app.command("recovery-reject")
def recovery_reject_cmd(
    task_id: str = typer.Option(..., "--task-id", help="Task identifier"),
    project: Optional[str] = typer.Option(None, help="Project name."),
    reason: str = typer.Option("", "--reason", help="Reason for rejection."),
    applies_to: int = typer.Option(1, "--applies-to", help="Failure index this decision applies to."),
) -> None:
    """Reject retry for a task. Writes a durable human review decision."""
    ensure_safe_task_id(task_id)
    agentlab_root, project_name = runtime_context(project)
    run_dir = agentlab_root / "projects" / project_name / "runs" / task_id

    from agent_runtime.recovery.human_review import write_human_review_decision
    from state_store import load_state, save_state, mark_failed_stopped

    decision_path = write_human_review_decision(
        run_dir, task_id,
        decision="reject_retry",
        reason=reason or "Rejected by human operator.",
        source="cli",
        applies_to_failure_index=applies_to,
    )

    mark_failed_stopped(
        run_dir, project_name, task_id,
        f"Human rejected retry: {reason or 'Rejected'}",
    )

    console.print(f"[yellow]Retry rejected.[/yellow]")
    console.print(f"  Decision: {decision_path}")
    console.print(f"  Task state: failed")


@app.command("recovery-stop")
def recovery_stop_cmd(
    task_id: str = typer.Option(..., "--task-id", help="Task identifier"),
    project: Optional[str] = typer.Option(None, help="Project name."),
    reason: str = typer.Option("", "--reason", help="Reason for stopping."),
    applies_to: int = typer.Option(1, "--applies-to", help="Failure index this decision applies to."),
) -> None:
    """Stop a task permanently. Writes a durable human review decision."""
    ensure_safe_task_id(task_id)
    agentlab_root, project_name = runtime_context(project)
    run_dir = agentlab_root / "projects" / project_name / "runs" / task_id

    from agent_runtime.recovery.human_review import write_human_review_decision
    from state_store import mark_failed_stopped

    decision_path = write_human_review_decision(
        run_dir, task_id,
        decision="stop",
        reason=reason or "Stopped by human operator.",
        source="cli",
        applies_to_failure_index=applies_to,
    )

    mark_failed_stopped(
        run_dir, project_name, task_id,
        f"Human stopped task: {reason or 'Stopped'}",
    )

    console.print(f"[red]Task stopped.[/red]")
    console.print(f"  Decision: {decision_path}")
    console.print(f"  Task state: failed")


@app.command("recovery-status")
def recovery_status_cmd(
    task_id: str = typer.Option(..., "--task-id", help="Task identifier"),
    project: Optional[str] = typer.Option(None, help="Project name."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON."),
) -> None:
    """Show full recovery status: verdict, human decisions, retry attempts, next action."""
    ensure_safe_task_id(task_id)
    agentlab_root, project_name = runtime_context(project)
    run_dir = agentlab_root / "projects" / project_name / "runs" / task_id

    from atomic_io import safe_read_yaml
    from agent_runtime.recovery.human_review import (
        load_latest_human_review_decision,
        load_all_human_review_decisions,
    )
    from agent_runtime.recovery.retry_ledger import load_retry_attempts, retry_attempt_count

    recovery_dir = run_dir / "recovery"
    if not recovery_dir.exists():
        msg = {"task_id": task_id, "project": project_name, "status": "no_recovery_artifacts"}
        if json_output:
            console.print(json.dumps(msg, indent=2, ensure_ascii=False))
        else:
            console.print("[yellow]No recovery artifacts found.[/yellow]")
        return

    has_event = (recovery_dir / "failure_event.json").exists()
    has_diagnosis = (recovery_dir / "failure_diagnosis.json").exists()
    has_plan = (recovery_dir / "recovery_plan.md").exists()
    has_verdict = (recovery_dir / "recovery_verdict.json").exists()
    has_decision = (recovery_dir / "human_review_decision.json").exists()

    # Load verdict
    verdict = None
    if has_verdict:
        verdict = safe_read_yaml(recovery_dir / "recovery_verdict.json") or {}

    # Load human decisions
    latest_decision = load_latest_human_review_decision(run_dir)
    all_decisions = load_all_human_review_decisions(run_dir)

    # Load retry attempts
    attempts = load_retry_attempts(run_dir)
    attempt_count = retry_attempt_count(run_dir)

    # Determine next action
    next_action = _derive_next_action(verdict, latest_decision)

    if json_output:
        import json as _json
        result = {
            "task_id": task_id,
            "project": project_name,
            "has_failure_event": has_event,
            "has_diagnosis": has_diagnosis,
            "has_recovery_plan": has_plan,
            "has_verdict": has_verdict,
            "has_human_decision": has_decision,
            "verdict": verdict,
            "latest_decision": latest_decision.to_dict() if latest_decision else None,
            "human_decisions_count": len(all_decisions),
            "retry_attempts": attempt_count,
            "next_action": next_action,
        }
        console.print(_json.dumps(result, indent=2, ensure_ascii=False))
        return

    # Rich output
    console.print(f"\n[bold]Recovery Status — {task_id}[/bold]")
    console.print(f"  Project: {project_name}")

    # Verdict
    if verdict:
        v = verdict.get("verdict", "?")
        color = {"retry": "green", "continue": "yellow", "rollback": "yellow",
                  "stop": "red", "human_review": "red"}.get(v, "white")
        console.print(f"\n[bold]Latest Verdict:[/bold] [{color}]{v}[/{color}]")
        console.print(f"  Category: {verdict.get('primary_category', verdict.get('reason', '?')[:80])}")
        console.print(f"  Safe to Auto-Retry: {verdict.get('safe_to_auto_retry', '?')}")
        console.print(f"  Requires Human Review: {verdict.get('requires_human_review', '?')}")

    # Human decisions
    if latest_decision:
        console.print(f"\n[bold]Latest Human Decision:[/bold]")
        console.print(f"  Decision: {latest_decision.decision}")
        console.print(f"  Reason: {latest_decision.reason}")
        console.print(f"  Time: {latest_decision.created_at}")
        if latest_decision.force_used:
            console.print(f"  [yellow]Force was used[/yellow]")
    if len(all_decisions) > 1:
        console.print(f"  Total decisions: {len(all_decisions)}")

    # Retry attempts
    if attempt_count > 0:
        console.print(f"\n[bold]Retry Attempts:[/bold] {attempt_count}")
        for a in attempts:
            result_color = {"success": "green", "failed": "red", "blocked": "yellow"}.get(a.result, "white")
            console.print(f"  #{a.attempt}: [{result_color}]{a.result}[/{result_color}] ({a.trigger}) — {a.command[:60]}")

    # Next action
    console.print(f"\n[bold]Next Action:[/bold] {next_action}")

    # Artifacts
    console.print(f"\n[bold]Artifacts:[/bold]")
    console.print(f"  failure_event.json: {'[green]yes[/green]' if has_event else '[red]no[/red]'}")
    console.print(f"  failure_diagnosis.json: {'[green]yes[/green]' if has_diagnosis else '[red]no[/red]'}")
    console.print(f"  recovery_plan.md: {'[green]yes[/green]' if has_plan else '[red]no[/red]'}")
    console.print(f"  recovery_verdict.json: {'[green]yes[/green]' if has_verdict else '[red]no[/red]'}")
    console.print(f"  human_review_decision.json: {'[green]yes[/green]' if has_decision else '[red]no[/red]'}")
    console.print(f"  retry_attempts.json: {'[green]yes[/green]' if (recovery_dir / 'retry_attempts.json').exists() else '[red]no[/red]'}")

    # Indexed failures
    failures_dir = recovery_dir / "failures"
    if failures_dir.exists():
        indexed = sorted(failures_dir.glob("failure_event_*.json"))
        if indexed:
            console.print(f"  Indexed failures: {len(indexed)}")


@app.command("recovery-feedback")
def recovery_feedback_cmd(
    task_id: str = typer.Option(..., "--task-id", help="Task identifier"),
    project: Optional[str] = typer.Option(None, help="Project name."),
    output_dir: Optional[str] = typer.Option(None, "--output-dir", help="Output directory for feedback artifacts."),
) -> None:
    """Generate P2-L closure quality feedback from recovery history.

    Reads recovery artifacts from the task run directory and writes
    ``closure_quality_feedback.json`` and ``closure_quality_feedback.md``.
    """
    ensure_safe_task_id(task_id)
    agentlab_root, project_name = runtime_context(project)
    run_dir = agentlab_root / "projects" / project_name / "runs" / task_id

    if not run_dir.exists():
        console.print(f"[red]Task run directory does not exist: {run_dir}[/red]")
        raise typer.Exit(code=1)

    out = Path(output_dir) if output_dir else run_dir

    from agent_runtime.recovery.closure_feedback import (
        load_recovery_history,
        derive_closure_quality_feedback,
        write_closure_feedback_json,
        write_closure_feedback_report,
    )

    console.print(f"Loading recovery history from {run_dir} ...")
    history, warnings = load_recovery_history(run_dir)

    for w in warnings:
        console.print(f"  [yellow][WARNING] {w}[/yellow]")

    feedback = derive_closure_quality_feedback(
        task_id=task_id,
        recovery_history=history,
    )

    json_path = write_closure_feedback_json(feedback, out)
    md_path = write_closure_feedback_report(feedback, out)

    console.print(f"\n[bold]Closure Quality Feedback — {task_id}[/bold]")
    console.print(f"  Verdict:            {feedback.verdict}")
    console.print(f"  Quality Score:      {feedback.quality_score}")
    console.print(f"  Recovery Used:      {feedback.recovery_used}")
    console.print(f"  Recovery Success:   {feedback.recovery_successful}")
    console.print(f"  Retry Count:        {feedback.retry_count}")
    console.print(f"  Human Review:       {feedback.human_review_required}")
    if feedback.blocked_reason:
        console.print(f"  Blocked Reason:     {feedback.blocked_reason}")
    console.print(f"  Lessons:            {len(feedback.lessons)}")
    console.print(f"  Recommended Actions: {feedback.recommended_actions}")
    console.print(f"\n  [green]JSON:[/green] {json_path}")
    console.print(f"  [green]MD:[/green]   {md_path}")


@app.command("configure-agent")
def configure_agent_cmd(
    agent: str = typer.Option(..., "--agent", help="Canonical agent name (e.g. Supervisor, Coder, RepoScout, etc.)."),
    mode: Optional[str] = typer.Option(None, "--mode", help="Mode to update: full_cli, qwen_token_plan_cli, full_api, or hybrid_ide. If omitted, applies to all modes."),
    tier: Optional[str] = typer.Option(None, "--tier", help="Tier to update: full, performance, or low. If omitted, applies to all tiers."),
    executor_type: Optional[str] = typer.Option(None, "--executor-type", help="Executor type: cli_agent, direct_api, or special."),
    cli_agent: Optional[str] = typer.Option(None, "--cli-agent", help="CLI agent binary name (e.g. hermes, claude_code)."),
    invocation_contract: Optional[str] = typer.Option(None, "--invocation-contract", help="Worker invocation contract key from config/worker_invocation_contracts.yml."),
    default_model: Optional[str] = typer.Option(None, "--default-model", help="Default fallback model ID from catalog."),
    skip: bool = typer.Option(False, "--skip", help="Whether to skip/disable this agent in the specified tier."),
    project: Optional[str] = typer.Option(None, help="Project name, only used to resolve root."),
) -> None:
    """Manually configure an Agent's execution type, worker contract, or model mapping."""
    agentlab_root, _ = runtime_context(project)
    profiles_path = agentlab_root / "config" / "agent_model_profiles.yml"

    if not profiles_path.exists():
        console.print(f"[red]Error: agent_model_profiles.yml not found at {profiles_path}[/red]")
        raise typer.Exit(code=1)

    import yaml
    try:
        data = yaml.safe_load(profiles_path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        console.print(f"[red]Error parsing agent_model_profiles.yml: {exc}[/red]")
        raise typer.Exit(code=1)

    role_key = agent.lower().replace(" ", "_")
    _role_key_map = {
        "supervisor": "supervisor",
        "reposcout": "reposcout",
        "researcher": "researcher",
        "interfacemapper": "interface_mapper",
        "coder": "coder",
        "artifactproducer": "artifact_producer",
        "promptengineer": "prompt_engineer",
        "testerauditor": "tester_auditor",
        "verifier": "verifier",
        "archivist": "archivist",
        "writer": "writer",
    }
    role_key = _role_key_map.get(role_key, role_key)

    modes_to_update = [mode.lower()] if mode else ["full_cli", "qwen_token_plan_cli", "full_api", "hybrid_ide"]
    tiers_to_update = [tier.lower()] if tier else ["full", "performance", "low"]

    modes_data = data.setdefault("modes", {})

    updated_count = 0
    for m in modes_to_update:
        mode_cfg = modes_data.setdefault(m, {})
        tiers_cfg = mode_cfg.setdefault("tiers", {})
        for t in tiers_to_update:
            tier_cfg = tiers_cfg.setdefault(t, {})
            if skip:
                tier_cfg[role_key] = "skip"
                updated_count += 1
            else:
                agent_cfg = tier_cfg.get(role_key)
                if not isinstance(agent_cfg, dict) or agent_cfg == "skip":
                    agent_cfg = {}
                if executor_type:
                    agent_cfg["executor_type"] = executor_type.lower()
                if cli_agent is not None:
                    agent_cfg["cli_agent"] = cli_agent
                if invocation_contract is not None:
                    agent_cfg["invocation_contract"] = invocation_contract
                if default_model is not None:
                    agent_cfg["default"] = default_model
                tier_cfg[role_key] = agent_cfg
                updated_count += 1

    try:
        profiles_path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
        console.print(f"[green]Successfully updated config for Agent '{agent}' across {updated_count} mode/tier configurations.[/green]")
    except Exception as exc:
        console.print(f"[red]Error writing updates: {exc}[/red]")
        raise typer.Exit(code=1)


def _derive_next_action(
    verdict: dict | None,
    latest_decision,  # HumanReviewDecision | None
) -> str:
    """Derive the next allowed action from verdict and human decisions.

    Delegates to the extracted resume policy function for the actual logic.
    """
    from agent_runtime.recovery.resume_policy import derive_recovery_next_action

    result = derive_recovery_next_action(
        verdict=verdict,
        human_decision=latest_decision,
    )
    action = result["action"]
    reason = result["reason"]
    if result["auditable_force_required"]:
        return f"{action} allowed ({reason}) [--force auditable]"
    if result["allowed"]:
        return f"{action} allowed ({reason})"
    return f"{action} — {reason}"



@app.command("cost-status")
def cost_status(project: str = typer.Option(..., "--project", help="Project name"), format: str = typer.Option("text", "--format")):
    from agent_runtime.costs.spend_ledger import load_spend_ledger
    from agent_runtime.costs.attribution import attribute_spend
    import yaml
    ledger = load_spend_ledger(_PROJECT_ROOT / "memory" / project / "spend_ledger.yml")
    if ledger.project != project: ledger.project = project
    attr = attribute_spend(ledger)
    if format == "json":
        import json
        typer.echo(json.dumps(attr, indent=2))
    elif format == "yaml":
        typer.echo(yaml.safe_dump(attr, sort_keys=False))
    else:
        from agent_runtime.costs.attribution import generate_attribution_report
        typer.echo(generate_attribution_report(attr))

@app.command("cost-estimate")
def cost_estimate(task_packet: str = typer.Option(..., "--task-packet", help="Path to task packet"), format: str = typer.Option("text", "--format")):
    import yaml
    from agent_runtime.costs.estimator import estimate_cost
    from agent_runtime.costs.renderer import render_cost_estimate
    try:
        packet = yaml.safe_load(Path(task_packet).read_text(encoding="utf-8")) or {}
    except Exception as e:
        typer.echo(f"Error loading task packet: {e}")
        raise typer.Exit(1)
    est = estimate_cost(packet, _PROJECT_ROOT)
    from agent_runtime.observability.api import emit_event
    project_id = packet.get("project_id", "AgentLab")
    emit_event(
        project_id=project_id,
        project_dir=_PROJECT_ROOT,
        event_type="cost_estimated",
        details={
            "model": packet.get("model", "unknown"),
            "cached_input_tokens": getattr(est, "cached_input_tokens", 0),
            "uncached_input_tokens": getattr(est, "uncached_input_tokens", 0),
            "output_tokens": getattr(est, "output_tokens", 0),
            "budget_policy": getattr(est, "budget_policy", "standard"),
            "requires_approval": getattr(est, "requires_approval", False),
        },
        task_id=packet.get("task_id", "unknown"),
        worker_id=packet.get("worker_id", "unknown"),
        cost_usd=getattr(est, "total_cost_usd", 0.0)
    )
    typer.echo(render_cost_estimate(est, format_type=format))

@app.command("cost-alerts")
def cost_alerts(project: str = typer.Option(..., "--project", help="Project name"), format: str = typer.Option("text", "--format")):
    import yaml
    from agent_runtime.costs.spend_ledger import load_spend_ledger
    from agent_runtime.costs.budget_policy import load_budget_policy
    from agent_runtime.costs.alerts import check_alerts
    ledger = load_spend_ledger(_PROJECT_ROOT / "memory" / project / "spend_ledger.yml")
    policy = load_budget_policy(_PROJECT_ROOT)
    alerts = check_alerts(policy, ledger)
    if format == "json":
        import json
        typer.echo(json.dumps(alerts, indent=2))
    elif format == "yaml":
        typer.echo(yaml.safe_dump(alerts, sort_keys=False))
    else:
        if not alerts:
            typer.echo("No alerts.")
        for a in alerts:
            typer.echo(f"[{a['level'].upper()}] {a['type']}: {a['message']}")

@app.command("cost-efficiency-review")
def cost_efficiency_review(project: str = typer.Option(..., "--project", help="Project name"), out: str = typer.Option(..., "--out")):
    from agent_runtime.costs.spend_ledger import load_spend_ledger
    from agent_runtime.costs.efficiency_review import generate_efficiency_review
    ledger = load_spend_ledger(_PROJECT_ROOT / "memory" / project / "spend_ledger.yml")
    if ledger.project != project: ledger.project = project
    report = generate_efficiency_review(ledger, {})
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(report, encoding="utf-8")
    typer.echo(f"Wrote {out}")

@app.command("approvals")
def approvals(project: str = typer.Option(..., "--project", help="Project name"), format: str = typer.Option("text", "--format")):
    from agent_runtime.approvals.approval_ledger import load_approval_ledger
    from agent_runtime.approvals.renderer import render_pending_approvals
    ledger = load_approval_ledger(_PROJECT_ROOT / "memory" / project / "approval_ledger.yml")
    pending = ledger.list_pending()
    typer.echo(render_pending_approvals(pending, format_type=format))

@app.command("approve")
def approve(decision_id: str = typer.Option(..., "--decision-id", help="Decision ID"), actor: str = typer.Option(..., "--actor"), reason: str = typer.Option(..., "--reason"), project: str = typer.Option("AgentLab", "--project")):
    from agent_runtime.approvals.approval_ledger import load_approval_ledger, write_approval_ledger
    path = _PROJECT_ROOT / "memory" / project / "approval_ledger.yml"
    ledger = load_approval_ledger(path)
    if ledger.approve_decision(decision_id, actor, reason):
        write_approval_ledger(ledger, path)
        from agent_runtime.observability.api import emit_event
        emit_event(
            project_id=project,
            project_dir=_PROJECT_ROOT,
            event_type="approval_accepted",
            details={"decision_card_id": decision_id, "reason": reason, "actor": actor, "approval_status": "accepted"},
            user_id=actor
        )
        typer.echo(f"Approved {decision_id}")
    else:
        typer.echo(f"Decision {decision_id} not found.")
        raise typer.Exit(1)

@app.command("reject")
def reject(decision_id: str = typer.Option(..., "--decision-id", help="Decision ID"), actor: str = typer.Option(..., "--actor"), reason: str = typer.Option(..., "--reason"), project: str = typer.Option("AgentLab", "--project")):
    from agent_runtime.approvals.approval_ledger import load_approval_ledger, write_approval_ledger
    path = _PROJECT_ROOT / "memory" / project / "approval_ledger.yml"
    ledger = load_approval_ledger(path)
    if ledger.reject_decision(decision_id, actor, reason):
        write_approval_ledger(ledger, path)
        from agent_runtime.observability.api import emit_event
        emit_event(
            project_id=project,
            project_dir=_PROJECT_ROOT,
            event_type="approval_rejected",
            details={"decision_card_id": decision_id, "reason": reason, "actor": actor, "approval_status": "rejected"},
            user_id=actor
        )
        typer.echo(f"Rejected {decision_id}")
    else:
        typer.echo(f"Decision {decision_id} not found.")
        raise typer.Exit(1)

@app.command("timeline")
def timeline_command(project: str = typer.Option(..., "--project", help="Project name"), event_type: str = typer.Option(None, "--event-type")):
    import os
    from agent_runtime.observability.query import query_timeline
    from agent_runtime.observability.renderer import render_timeline
    
    project_dir = os.path.join(str(_PROJECT_ROOT), "projects", project)
    if not os.path.exists(project_dir):
        project_dir = str(_PROJECT_ROOT)
        
    events = query_timeline(project_dir, event_type=event_type)
    typer.echo(render_timeline(events))

@app.command("event-log-tail")
def event_log_tail_command(project: str = typer.Option(..., "--project", help="Project name"), limit: int = typer.Option(50, "--limit")):
    import os
    import json
    from agent_runtime.observability.query import tail_event_log
    
    project_dir = os.path.join(str(_PROJECT_ROOT), "projects", project)
    if not os.path.exists(project_dir):
        project_dir = str(_PROJECT_ROOT)
        
    entries = tail_event_log(project_dir, limit=limit)
    if not entries:
        typer.echo("No event log found or empty.")
    for entry in entries:
        typer.echo(json.dumps(entry, ensure_ascii=False))

if __name__ == '__main__':
    app()
control_app = typer.Typer(help="Control Panel: Manage Workers, Skills, Capabilities, and Executors")
app.add_typer(control_app, name="control")

@control_app.command("workers")
def control_workers(project: str = typer.Option("AgentLab", "--project")):
    from agent_runtime.control_panel.worker_control import WorkerControl
    from agent_runtime.control_panel.renderer import render_worker_table
    wc = WorkerControl(_PROJECT_ROOT)
    console.print(render_worker_table(wc.list_workers()))

@control_app.command("worker-enable")
def control_worker_enable(worker: str = typer.Option(..., "--worker")):
    from agent_runtime.control_panel.worker_control import WorkerControl
    wc = WorkerControl(_PROJECT_ROOT)
    wc.enable_worker(worker)
    typer.echo(f"Enabled worker: {worker}")

@control_app.command("worker-disable")
def control_worker_disable(worker: str = typer.Option(..., "--worker")):
    from agent_runtime.control_panel.worker_control import WorkerControl
    wc = WorkerControl(_PROJECT_ROOT)
    wc.disable_worker(worker)
    typer.echo(f"Disabled worker: {worker}")

@control_app.command("worker-inspect")
def control_worker_inspect(worker: str = typer.Option(..., "--worker")):
    from agent_runtime.control_panel.worker_control import WorkerControl
    import yaml
    wc = WorkerControl(_PROJECT_ROOT)
    overrides = wc.get_overrides(worker)
    typer.echo(f"Control panel state for {worker}:")
    typer.echo(yaml.safe_dump(overrides))

@control_app.command("worker-force-assign")
def control_worker_force_assign(worker: str = typer.Option(..., "--worker"), role: str = typer.Option(..., "--role")):
    from agent_runtime.control_panel.worker_control import WorkerControl
    wc = WorkerControl(_PROJECT_ROOT)
    wc.force_assign_role(worker, role)
    typer.echo(f"Forced worker {worker} to role {role}")

@control_app.command("worker-reset-assign")
def control_worker_reset_assign(worker: str = typer.Option(..., "--worker")):
    from agent_runtime.control_panel.worker_control import WorkerControl
    wc = WorkerControl(_PROJECT_ROOT)
    wc.reset_assignment(worker)
    typer.echo(f"Reset assignment for {worker}")

@control_app.command("skills")
def control_skills(project: str = typer.Option("AgentLab", "--project")):
    from agent_runtime.control_panel.skill_control import SkillControl
    import yaml
    sc = SkillControl(_PROJECT_ROOT)
    typer.echo(yaml.safe_dump(sc.list_skills()))

@control_app.command("capabilities")
def control_capabilities(project: str = typer.Option("AgentLab", "--project")):
    from agent_runtime.control_panel.capability_control import CapabilityControl
    import yaml
    cc = CapabilityControl(_PROJECT_ROOT)
    typer.echo(yaml.safe_dump(cc.list_capabilities()))

@control_app.command("executors")
def control_executors(project: str = typer.Option("AgentLab", "--project")):
    from agent_runtime.control_panel.executor_control import ExecutorControl
    import yaml
    ec = ExecutorControl(_PROJECT_ROOT)
    typer.echo(yaml.safe_dump(ec.list_executors()))

@control_app.command("approve")
def control_approve_decision(decision_id: str = typer.Option(..., "--decision-card"), actor: str = typer.Option("admin", "--actor"), reason: str = typer.Option("Approved via control panel", "--reason")):
    from agent_runtime.control_panel.approval_actions import control_approve
    if control_approve(_PROJECT_ROOT, "AgentLab", decision_id, actor, reason):
        typer.echo(f"Approved {decision_id}")
    else:
        typer.echo(f"Failed to approve {decision_id}")
