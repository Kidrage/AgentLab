"""Protocol, artifact task, and CLI entrypoint commands."""

from __future__ import annotations

from pathlib import Path

import typer
import yaml
from rich.console import Console


def register_protocol_commands(app: typer.Typer, project_root: Path, console: Console) -> None:
    """Register collaboration protocol commands on the root CLI app."""

    @app.command("repository-handoff")
    def repository_handoff_cmd(
        repo: Path = typer.Option(..., "--repo", exists=True, file_okay=False, resolve_path=True),
        shared_memory_root: Path | None = typer.Option(
            None,
            "--shared-memory-root",
            help="Shared repository-memory root; defaults to AgentLab memory/repositories.",
        ),
        write: bool = typer.Option(False, "--write", help="Create or refresh root, local, compatible, and shared HandOff copies."),
    ) -> None:
        """Discover or safely refresh repository memory without bulk content reads."""
        from repository_handoff import discover_handoff, scan_repository, update_handoffs

        memory_root = (shared_memory_root or (project_root / "memory" / "repositories")).expanduser().resolve()
        if write:
            result = update_handoffs(repo, memory_root)
            result["status"] = "updated"
        else:
            existing = discover_handoff(repo, memory_root)
            snapshot = scan_repository(repo)
            result = {
                "status": "found" if existing else "missing",
                "repository_id": snapshot["repository_id"],
                "handoff_path": str(existing) if existing else None,
                "required_action": None if existing else "rerun with --write before deep repository work",
                "path_count": snapshot["scan"]["path_count"],
                "truncated": snapshot["scan"]["truncated"],
                "content_bulk_read": snapshot["scan"]["content_bulk_read"],
            }
        console.print(yaml.safe_dump(result, allow_unicode=True, sort_keys=False).rstrip())

    @app.command("workspace-entry")
    def workspace_entry_cmd(
        agent: str = typer.Option(..., "--agent", help="CLI agent id entering the AgentLab workspace."),
        project: str = typer.Option(
            "AgentLab",
            "--project",
            help="Project whose task state should ground the entry packet.",
        ),
        task_id: str | None = typer.Option(None, "--task-id", help="Optional task id to ground the entry packet."),
    ) -> None:
        """Print the enforced AgentLab workspace entry packet for a CLI agent."""
        from agent_runtime.protocols import build_workspace_entry

        packet = build_workspace_entry(project_root, agent, project=project, task_id=task_id)
        console.print(yaml.safe_dump(packet, sort_keys=False, allow_unicode=True).rstrip())

    @app.command("frontdesk-context")
    def frontdesk_context_cmd(
        agent: str = typer.Option(..., "--agent", help="Frontdesk-capable CLI agent id."),
        project: str = typer.Option("AgentLab", "--project"),
        task_id: str | None = typer.Option(None, "--task-id"),
    ) -> None:
        """Print deterministic frontdesk context for a user-facing chat assistant."""
        from agent_runtime.protocols import build_frontdesk_context

        packet = build_frontdesk_context(project_root, agent, project=project, task_id=task_id)
        console.print(yaml.safe_dump(packet, sort_keys=False, allow_unicode=True).rstrip())

    @app.command("frontdesk-session")
    def frontdesk_session_cmd(
        agent: str = typer.Option(..., "--agent", help="Frontdesk-capable CLI agent id."),
        project: str = typer.Option("AgentLab", "--project"),
        task_id: str | None = typer.Option(None, "--task-id"),
    ) -> None:
        """Print a ready-to-inject frontdesk session prompt for any supported CLI."""
        from agent_runtime.protocols import build_frontdesk_session

        console.print(build_frontdesk_session(project_root, agent, project=project, task_id=task_id))

    @app.command("role-session")
    def role_session_cmd(
        role: str = typer.Option(..., "--role", help="AgentLab role name, e.g. Coder or ArtifactProducer."),
        worker: str = typer.Option(..., "--worker", help="CLI worker id to bind to this role."),
        project: str = typer.Option("AgentLab", "--project"),
        task_id: str = typer.Option("task_0001", "--task-id"),
    ) -> None:
        """Print the enforced role session packet for a worker-role assignment."""
        from agent_runtime.protocols import build_role_session

        packet = build_role_session(project_root, role, worker, project=project, task_id=task_id)
        console.print(yaml.safe_dump(packet, sort_keys=False, allow_unicode=True).rstrip())
        if not packet.get("binding", {}).get("allowed"):
            raise typer.Exit(code=1)

    @app.command("frontdesk-doctor")
    def frontdesk_doctor_cmd(
        agent: str = typer.Option(..., "--agent", help="Frontdesk-capable CLI agent id."),
    ) -> None:
        """Validate a CLI agent against the enforced frontdesk protocol."""
        from agent_runtime.protocols import run_frontdesk_doctor

        result = run_frontdesk_doctor(project_root, agent)
        console.print(yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip())
        if result.get("status") != "pass":
            raise typer.Exit(code=1)

    @app.command("role-doctor")
    def role_doctor_cmd(
        role: str = typer.Option(..., "--role", help="AgentLab role name, e.g. Coder or ArtifactProducer."),
        worker: str = typer.Option(..., "--worker", help="CLI worker id."),
    ) -> None:
        """Validate a worker-role binding and role-session generation."""
        from agent_runtime.protocols import run_role_doctor

        result = run_role_doctor(project_root, role, worker)
        console.print(yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip())
        if result.get("status") != "pass":
            raise typer.Exit(code=1)

    @app.command("protocol-doctor")
    def protocol_doctor_cmd() -> None:
        """Validate runtime-enforced AgentLab collaboration protocol wiring."""
        from agent_runtime.protocols import run_protocol_doctor

        result = run_protocol_doctor(project_root)
        console.print(yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip())
        if result.get("status") != "pass":
            raise typer.Exit(code=1)

    @app.command("artifact-task-plan")
    def artifact_task_plan_cmd(
        task_text: str = typer.Option(..., "--task-text", help="User-facing artifact request text."),
        artifact_type: str | None = typer.Option(None, "--artifact-type", help="Override inferred artifact type."),
        output_path: str | None = typer.Option(None, "--output-path", help="Expected artifact output path."),
        preferred_provider: str | None = typer.Option(
            None,
            "--provider",
            help="Preferred provider id from artifact_task_policy.yml.",
        ),
        project: str = typer.Option("AgentLab", "--project", help="AgentLab project name."),
        task_id: str = typer.Option("task_0001", "--task-id", help="AgentLab task id."),
        write: bool = typer.Option(False, "--write", help="Write projects/<project>/runs/<task_id>/artifact_task.yml."),
    ) -> None:
        """Build a structured ArtifactTask contract for ArtifactProducer."""
        from agent_runtime.protocols import build_artifact_task_contract

        packet = build_artifact_task_contract(
            project_root,
            task_text,
            artifact_type=artifact_type,
            output_path=output_path,
            project=project,
            task_id=task_id,
            preferred_provider=preferred_provider,
        )
        if write:
            out = project_root / "projects" / project / "runs" / task_id / "artifact_task.yml"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(yaml.safe_dump(packet, sort_keys=False, allow_unicode=True), encoding="utf-8")
            packet["written_to"] = str(out)
        console.print(yaml.safe_dump(packet, sort_keys=False, allow_unicode=True).rstrip())
        if packet.get("routing", {}).get("status") != "routed":
            raise typer.Exit(code=1)

    @app.command("artifact-doctor")
    def artifact_doctor_cmd() -> None:
        """Validate ArtifactProducer policy, provider routing, and role bindings."""
        from agent_runtime.protocols import run_artifact_task_doctor

        result = run_artifact_task_doctor(project_root)
        console.print(yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip())
        if result.get("status") != "pass":
            raise typer.Exit(code=1)

    @app.command("cli-entrypoint-scan")
    def cli_entrypoint_scan_cmd() -> None:
        """Scan recognized local agent CLIs that can receive AgentLab entrypoints."""
        from agent_runtime.protocols import scan_cli_entrypoints

        result = scan_cli_entrypoints(project_root)
        console.print(yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip())

    @app.command("cli-entrypoint-bootstrap")
    def cli_entrypoint_bootstrap_cmd(
        write: bool = typer.Option(False, "--write", help="Create project-local entrypoint files and wrappers."),
    ) -> None:
        """Plan or install all project-local CLI entrypoints and wrappers."""
        from agent_runtime.protocols import install_cli_entrypoints

        result = install_cli_entrypoints(project_root, write=write)
        console.print(yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip())

    @app.command("cli-entrypoint-install")
    def cli_entrypoint_install_cmd(
        agent: str | None = typer.Option(None, "--agent", help="Install one agent; omit with --all to install all."),
        all_agents: bool = typer.Option(False, "--all", help="Install all recognized configurable agents."),
        write: bool = typer.Option(False, "--write", help="Actually write files; otherwise print a plan."),
    ) -> None:
        """Install project-local entrypoint and wrapper for one or all CLI agents."""
        from agent_runtime.protocols import install_cli_entrypoints

        if not agent and not all_agents:
            console.print("[red]Error: specify --agent <id> or --all[/red]")
            raise typer.Exit(code=1)
        result = install_cli_entrypoints(project_root, agent=agent if not all_agents else None, write=write)
        console.print(yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip())

    @app.command("cli-entrypoint-doctor")
    def cli_entrypoint_doctor_cmd(
        agent: str | None = typer.Option(None, "--agent", help="Check one agent; omit to check all planned entrypoints."),
    ) -> None:
        """Validate project-local CLI entrypoints and wrappers."""
        from agent_runtime.protocols import doctor_cli_entrypoints

        result = doctor_cli_entrypoints(project_root, agent=agent)
        console.print(yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip())
        if result.get("status") != "pass":
            raise typer.Exit(code=1)

    @app.command("cli-entrypoint-status")
    def cli_entrypoint_status_cmd() -> None:
        """Show installed CLI entrypoint inventory and install report if present."""
        policy_path = project_root / "config" / "cli_entrypoint_policy.yml"
        policy = yaml.safe_load(policy_path.read_text(encoding="utf-8")) if policy_path.exists() else {}
        inventory_path = project_root / str(policy.get("inventory_path", ".agentlab/cli_entrypoints/inventory.yml"))
        report_path = project_root / str(policy.get("install_report_path", ".agentlab/cli_entrypoints/install_report.yml"))
        result = {
            "inventory_path": str(inventory_path),
            "inventory_exists": inventory_path.exists(),
            "install_report_path": str(report_path),
            "install_report_exists": report_path.exists(),
            "inventory": yaml.safe_load(inventory_path.read_text(encoding="utf-8")) if inventory_path.exists() else {},
            "install_report": yaml.safe_load(report_path.read_text(encoding="utf-8")) if report_path.exists() else {},
        }
        console.print(yaml.safe_dump(result, sort_keys=False, allow_unicode=True).rstrip())
