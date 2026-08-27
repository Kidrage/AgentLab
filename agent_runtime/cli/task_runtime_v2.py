"""Operator CLI for the append-only Task Runtime."""

from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
from typing import Any

import typer
import yaml
from rich.console import Console

from agent_runtime.protocol_canary import run_protocol_canaries
from agent_runtime.production_protocols import ProductionProtocolRunner
from agent_runtime.task_runtime_v2 import (
    AttemptLogRetention,
    LegacyRunMigrator,
    RoleAttemptExecutor,
    TaskInputClassifier,
    TaskRuntime,
)


RootProvider = Path | Callable[[], Path]


def register_task_runtime_commands(
    app: typer.Typer, root: RootProvider, console: Console
) -> None:
    """Register the stable Task Runtime command surface on an AgentLab Typer app."""

    task_app = typer.Typer(
        help="Task Runtime business-goal lifecycle.", no_args_is_help=True
    )
    job_app = typer.Typer(
        help="Execution strategies under a Task.", no_args_is_help=True
    )
    work_app = typer.Typer(help="Schedulable units under a Job.", no_args_is_help=True)
    attempt_app = typer.Typer(
        help="Immutable execution attempts.", no_args_is_help=True
    )
    artifact_app = typer.Typer(
        help="Immutable artifact versions.", no_args_is_help=True
    )
    evidence_app = typer.Typer(help="Artifact evidence bindings.", no_args_is_help=True)
    trace_app = typer.Typer(
        help="Immutable task trace and memory records.", no_args_is_help=True
    )
    gate_app = typer.Typer(
        help="Compiled protocol promotion gates.", no_args_is_help=True
    )
    runtime_app = typer.Typer(
        help="Task Runtime project operations.", no_args_is_help=True
    )

    def current_root() -> Path:
        return Path(root() if callable(root) else root)

    def runtime(project: str) -> TaskRuntime:
        return TaskRuntime(current_root(), project=project)

    def emit(value: Any) -> None:
        console.print(
            yaml.safe_dump(value, sort_keys=False, allow_unicode=True).rstrip()
        )

    def json_mapping(raw: str, *, field: str) -> dict[str, Any]:
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise typer.BadParameter(f"{field} must be valid JSON: {exc.msg}") from exc
        if not isinstance(value, dict):
            raise typer.BadParameter(f"{field} must be a JSON object")
        return value

    def json_list(raw: str, *, field: str) -> list[Any]:
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise typer.BadParameter(f"{field} must be valid JSON: {exc.msg}") from exc
        if not isinstance(value, list):
            raise typer.BadParameter(f"{field} must be a JSON list")
        return value

    @task_app.command("create")
    def task_create(
        project: str = typer.Option(..., "--project"),
        task_id: str = typer.Option(..., "--task-id"),
        title: str = typer.Option(..., "--title"),
        goal: str = typer.Option(..., "--goal"),
        protocol_ref: str | None = typer.Option(None, "--protocol-ref"),
        input_profile_json: str | None = typer.Option(None, "--input-profile-json"),
        idempotency_key: str = typer.Option(..., "--idempotency-key"),
        allow_duplicate_goal: bool = typer.Option(False, "--allow-duplicate-goal"),
        independent_boundary_reason: str | None = typer.Option(
            None, "--independent-boundary-reason"
        ),
    ) -> None:
        emit(
            runtime(project).create_task(
                task_id=task_id,
                title=title,
                user_goal=goal,
                protocol_ref=protocol_ref,
                input_profile=(
                    json_mapping(input_profile_json, field="input_profile")
                    if input_profile_json is not None
                    else None
                ),
                idempotency_key=idempotency_key,
                allow_duplicate_goal=allow_duplicate_goal,
                independent_boundary_reason=independent_boundary_reason,
            )["task"]
        )

    @task_app.command("execute")
    def task_execute(
        project: str = typer.Option(..., "--project"),
        task_id: str = typer.Option(..., "--task-id"),
        live: bool = typer.Option(
            False,
            "--live",
            help="Execute one compiled node through its governed role executor.",
        ),
        work_item_id: str | None = typer.Option(None, "--work-item-id"),
        messages_path: Path | None = typer.Option(None, "--messages-path"),
        source_paths: list[Path] = typer.Option([], "--source-path"),
        external_context_request_path: Path | None = typer.Option(
            None, "--external-context-request"
        ),
        attempt_id: str | None = typer.Option(None, "--attempt-id"),
        idempotency_key: str = typer.Option("protocol-execute", "--idempotency-key"),
        timeout: int | None = typer.Option(None, "--timeout", min=1),
    ) -> None:
        """Prepare a protocol, or execute one exact node with ``--live``."""

        runner = ProductionProtocolRunner(current_root(), project=project)
        if not live:
            emit(runner.prepare(task_id))
            return
        if (
            not work_item_id
            or messages_path is None
            or external_context_request_path is None
        ):
            raise typer.BadParameter(
                "--live requires --work-item-id, --messages-path, and "
                "--external-context-request"
            )
        task_root = runner.runtime._task_dir(task_id).resolve(strict=True)
        resolved_messages = messages_path.resolve(strict=True)
        if (
            messages_path.is_symlink()
            or not resolved_messages.is_file()
            or not resolved_messages.is_relative_to(task_root)
        ):
            raise typer.BadParameter(
                "messages path must be a regular file inside the governed Task"
            )
        messages = json_list(
            resolved_messages.read_text(encoding="utf-8"), field="messages"
        )
        if external_context_request_path.is_symlink():
            raise typer.BadParameter(
                "external context request path may not be a symlink"
            )
        external_request = yaml.safe_load(
            external_context_request_path.read_text(encoding="utf-8")
        )
        if not isinstance(external_request, dict):
            raise typer.BadParameter("external context request must be a mapping")
        emit(
            runner.execute_node(
                task_id,
                work_item_id=work_item_id,
                messages=messages,
                source_paths=source_paths,
                external_context_request=external_request,
                attempt_id=attempt_id,
                idempotency_key=idempotency_key,
                timeout=timeout,
            )
        )

    @task_app.command("execute-blueprint-shards")
    def task_execute_blueprint_shards(
        project: str = typer.Option(..., "--project"),
        task_id: str = typer.Option(..., "--task-id"),
        total_chapters: int = typer.Option(..., "--total-chapters", min=1),
        volume_count: int = typer.Option(..., "--volume-count", min=1),
        blueprint_title: str = typer.Option(..., "--title"),
        writer_work_item_id: str = typer.Option(..., "--writer-work-item-id"),
        story_artifact_type: str = typer.Option(..., "--story-artifact-type"),
        candidate_gate_id: str = typer.Option(..., "--candidate-gate-id"),
        context_artifact_types: list[str] = typer.Option(
            ..., "--context-artifact-type"
        ),
        required_fields: list[str] = typer.Option(..., "--required-field"),
        writer_instruction_path: Path = typer.Option(..., "--writer-instruction"),
        external_context_request_path: Path = typer.Option(
            ..., "--external-context-request"
        ),
        timeout: int = typer.Option(600, "--timeout", min=1),
        retries_per_volume: int = typer.Option(
            2, "--retries-per-volume", min=1, max=5
        ),
        revision: int = typer.Option(1, "--revision", min=1),
        revision_guidance_path: Path | None = typer.Option(
            None, "--revision-guidance"
        ),
        volume_ids: list[str] = typer.Option([], "--volume"),
        baseline_revision: int | None = typer.Option(
            None, "--baseline-revision", min=1
        ),
        semantic_contract_path: Path = typer.Option(
            ..., "--semantic-contract"
        ),
        assembly_only_baseline: bool = typer.Option(False, "--assembly-only-baseline"),
    ) -> None:
        """Run resumable Writer shard generation and deterministic assembly."""

        from agent_runtime.narrative.blueprint_shards import (
            run_blueprint_shard_workflow,
        )

        emit(
            run_blueprint_shard_workflow(
                current_root(),
                project=project,
                task_id=task_id,
                total_chapters=total_chapters,
                volume_count=volume_count,
                blueprint_title=blueprint_title,
                writer_work_item_id=writer_work_item_id,
                story_artifact_type=story_artifact_type,
                candidate_gate_id=candidate_gate_id,
                context_artifact_types=context_artifact_types,
                required_fields=required_fields,
                writer_instruction_path=writer_instruction_path,
                external_context_request_path=external_context_request_path,
                timeout=timeout,
                retries_per_volume=retries_per_volume,
                revision=revision,
                revision_guidance_path=revision_guidance_path,
                volume_ids=volume_ids,
                baseline_revision=baseline_revision,
                semantic_contract_path=semantic_contract_path,
                assembly_only_baseline=assembly_only_baseline,
            )
        )

    @gate_app.command("record")
    def protocol_gate_record(
        project: str = typer.Option(..., "--project"),
        task_id: str = typer.Option(..., "--task-id"),
        gate_id: str = typer.Option(..., "--gate-id"),
        work_item_id: str = typer.Option(..., "--work-item-id"),
        evidence_kind: str = typer.Option(..., "--evidence-kind"),
        evidence_sha256: str = typer.Option(..., "--evidence-sha256"),
        attempt_id: str = typer.Option(..., "--attempt-id"),
        subject_version_ids: list[str] = typer.Option(..., "--subject-version-id"),
        actor: str = typer.Option(..., "--actor"),
        approval_receipt_path: Path | None = typer.Option(None, "--approval-receipt"),
        approval_signature_path: Path | None = typer.Option(
            None, "--approval-signature"
        ),
        idempotency_key: str = typer.Option(..., "--idempotency-key"),
    ) -> None:
        """Record a declared, hash-bound protocol gate pass."""

        emit(
            runtime(project).record_protocol_gate(
                task_id,
                gate_id=gate_id,
                work_item_id=work_item_id,
                evidence_kind=evidence_kind,
                evidence_sha256=evidence_sha256,
                attempt_id=attempt_id,
                subject_version_ids=subject_version_ids,
                actor=actor,
                idempotency_key=idempotency_key,
                approval_receipt_path=approval_receipt_path,
                approval_signature_path=approval_signature_path,
            )["protocol_gates"][gate_id]
        )

    @gate_app.command("revoke")
    def protocol_gate_revoke(
        project: str = typer.Option(..., "--project"),
        task_id: str = typer.Option(..., "--task-id"),
        gate_id: str = typer.Option(..., "--gate-id"),
        reason_code: str = typer.Option(..., "--reason-code"),
        feedback_digest: str = typer.Option(..., "--feedback-digest"),
        feedback_path: Path = typer.Option(..., "--feedback-path"),
        actor: str = typer.Option(..., "--actor"),
        idempotency_key: str = typer.Option(..., "--idempotency-key"),
    ) -> None:
        emit(
            runtime(project).revoke_protocol_gate(
                task_id,
                gate_id=gate_id,
                reason_code=reason_code,
                feedback_digest=feedback_digest,
                feedback_path=feedback_path,
                actor=actor,
                idempotency_key=idempotency_key,
            )
        )

    @task_app.command("classify")
    def task_classify(
        input_profile_json: str = typer.Option(..., "--input-profile-json"),
    ) -> None:
        """Preview the fail-closed execution tier without creating a Task."""

        emit(
            TaskInputClassifier(current_root()).classify(
                json_mapping(input_profile_json, field="input_profile")
            )
        )

    @task_app.command("classify-set")
    def task_classify_set(
        project: str = typer.Option(..., "--project"),
        task_id: str = typer.Option(..., "--task-id"),
        input_profile_json: str = typer.Option(..., "--input-profile-json"),
        producer_attempt_id: str = typer.Option(..., "--producer-attempt-id"),
        idempotency_key: str = typer.Option(..., "--idempotency-key"),
    ) -> None:
        """Record the profile returned by a successful Supervisor intake Attempt."""

        emit(
            runtime(project).classify_task_input(
                task_id,
                input_profile=json_mapping(input_profile_json, field="input_profile"),
                producer_attempt_id=producer_attempt_id,
                idempotency_key=idempotency_key,
            )["task"]
        )

    @task_app.command("show")
    def task_show(
        project: str = typer.Option(..., "--project"),
        task_id: str = typer.Option(..., "--task-id"),
    ) -> None:
        emit(runtime(project).load_task(task_id))

    @task_app.command("list")
    def task_list(
        project: str = typer.Option(..., "--project"),
        include_legacy: bool = typer.Option(
            False, "--include-legacy", help="Include legacy runs/task_id entries"
        ),
    ) -> None:
        emit(
            {
                "project": project,
                "tasks": runtime(project).list_tasks(include_legacy=include_legacy),
            }
        )

    def task_transition(
        project: str, task_id: str, status: str, idempotency_key: str
    ) -> None:
        emit(
            runtime(project).transition_task(
                task_id,
                status=status,
                idempotency_key=idempotency_key,
            )["task"]
        )

    @task_app.command("pause")
    def task_pause(
        project: str = typer.Option(..., "--project"),
        task_id: str = typer.Option(..., "--task-id"),
        idempotency_key: str = typer.Option(..., "--idempotency-key"),
    ) -> None:
        task_transition(project, task_id, "paused", idempotency_key)

    @task_app.command("resume")
    def task_resume(
        project: str = typer.Option(..., "--project"),
        task_id: str = typer.Option(..., "--task-id"),
        status: str = typer.Option("running", "--status", help="ready or running"),
        idempotency_key: str = typer.Option(..., "--idempotency-key"),
    ) -> None:
        if status not in {"ready", "running"}:
            raise typer.BadParameter("resume status must be ready or running")
        task_transition(project, task_id, status, idempotency_key)

    @task_app.command("cancel")
    def task_cancel(
        project: str = typer.Option(..., "--project"),
        task_id: str = typer.Option(..., "--task-id"),
        idempotency_key: str = typer.Option(..., "--idempotency-key"),
    ) -> None:
        task_transition(project, task_id, "cancelled", idempotency_key)

    @job_app.command("create")
    def job_create(
        project: str = typer.Option(..., "--project"),
        task_id: str = typer.Option(..., "--task-id"),
        job_id: str = typer.Option(..., "--job-id"),
        kind: str = typer.Option("candidate", "--kind"),
        strategy: str = typer.Option(..., "--strategy"),
        idempotency_key: str = typer.Option(..., "--idempotency-key"),
    ) -> None:
        emit(
            runtime(project).create_job(
                task_id,
                job_id=job_id,
                kind=kind,
                strategy=strategy,
                idempotency_key=idempotency_key,
            )["jobs"][job_id]
        )

    @work_app.command("create")
    def work_create(
        project: str = typer.Option(..., "--project"),
        task_id: str = typer.Option(..., "--task-id"),
        job_id: str = typer.Option("job-main", "--job-id"),
        work_item_id: str = typer.Option(..., "--work-item-id"),
        kind: str = typer.Option(..., "--kind"),
        title: str = typer.Option(..., "--title"),
        depends_on: list[str] = typer.Option([], "--depends-on"),
        assigned_agent_id: str | None = typer.Option(None, "--assigned-agent-id"),
        agent_manifest_revision: int | None = typer.Option(
            None, "--agent-manifest-revision"
        ),
        canonical_snapshot_id: str | None = typer.Option(
            None, "--canonical-snapshot-id"
        ),
        effective_contract_hash: str | None = typer.Option(
            None, "--effective-contract-hash"
        ),
        requires_user_acceptance: bool = typer.Option(
            False,
            "--requires-user-acceptance",
            help="Keep the WorkItem gated until explicit user acceptance.",
        ),
        idempotency_key: str = typer.Option(..., "--idempotency-key"),
    ) -> None:
        emit(
            runtime(project).create_work_item(
                task_id,
                job_id=job_id,
                work_item_id=work_item_id,
                kind=kind,
                title=title,
                depends_on=depends_on,
                assigned_agent_id=assigned_agent_id,
                agent_manifest_revision=agent_manifest_revision,
                canonical_snapshot_id=canonical_snapshot_id,
                effective_contract_hash=effective_contract_hash,
                requires_user_acceptance=requires_user_acceptance,
                idempotency_key=idempotency_key,
            )["work_items"][work_item_id]
        )

    @work_app.command("materialize-collaboration")
    def work_materialize_collaboration(
        project: str = typer.Option(..., "--project"),
        task_id: str = typer.Option(..., "--task-id"),
        domain: str = typer.Option(..., "--domain"),
        job_id: str = typer.Option("job-main", "--job-id"),
        idempotency_prefix: str = typer.Option(
            ...,
            "--idempotency-prefix",
        ),
    ) -> None:
        """Compile the registered Project Agent DAG into Task Runtime WorkItems."""

        from agent_runtime.project_agents import (
            ExpertCollaborationScheduler,
            ProjectAgentRegistry,
        )
        from agent_runtime.project_truth import ProjectTruthStore

        task_runtime = runtime(project)
        project_root = current_root() / "projects" / task_runtime.project
        registry = ProjectAgentRegistry(ProjectTruthStore(project_root))
        projection = ExpertCollaborationScheduler().materialize(
            task_runtime,
            registry,
            task_id=task_id,
            domain=domain,
            job_id=job_id,
            idempotency_prefix=idempotency_prefix,
        )
        emit(
            {
                "project": project,
                "task_id": task_id,
                "work_items": projection["work_items"],
            }
        )

    @work_app.command("status")
    def work_status(
        project: str = typer.Option(..., "--project"),
        task_id: str = typer.Option(..., "--task-id"),
        work_item_id: str = typer.Option(..., "--work-item-id"),
        status: str = typer.Option(..., "--status"),
        idempotency_key: str = typer.Option(..., "--idempotency-key"),
        reason_code: str | None = typer.Option(None, "--reason-code"),
        feedback_digest: str | None = typer.Option(None, "--feedback-digest"),
        feedback_path: Path | None = typer.Option(None, "--feedback-path"),
    ) -> None:
        emit(
            runtime(project).transition_work_item(
                task_id,
                work_item_id=work_item_id,
                status=status,
                idempotency_key=idempotency_key,
                reason_code=reason_code,
                feedback_digest=feedback_digest,
                feedback_path=feedback_path,
            )["work_items"][work_item_id]
        )

    @attempt_app.command("schedule")
    def attempt_schedule(
        project: str = typer.Option(..., "--project"),
        task_id: str = typer.Option(..., "--task-id"),
        work_item_id: str = typer.Option(..., "--work-item-id"),
        attempt_id: str = typer.Option(..., "--attempt-id"),
        worker: str = typer.Option(..., "--worker"),
        provider: str = typer.Option(..., "--provider"),
        execution_contract: str = typer.Option(..., "--execution-contract-json"),
        idempotency_key: str = typer.Option(..., "--idempotency-key"),
    ) -> None:
        emit(
            runtime(project).schedule_attempt(
                task_id,
                work_item_id=work_item_id,
                attempt_id=attempt_id,
                worker=worker,
                provider=provider,
                execution_contract=json_mapping(
                    execution_contract, field="execution_contract"
                ),
                idempotency_key=idempotency_key,
            )["attempts"][attempt_id]
        )

    @attempt_app.command("status")
    def attempt_status(
        project: str = typer.Option(..., "--project"),
        task_id: str = typer.Option(..., "--task-id"),
        attempt_id: str = typer.Option(..., "--attempt-id"),
        status: str = typer.Option(..., "--status"),
        outcome: str = typer.Option("{}", "--outcome-json"),
        idempotency_key: str = typer.Option(..., "--idempotency-key"),
    ) -> None:
        emit(
            runtime(project).transition_attempt(
                task_id,
                attempt_id=attempt_id,
                status=status,
                outcome=json_mapping(outcome, field="outcome"),
                idempotency_key=idempotency_key,
            )["attempts"][attempt_id]
        )

    @attempt_app.command("execute-role")
    def attempt_execute_role(
        project: str = typer.Option(..., "--project"),
        task_id: str = typer.Option(..., "--task-id"),
        work_item_id: str = typer.Option(..., "--work-item-id"),
        attempt_id: str = typer.Option(..., "--attempt-id"),
        role: str = typer.Option(..., "--role"),
        messages_path: Path = typer.Option(..., "--messages-path"),
        source_paths: list[Path] = typer.Option([], "--source-path"),
        external_context_request_path: Path = typer.Option(
            ...,
            "--external-context-request",
        ),
        idempotency_key: str = typer.Option(..., "--idempotency-key"),
        timeout: int | None = typer.Option(None, "--timeout", min=1),
    ) -> None:
        """Execute one configured role and bind its receipt to a v2 Attempt."""

        root = current_root()
        raw_task_root = root / "projects" / project / "runtime" / "tasks" / task_id
        lexical_task_root = raw_task_root.absolute()
        lexical_messages_path = messages_path.absolute()
        try:
            lexical_messages_path.relative_to(lexical_task_root)
            current = root.absolute()
            for part in lexical_messages_path.relative_to(current).parts:
                current = current / part
                if current.is_symlink():
                    raise ValueError(f"symlink ancestor: {current}")
            task_root = lexical_task_root.resolve(strict=True)
            resolved_messages_path = messages_path.resolve(strict=True)
            resolved_messages_path.relative_to(task_root)
        except (OSError, ValueError) as exc:
            raise typer.BadParameter(
                "messages path must be an existing file inside the governed task"
            ) from exc
        if not resolved_messages_path.is_file():
            raise typer.BadParameter("messages path must be a regular file")
        raw_messages = resolved_messages_path.read_text(encoding="utf-8")
        messages = json_list(raw_messages, field="messages")
        if external_context_request_path.is_symlink():
            raise typer.BadParameter(
                "external context request path may not be a symlink"
            )
        loaded_request = yaml.safe_load(
            external_context_request_path.read_text(encoding="utf-8")
        )
        if not isinstance(loaded_request, dict):
            raise typer.BadParameter("external context request must be a mapping")
        external_context_request = loaded_request
        emit(
            RoleAttemptExecutor(root, project=project).execute(
                task_id=task_id,
                work_item_id=work_item_id,
                attempt_id=attempt_id,
                role=role,
                messages=messages,
                source_paths=source_paths,
                external_context_request=external_context_request,
                idempotency_key=idempotency_key,
                timeout=timeout,
            )
        )

    @artifact_app.command("record")
    def artifact_record(
        project: str = typer.Option(..., "--project"),
        task_id: str = typer.Option(..., "--task-id"),
        artifact_id: str = typer.Option(..., "--artifact-id"),
        version_id: str = typer.Option(..., "--version-id"),
        attempt_id: str = typer.Option(..., "--attempt-id"),
        path: Path = typer.Option(..., "--path"),
        media_type: str = typer.Option(..., "--media-type"),
        idempotency_key: str = typer.Option(..., "--idempotency-key"),
    ) -> None:
        emit(
            runtime(project).record_artifact_version(
                task_id,
                artifact_id=artifact_id,
                version_id=version_id,
                attempt_id=attempt_id,
                path=path,
                media_type=media_type,
                idempotency_key=idempotency_key,
            )["artifacts"][version_id]
        )

    @artifact_app.command("select")
    def artifact_select(
        project: str = typer.Option(..., "--project"),
        task_id: str = typer.Option(..., "--task-id"),
        version_id: str = typer.Option(..., "--version-id"),
        idempotency_key: str = typer.Option(..., "--idempotency-key"),
    ) -> None:
        emit(
            runtime(project).select_artifact_version(
                task_id, version_id=version_id, idempotency_key=idempotency_key
            )
        )

    @artifact_app.command("disposition")
    def artifact_disposition(
        project: str = typer.Option(..., "--project"),
        task_id: str = typer.Option(..., "--task-id"),
        version_id: str = typer.Option(..., "--version-id"),
        disposition: str = typer.Option(..., "--disposition"),
        reason_code: str = typer.Option(..., "--reason-code"),
        feedback_digest: str = typer.Option(..., "--feedback-digest"),
        feedback_path: Path | None = typer.Option(None, "--feedback-path"),
        idempotency_key: str = typer.Option(..., "--idempotency-key"),
    ) -> None:
        emit(
            runtime(project).change_artifact_disposition(
                task_id,
                version_id=version_id,
                disposition=disposition,
                reason_code=reason_code,
                feedback_digest=feedback_digest,
                feedback_path=feedback_path,
                idempotency_key=idempotency_key,
            )["artifacts"][version_id]
        )

    @evidence_app.command("bind")
    def evidence_bind(
        project: str = typer.Option(..., "--project"),
        task_id: str = typer.Option(..., "--task-id"),
        binding_id: str = typer.Option(..., "--binding-id"),
        version_id: str = typer.Option(..., "--version-id"),
        input_manifest_hash: str = typer.Option(..., "--input-manifest-hash"),
        index_snapshot_id: str = typer.Option(..., "--index-snapshot-id"),
        source_hashes: str = typer.Option(..., "--source-hashes-json"),
        audit: str = typer.Option("{}", "--audit-json"),
        idempotency_key: str = typer.Option(..., "--idempotency-key"),
    ) -> None:
        emit(
            runtime(project).bind_evidence(
                task_id,
                binding_id=binding_id,
                version_id=version_id,
                input_manifest_hash=input_manifest_hash,
                index_snapshot_id=index_snapshot_id,
                source_hashes=json_mapping(source_hashes, field="source_hashes"),
                audit=json_mapping(audit, field="audit"),
                idempotency_key=idempotency_key,
            )["evidence_bindings"][binding_id]
        )

    @evidence_app.command("verify")
    def evidence_verify(
        project: str = typer.Option(..., "--project"),
        task_id: str = typer.Option(..., "--task-id"),
    ) -> None:
        emit(runtime(project).verify_evidence(task_id))

    @trace_app.command("record")
    def trace_record(
        project: str = typer.Option(..., "--project"),
        task_id: str = typer.Option(..., "--task-id"),
        record_id: str = typer.Option(..., "--record-id"),
        record_type: str = typer.Option(..., "--record-type"),
        producer: str = typer.Option(..., "--producer"),
        producer_role: str = typer.Option(..., "--producer-role"),
        path: Path = typer.Option(..., "--path"),
        metadata: str = typer.Option("{}", "--metadata-json"),
        idempotency_key: str = typer.Option(..., "--idempotency-key"),
    ) -> None:
        emit(
            runtime(project).record_trace(
                task_id,
                record_id=record_id,
                record_type=record_type,
                producer=producer,
                producer_role=producer_role,
                path=path,
                metadata=json_mapping(metadata, field="metadata"),
                idempotency_key=idempotency_key,
            )["trace_records"][record_id]
        )

    @runtime_app.command("project")
    @runtime_app.command("rebuild")
    def runtime_rebuild(project: str = typer.Option(..., "--project")) -> None:
        emit(runtime(project).rebuild_project())

    @runtime_app.command("doctor")
    def runtime_doctor(project: str = typer.Option(..., "--project")) -> None:
        report = runtime(project).doctor_project()
        emit(report)
        if not report["ok"]:
            raise typer.Exit(code=1)

    @runtime_app.command("protocol-canary")
    def runtime_protocol_canary(
        iterations: int = typer.Option(10, "--iterations", min=1),
        state_root: Path | None = typer.Option(None, "--state-root"),
    ) -> None:
        target = (
            state_root or current_root() / ".agentlab_runtime" / "protocol_canaries"
        )
        report = run_protocol_canaries(
            current_root(),
            state_root=target,
            iterations=iterations,
        )
        emit(report)
        if not report["ok"]:
            raise typer.Exit(code=1)

    @runtime_app.command("migrate-legacy")
    def runtime_migrate(
        project: str = typer.Option(..., "--project"),
        apply: bool = typer.Option(False, "--apply"),
        expected_plan_hash: str | None = typer.Option(None, "--expected-plan-hash"),
    ) -> None:
        migrator = LegacyRunMigrator(current_root(), project=project)
        if not apply:
            emit(migrator.plan())
            return
        if not expected_plan_hash:
            raise typer.BadParameter("--expected-plan-hash is required with --apply")
        emit(migrator.apply(expected_plan_hash=expected_plan_hash))

    @runtime_app.command("compact-logs")
    def runtime_compact_logs(
        project: str = typer.Option(..., "--project"),
        apply: bool = typer.Option(False, "--apply"),
        expected_plan_hash: str | None = typer.Option(None, "--expected-plan-hash"),
        older_than_days: int = typer.Option(7, "--older-than-days", min=1),
    ) -> None:
        retention = AttemptLogRetention(current_root(), project=project)
        if not apply:
            emit(retention.plan(older_than_days=older_than_days))
            return
        if not expected_plan_hash:
            raise typer.BadParameter("--expected-plan-hash is required with --apply")
        emit(
            retention.apply(
                expected_plan_hash=expected_plan_hash,
                older_than_days=older_than_days,
            )
        )

    app.add_typer(task_app, name="task")
    app.add_typer(job_app, name="job")
    app.add_typer(work_app, name="work-item")
    app.add_typer(attempt_app, name="attempt")
    app.add_typer(artifact_app, name="artifact")
    app.add_typer(evidence_app, name="evidence")
    app.add_typer(trace_app, name="trace")
    app.add_typer(gate_app, name="protocol-gate")
    app.add_typer(runtime_app, name="runtime")
    app.add_typer(
        runtime_app,
        name="runtime-v2",
        deprecated=True,
        help="Compatibility alias for `runtime`.",
    )
