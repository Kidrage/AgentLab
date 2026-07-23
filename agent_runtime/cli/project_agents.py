"""CLI commands for project truth and dynamic Agent lifecycle."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer
import yaml

from agent_runtime.atomic_io import atomic_write_yaml
from agent_runtime.project_agents import (
    AgentLifecycle,
    AgentManifest,
    ProjectAgentFactory,
    ProjectAgentRegistry,
)
from agent_runtime.project_truth import (
    ChangeSet,
    FactChange,
    ProjectTruthStore,
    ResourceChange,
)


def _project_root(root: Path, project: str) -> Path:
    projects_root = (root / "projects").resolve()
    path = (projects_root / project).resolve()
    try:
        path.relative_to(projects_root)
    except ValueError as exc:
        raise typer.BadParameter("project path escapes projects root") from exc
    if not path.is_dir():
        raise typer.BadParameter(f"project does not exist: {project}")
    return path


def _registry(root: Path, project: str) -> ProjectAgentRegistry:
    return ProjectAgentRegistry(ProjectTruthStore(_project_root(root, project)))


def _scopes(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def register_project_agent_commands(app: typer.Typer, root: Path, console: Any) -> None:
    del console

    @app.command("project-agents-enable")
    def enable_project_agents(
        project: str = typer.Option(..., "--project"),
    ) -> None:
        project_root = _project_root(root, project)
        manifest_path = project_root / "project.yml"
        data = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        workspace = data.setdefault("workspace", {})
        if workspace.get("isolation", "required") != "required":
            raise typer.BadParameter("project workspace isolation must be required")
        workspace["isolation"] = "required"
        features = data.setdefault("features", {})
        features["project_truth_mode"] = "enforced"
        features["enable_project_agents"] = True
        atomic_write_yaml(manifest_path, data, sort_keys=False)
        pointer = ProjectTruthStore(project_root).initialize(project)
        typer.echo(
            yaml.safe_dump(
                {
                    "status": "enabled",
                    "project": project,
                    "snapshot_id": pointer.current_snapshot_id,
                },
                sort_keys=False,
            )
        )

    @app.command("add-agent")
    def add_agent(
        project: str = typer.Option(..., "--project"),
        agent_id: str = typer.Option(..., "--agent-id"),
        name: str = typer.Option(..., "--name"),
        role: str = typer.Option(..., "--role"),
        responsibility: str = typer.Option(..., "--responsibility"),
        read_scope: str = typer.Option("", "--read-scope"),
        write_scope: str = typer.Option("", "--write-scope"),
        approval_scope: str = typer.Option("", "--approval-scope"),
        runtime_role: str = typer.Option("Researcher", "--runtime-role"),
        model_profile: str = typer.Option("balanced", "--model-profile"),
    ) -> None:
        registry = _registry(root, project)
        snapshot = registry.truth.current()
        manifest = AgentManifest(
            id=agent_id,
            name=name,
            version="1.0.0",
            role=role,
            description=responsibility,
            responsibilities=(responsibility,),
            runtime_role=runtime_role,
            read_scope=_scopes(read_scope),
            write_scope=_scopes(write_scope),
            approval_scope=_scopes(approval_scope),
            knowledge_binding={
                "namespace": f"agent.{project}.{agent_id}",
                "documents": (),
                "artifacts": (),
            },
            model_profile=model_profile,
            tool_permission=("knowledge.read",),
            budget_profile="standard",
            status="active",
            acceptance_rules=("scope_contract_satisfied",),
        )
        receipt = registry.register(
            manifest,
            expected_snapshot_id=snapshot.snapshot_id,
            actor_id="user",
            source="user",
            approved=True,
        )
        typer.echo(yaml.safe_dump(receipt.to_dict(), sort_keys=False))

    @app.command("set-project-fact")
    def set_project_fact(
        project: str = typer.Option(..., "--project"),
        key: str = typer.Option(..., "--key"),
        value_json: str = typer.Option(..., "--value-json"),
        owner: str = typer.Option(..., "--owner"),
        idempotency_key: str = typer.Option(..., "--idempotency-key"),
        reason: str = typer.Option("", "--reason"),
    ) -> None:
        try:
            value = json.loads(value_json)
        except json.JSONDecodeError as exc:
            raise typer.BadParameter(
                f"value-json must be valid JSON: {exc.msg}"
            ) from exc
        truth = ProjectTruthStore(_project_root(root, project))
        current = truth.current()
        receipt = truth.commit(
            ChangeSet(
                project_id=project,
                expected_snapshot_id=current.snapshot_id,
                actor_id="user",
                idempotency_key=idempotency_key,
                reason=reason,
                facts=(FactChange(key=key, value=value, owner=owner),),
            )
        )
        typer.echo(yaml.safe_dump(receipt.to_dict(), sort_keys=False))

    @app.command("set-project-resource")
    def set_project_resource(
        project: str = typer.Option(..., "--project"),
        key: str = typer.Option(..., "--key"),
        content_path: Path = typer.Option(..., "--content-path"),
        idempotency_key: str = typer.Option(..., "--idempotency-key"),
        media_type: str = typer.Option("application/yaml", "--media-type"),
        reason: str = typer.Option("", "--reason"),
    ) -> None:
        if not content_path.is_file():
            raise typer.BadParameter(f"content path does not exist: {content_path}")
        if media_type in {"application/yaml", "application/json"}:
            if media_type == "application/json":
                content = json.loads(content_path.read_text(encoding="utf-8"))
            else:
                content = yaml.safe_load(content_path.read_text(encoding="utf-8"))
        else:
            content = content_path.read_text(encoding="utf-8")
        truth = ProjectTruthStore(_project_root(root, project))
        current = truth.current()
        receipt = truth.commit(
            ChangeSet(
                project_id=project,
                expected_snapshot_id=current.snapshot_id,
                actor_id="user",
                idempotency_key=idempotency_key,
                reason=reason,
                resources=(
                    ResourceChange(
                        key=key,
                        content=content,
                        media_type=media_type,
                    ),
                ),
            )
        )
        typer.echo(yaml.safe_dump(receipt.to_dict(), sort_keys=False))

    @app.command("project-fact-history")
    def project_fact_history(
        project: str = typer.Option(..., "--project"),
        key: str = typer.Option(..., "--key"),
    ) -> None:
        truth = ProjectTruthStore(_project_root(root, project))
        typer.echo(
            yaml.safe_dump(
                [revision.to_dict() for revision in truth.fact_history(key)],
                sort_keys=False,
                allow_unicode=True,
            )
        )

    @app.command("project-truth-audit")
    def project_truth_audit(
        project: str = typer.Option(..., "--project"),
    ) -> None:
        typer.echo(
            yaml.safe_dump(
                ProjectTruthStore(_project_root(root, project)).audit(),
                sort_keys=False,
            )
        )

    @app.command("create-agent-team")
    def create_agent_team(
        project: str = typer.Option(..., "--project"),
        prompt: str = typer.Option(..., "--prompt"),
    ) -> None:
        registry = _registry(root, project)
        receipt = ProjectAgentFactory().create_team(
            registry,
            prompt,
            expected_snapshot_id=registry.truth.current().snapshot_id,
            actor_id="user",
        )
        typer.echo(yaml.safe_dump(receipt.to_dict(), sort_keys=False))

    @app.command("list-agents")
    def list_agents(
        project: str = typer.Option(..., "--project"),
        format: str = typer.Option("yaml", "--format"),
        include_archived: bool = typer.Option(True, "--include-archived/--active-only"),
    ) -> None:
        documents = [
            item.to_dict()
            for item in _registry(root, project).list(
                include_archived=include_archived
            )
        ]
        if format == "json":
            typer.echo(json.dumps(documents, ensure_ascii=False, indent=2))
        elif format == "yaml":
            typer.echo(yaml.safe_dump(documents, sort_keys=False, allow_unicode=True))
        else:
            raise typer.BadParameter("format must be yaml or json")

    def transition(
        project: str, agent_id: str, operation: str, **changes: Any
    ) -> None:
        registry = _registry(root, project)
        lifecycle = AgentLifecycle(registry)
        method = getattr(lifecycle, operation)
        receipt = method(
            agent_id,
            expected_snapshot_id=registry.truth.current().snapshot_id,
            actor_id="user",
            **changes,
        )
        typer.echo(yaml.safe_dump(receipt.to_dict(), sort_keys=False))

    @app.command("pause-agent")
    def pause_agent(
        project: str = typer.Option(..., "--project"),
        agent_id: str = typer.Option(..., "--agent-id"),
    ) -> None:
        transition(project, agent_id, "pause")

    @app.command("resume-agent")
    def resume_agent(
        project: str = typer.Option(..., "--project"),
        agent_id: str = typer.Option(..., "--agent-id"),
    ) -> None:
        transition(project, agent_id, "resume")

    @app.command("archive-agent")
    def archive_agent(
        project: str = typer.Option(..., "--project"),
        agent_id: str = typer.Option(..., "--agent-id"),
    ) -> None:
        transition(project, agent_id, "archive")

    @app.command("replace-agent")
    def replace_agent(
        project: str = typer.Option(..., "--project"),
        agent_id: str = typer.Option(..., "--agent-id"),
        model_profile: str = typer.Option(..., "--model-profile"),
        runtime_role: str | None = typer.Option(None, "--runtime-role"),
    ) -> None:
        transition(
            project,
            agent_id,
            "replace",
            model_profile=model_profile,
            runtime_role=runtime_role,
        )
