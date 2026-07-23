"""CLI commands for project truth and dynamic Agent lifecycle."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer
import yaml

from agent_runtime.atomic_io import atomic_write_yaml
from agent_runtime.project_ops.project_router import DEFAULT_PROJECT_BRAIN_FILES
from agent_runtime.project_agents import (
    AgentLifecycle,
    AgentManifest,
    ProjectAgentFactory,
    ProjectAgentRegistry,
)
from agent_runtime.project_truth import (
    ChangeSet,
    FactChange,
    ProjectTruthMigrator,
    ProjectTruthStore,
    ResourceChange,
)


def _project_root(root: Path, project: str) -> Path:
    projects_root = (root / "projects").resolve()
    raw_path = projects_root / project
    if Path(project).name != project or project in {".", ".."}:
        raise typer.BadParameter("project must be one direct project id")
    if raw_path.is_symlink():
        raise typer.BadParameter("project path must not be a symlink")
    path = raw_path.resolve()
    try:
        path.relative_to(projects_root)
    except ValueError as exc:
        raise typer.BadParameter("project path escapes projects root") from exc
    if not path.is_dir():
        raise typer.BadParameter(f"project does not exist: {project}")
    manifest_path = path / "project.yml"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise typer.BadParameter("project manifest is missing or unsafe")
    try:
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise typer.BadParameter("project manifest cannot be read") from exc
    if not isinstance(manifest, dict) or manifest.get("project_id") != project:
        raise typer.BadParameter("project manifest identity mismatch")
    return path


def _registry(root: Path, project: str) -> ProjectAgentRegistry:
    return ProjectAgentRegistry(ProjectTruthStore(_project_root(root, project)))


def _meaningful_legacy_files(project_root: Path) -> list[Path]:
    files: list[Path] = []
    for name in ("project_brain", "production", "config"):
        for path in (project_root / name).rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            if name == "project_brain":
                expected = DEFAULT_PROJECT_BRAIN_FILES.get(path.name)
                if expected is not None:
                    try:
                        if path.read_text(encoding="utf-8") == expected:
                            continue
                    except OSError:
                        pass
            files.append(path)
    return files


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
        truth = ProjectTruthStore(project_root)
        legacy_files = _meaningful_legacy_files(project_root)
        if not truth.pointer_path.exists():
            if legacy_files:
                raise typer.BadParameter(
                    "legacy project content requires an approved truth migration"
                )
            pointer = truth.initialize(project)
        else:
            pointer = truth.initialize(project)
            current = truth.current()
            if (
                legacy_files
                and not current.resources
                and not current.facts
            ):
                raise typer.BadParameter(
                    "legacy project content requires a completed truth migration"
                )
            migration_result = (
                project_root
                / ".agentlab"
                / "truth"
                / "migration_result.yml"
            )
            current_mode = (data.get("features") or {}).get(
                "project_truth_mode", "legacy"
            )
            if (
                legacy_files
                and current_mode != "enforced"
            ):
                if not migration_result.is_file() or migration_result.is_symlink():
                    raise typer.BadParameter(
                        "legacy project content requires a hash-bound migration receipt"
                    )
                try:
                    migration = yaml.safe_load(
                        migration_result.read_text(encoding="utf-8")
                    )
                    if (
                        not isinstance(migration, dict)
                        or migration.get("schema_version")
                        != "project-truth-migration-result/v1"
                        or migration.get("status") != "migrated"
                        or migration.get("project_id") != project
                    ):
                        raise ValueError("migration result metadata mismatch")
                    verified = truth.verify_receipt(
                        migration.get("canonical_commit_receipt") or {}
                    )
                    if verified.snapshot_id != current.snapshot_id:
                        raise ValueError(
                            "migration receipt is not the current snapshot"
                        )
                except (OSError, RuntimeError, ValueError, yaml.YAMLError) as exc:
                    raise typer.BadParameter(
                        "legacy project migration receipt is invalid or stale"
                    ) from exc
        truth.audit()
        features = data.setdefault("features", {})
        features["project_truth_mode"] = "enforced"
        features["enable_project_agents"] = True
        atomic_write_yaml(manifest_path, data, sort_keys=False)
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
        if key.startswith("agents.manifest."):
            raise typer.BadParameter(
                "Agent manifests must be mutated through Agent Registry commands"
            )
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

    @app.command("project-resource-history")
    def project_resource_history(
        project: str = typer.Option(..., "--project"),
        key: str = typer.Option(..., "--key"),
    ) -> None:
        truth = ProjectTruthStore(_project_root(root, project))
        typer.echo(
            yaml.safe_dump(
                [revision.to_dict() for revision in truth.resource_history(key)],
                sort_keys=False,
                allow_unicode=True,
            )
        )

    @app.command("rollback-project-truth")
    def rollback_project_truth(
        project: str = typer.Option(..., "--project"),
        snapshot_id: str = typer.Option(..., "--snapshot-id"),
        idempotency_key: str = typer.Option(..., "--idempotency-key"),
        reason: str = typer.Option("", "--reason"),
    ) -> None:
        truth = ProjectTruthStore(_project_root(root, project))
        receipt = truth.rollback(
            snapshot_id,
            expected_snapshot_id=truth.current().snapshot_id,
            actor_id="user",
            idempotency_key=idempotency_key,
            reason=reason,
        )
        typer.echo(yaml.safe_dump(receipt.to_dict(), sort_keys=False))

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

    @app.command("plan-project-truth-migration")
    def plan_project_truth_migration(
        project: str = typer.Option(..., "--project"),
        output: Path | None = typer.Option(None, "--output"),
    ) -> None:
        plan = ProjectTruthMigrator(_project_root(root, project)).plan(project)
        if output is not None:
            atomic_write_yaml(output, plan, sort_keys=False)
        typer.echo(yaml.safe_dump(plan, sort_keys=False, allow_unicode=True))

    @app.command("project-truth-shadow")
    def project_truth_shadow(
        project: str = typer.Option(..., "--project"),
    ) -> None:
        project_root = _project_root(root, project)
        plan = ProjectTruthMigrator(project_root).plan(project)
        report_path = (
            project_root / ".agentlab" / "truth" / "shadow_audit.yml"
        )
        atomic_write_yaml(report_path, plan, sort_keys=False)
        manifest_path = project_root / "project.yml"
        manifest = yaml.safe_load(
            manifest_path.read_text(encoding="utf-8")
        ) or {}
        features = manifest.setdefault("features", {})
        if features.get("project_truth_mode") == "enforced":
            raise typer.BadParameter(
                "enforced truth cannot be downgraded to shadow mode"
            )
        features["project_truth_mode"] = "shadow"
        features["enable_project_agents"] = False
        atomic_write_yaml(manifest_path, manifest, sort_keys=False)
        typer.echo(
            yaml.safe_dump(
                {
                    "status": "shadow",
                    "project": project,
                    "report": str(report_path.relative_to(project_root)),
                    "conflict_count": len(
                        plan.get("potential_fact_conflicts") or []
                    ),
                },
                sort_keys=False,
            )
        )

    @app.command("apply-project-truth-migration")
    def apply_project_truth_migration(
        project: str = typer.Option(..., "--project"),
        manifest_path: Path = typer.Option(..., "--manifest"),
    ) -> None:
        if not manifest_path.is_file():
            raise typer.BadParameter(
                f"migration manifest does not exist: {manifest_path}"
            )
        manifest = yaml.safe_load(
            manifest_path.read_text(encoding="utf-8")
        ) or {}
        if manifest.get("project_id") != project:
            raise typer.BadParameter("migration manifest project mismatch")
        result = ProjectTruthMigrator(_project_root(root, project)).apply(
            manifest
        )
        typer.echo(yaml.safe_dump(result, sort_keys=False, allow_unicode=True))

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
            approved=True,
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
