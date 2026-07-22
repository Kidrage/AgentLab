"""Operator CLI for the append-only Task Runtime v2."""

from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
from typing import Any

import typer
import yaml
from rich.console import Console

from agent_runtime.task_runtime_v2 import (
    AttemptLogRetention,
    LegacyRunMigrator,
    TaskInputClassifier,
    TaskRuntime,
)


RootProvider = Path | Callable[[], Path]


def register_task_runtime_commands(
    app: typer.Typer, root: RootProvider, console: Console
) -> None:
    """Register the stable v2 command surface on an AgentLab Typer app."""

    task_app = typer.Typer(help="Task Runtime v2 business-goal lifecycle.", no_args_is_help=True)
    job_app = typer.Typer(help="Execution strategies under a Task.", no_args_is_help=True)
    work_app = typer.Typer(help="Schedulable units under a Job.", no_args_is_help=True)
    attempt_app = typer.Typer(help="Immutable execution attempts.", no_args_is_help=True)
    artifact_app = typer.Typer(help="Immutable artifact versions.", no_args_is_help=True)
    evidence_app = typer.Typer(help="Artifact evidence bindings.", no_args_is_help=True)
    trace_app = typer.Typer(help="Immutable task trace and memory records.", no_args_is_help=True)
    runtime_app = typer.Typer(help="Task Runtime v2 project operations.", no_args_is_help=True)

    def current_root() -> Path:
        return Path(root() if callable(root) else root)

    def runtime(project: str) -> TaskRuntime:
        return TaskRuntime(current_root(), project=project)

    def emit(value: Any) -> None:
        console.print(yaml.safe_dump(value, sort_keys=False, allow_unicode=True).rstrip())

    def json_mapping(raw: str, *, field: str) -> dict[str, Any]:
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise typer.BadParameter(f"{field} must be valid JSON: {exc.msg}") from exc
        if not isinstance(value, dict):
            raise typer.BadParameter(f"{field} must be a JSON object")
        return value

    @task_app.command("create")
    def task_create(
        project: str = typer.Option(..., "--project"),
        task_id: str = typer.Option(..., "--task-id"),
        title: str = typer.Option(..., "--title"),
        goal: str = typer.Option(..., "--goal"),
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

    @task_app.command("show")
    def task_show(
        project: str = typer.Option(..., "--project"),
        task_id: str = typer.Option(..., "--task-id"),
    ) -> None:
        emit(runtime(project).load_task(task_id))

    @task_app.command("list")
    def task_list(project: str = typer.Option(..., "--project")) -> None:
        emit({"project": project, "tasks": runtime(project).list_tasks()})

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
                idempotency_key=idempotency_key,
            )["work_items"][work_item_id]
        )

    @work_app.command("status")
    def work_status(
        project: str = typer.Option(..., "--project"),
        task_id: str = typer.Option(..., "--task-id"),
        work_item_id: str = typer.Option(..., "--work-item-id"),
        status: str = typer.Option(..., "--status"),
        idempotency_key: str = typer.Option(..., "--idempotency-key"),
    ) -> None:
        emit(
            runtime(project).transition_work_item(
                task_id,
                work_item_id=work_item_id,
                status=status,
                idempotency_key=idempotency_key,
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
    app.add_typer(runtime_app, name="runtime-v2")
