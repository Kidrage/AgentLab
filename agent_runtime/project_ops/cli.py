"""ProjectOps CLI.

Run with:

    python -m agent_runtime.project_ops.cli repo-hygiene-check

`agentlab.sh` also dispatches these S2.5 commands directly.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Optional

import typer
import yaml

from .agent_contributions import render_agent_contribution_summary, summarize_agent_contributions
from .project_router import (
    init_project,
    load_project_routing_policy,
    project_status,
    render_project_status,
    route_decision_to_dict,
    route_invocation_to_project,
)
from .repo_hygiene import print_hygiene_report, scan_repository_root
from .task_compaction import compact_task, task_compaction_result_to_dict

app = typer.Typer(help="AgentLab ProjectOps commands.", no_args_is_help=True)


def repo_root_from_cwd() -> Path:
    return Path.cwd()


@app.command("repo-hygiene-check")
def repo_hygiene_check(
    json_output: bool = typer.Option(False, "--json", help="Emit JSON instead of Markdown."),
    root: Optional[Path] = typer.Option(None, "--root", help="Repository root. Defaults to cwd."),
) -> None:
    repo_root = (root or repo_root_from_cwd()).resolve()
    report = scan_repository_root(repo_root)
    print_hygiene_report(report, json_output=json_output)
    if not report.ok:
        raise typer.Exit(code=1)


@app.command("project-route")
def project_route(
    mission_contract: Path = typer.Option(..., "--mission-contract", help="Path to mission_contract.yml."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
    root: Optional[Path] = typer.Option(None, "--root", help="Repository root. Defaults to cwd."),
) -> None:
    repo_root = (root or repo_root_from_cwd()).resolve()
    contract = yaml.safe_load(mission_contract.read_text(encoding="utf-8")) or {}
    policy = load_project_routing_policy(repo_root)
    existing_projects = []
    projects_root = repo_root / "projects"
    if projects_root.exists():
        for manifest_path in sorted(projects_root.glob("*/project.yml")):
            existing_projects.append(yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {})
    decision = route_invocation_to_project(contract, existing_projects, policy)
    payload = route_decision_to_dict(decision)
    if json_output:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print("# Project Route Decision\n")
        for key, value in payload.items():
            print(f"- {key}: {value}")


@app.command("project-init")
def project_init(
    project_id: str = typer.Option(..., "--project-id"),
    project_type: str = typer.Option("user_project", "--type"),
    title: str = typer.Option("", "--title"),
    json_output: bool = typer.Option(False, "--json"),
    root: Optional[Path] = typer.Option(None, "--root"),
) -> None:
    repo_root = (root or repo_root_from_cwd()).resolve()
    result = init_project(repo_root, project_id=project_id, project_type=project_type, title=title or project_id)
    payload = asdict(result)
    if json_output:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(f"Project initialized: {result.project_id}")
        print(f"Root: {result.root_path}")
        print(f"Created: {len(result.created_paths)}")
        print(f"Existing: {len(result.existing_paths)}")


@app.command("project-status")
def project_status_cmd(
    project: str = typer.Option(..., "--project"),
    json_output: bool = typer.Option(False, "--json"),
    root: Optional[Path] = typer.Option(None, "--root"),
) -> None:
    repo_root = (root or repo_root_from_cwd()).resolve()
    status = project_status(repo_root, project)
    if json_output:
        print(json.dumps(status, indent=2, ensure_ascii=False))
    else:
        text = render_project_status(status)
        print(text)
        out = repo_root / "projects" / project / "acceptance" / "project_status.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")


@app.command("task-compact")
def task_compact_cmd(
    project: str = typer.Option(..., "--project"),
    task: str = typer.Option(..., "--task"),
    execute_prune: bool = typer.Option(False, "--execute-prune", help="Reserved. Raw artifacts are preserved unless explicitly enabled."),
    json_output: bool = typer.Option(False, "--json"),
    root: Optional[Path] = typer.Option(None, "--root"),
) -> None:
    repo_root = (root or repo_root_from_cwd()).resolve()
    task_dir = repo_root / "projects" / project / "tasks" / "closed" / task
    if not task_dir.exists():
        task_dir = repo_root / "projects" / project / "runs" / task
    result = compact_task(project, task, task_dir, execute_prune=execute_prune)
    payload = task_compaction_result_to_dict(result)
    if json_output:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(f"Task compacted: {project}/{task}")
        print(f"Compact dir: {result.compact_dir}")
        print(f"Created files: {len(result.created_files)}")
        print(f"Raw files preserved: {len(result.raw_files_preserved)}")


@app.command("agent-contributions")
def agent_contributions_cmd(
    project: str = typer.Option(..., "--project"),
    task: str = typer.Option(..., "--task"),
    json_output: bool = typer.Option(False, "--json"),
    root: Optional[Path] = typer.Option(None, "--root"),
) -> None:
    repo_root = (root or repo_root_from_cwd()).resolve()
    project_root = repo_root / "projects" / project
    summary = summarize_agent_contributions(project_root, task)
    if json_output:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        print(render_agent_contribution_summary(summary))


def main() -> None:
    app()


if __name__ == "__main__":
    main()
