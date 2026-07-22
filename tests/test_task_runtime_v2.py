from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml
import pytest

from agent_runtime.task_runtime_v2 import (
    ActiveAttemptExists,
    DuplicateBusinessGoal,
    EntityNotFound,
    EntityAlreadyExists,
    IdempotencyConflict,
    InvalidTransition,
    LedgerIntegrityError,
    TaskRuntime,
)
from agent_runtime.knowledge_system.sources import SourceCollector
from agent_runtime.config_loader import load_agentlab_configs
from task_runtime_v2_support import execute_role_with_output


_GOVERNED_PROFILE = {
    "kind": "prose_build",
    "scope": "multi_chapter",
    "target_count": 0,
    "canon_impact": "canonical",
    "risk_flags": ["longform_continuity"],
}


def _record_brain_plan_gates(
    runtime: TaskRuntime, tmp_path: Path, task_id: str
) -> None:
    scope = {
        "schema_version": "brain-scope-decision/v1",
        "approved": True,
        "chapter_start": 1,
        "chapter_end": 1,
        "target_cjk_chars": 3000,
        "quality_thresholds": {"overall": 0.8},
    }
    plan = {
        "schema_version": "task-execution-plan/v1",
        "status": "approved",
        "route": "governed_pipeline",
        "work_items": ["writer", "reviewer"],
    }
    runtime.create_work_item(
        task_id,
        job_id="job-main",
        work_item_id="brain-plan",
        kind="planning",
        title="Brain plan",
        idempotency_key="work-brain-plan",
    )
    outcome = execute_role_with_output(
        runtime,
        tmp_path,
        task_id=task_id,
        work_item_id="brain-plan",
        attempt_id="brain-plan-attempt",
        role="Supervisor",
        output={"brain_scope_decision": scope, "execution_plan": plan},
    )
    staging = (
        tmp_path
        / "projects"
        / "Demo"
        / "runtime"
        / "tasks"
        / task_id
        / "records"
        / "staging"
    )
    staging.mkdir(parents=True, exist_ok=True)
    for record_type in ("brain_scope_decision", "execution_plan"):
        source = staging / f"{record_type}.yml"
        payload = dict(scope if record_type == "brain_scope_decision" else plan)
        payload["producer_attempt_id"] = "brain-plan-attempt"
        payload["source_output_sha256"] = outcome["output_sha256"]
        source.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
        runtime.record_trace(
            task_id,
            record_id=f"record-{record_type}",
            record_type=record_type,
            producer="codex",
            producer_role="Supervisor",
            path=source,
            idempotency_key=f"record-{record_type}",
        )


def test_create_task_appends_authoritative_event_and_rebuilds_projection(
    tmp_path: Path,
) -> None:
    runtime = TaskRuntime(tmp_path, project="Demo")

    created = runtime.create_task(
        task_id="task-demo-001",
        title="Deliver one governed result",
        user_goal="Produce and review one result without splitting the goal.",
        idempotency_key="request-001",
    )

    assert created["task"] == {
        "task_id": "task-demo-001",
        "project": "Demo",
        "title": "Deliver one governed result",
        "user_goal": "Produce and review one result without splitting the goal.",
        "goal_fingerprint": created["task"]["goal_fingerprint"],
        "input_classification": created["task"]["input_classification"],
        "status": "created",
        "created_at": created["task"]["created_at"],
        "updated_at": created["task"]["updated_at"],
    }
    assert created["last_event_sequence"] == 1
    assert created["jobs"] == {
        "job-main": {
            "job_id": "job-main",
            "kind": "inline",
            "status": "queued",
            "created_at": created["task"]["created_at"],
            "updated_at": created["task"]["created_at"],
        }
    }

    task_dir = tmp_path / "projects" / "Demo" / "runtime" / "tasks" / "task-demo-001"
    events = [
        json.loads(line)
        for line in (task_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(events) == 1
    assert events[0]["schema_version"] == "task-runtime-event/v2"
    assert events[0]["event_type"] == "TASK_CREATED"
    assert events[0]["previous_event_hash"] is None
    assert len(events[0]["event_hash"]) == 64

    projection_path = task_dir / "projections" / "task.yml"
    projection_path.write_text("corrupt: true\n", encoding="utf-8")
    rebuilt = runtime.rebuild_task("task-demo-001")

    assert rebuilt == created
    assert yaml.safe_load(projection_path.read_text(encoding="utf-8")) == created


def test_create_task_is_idempotent_and_rejects_key_reuse(tmp_path: Path) -> None:
    runtime = TaskRuntime(tmp_path, project="Demo")
    command = {
        "task_id": "task-demo-001",
        "title": "One goal",
        "user_goal": "Keep all retries under one task.",
        "idempotency_key": "request-001",
    }

    first = runtime.create_task(**command)
    repeated = runtime.create_task(**command)

    assert repeated == first
    ledger = (
        tmp_path
        / "projects"
        / "Demo"
        / "runtime"
        / "tasks"
        / "task-demo-001"
        / "events.jsonl"
    )
    assert len(ledger.read_text(encoding="utf-8").splitlines()) == 1

    with pytest.raises(IdempotencyConflict):
        runtime.create_task(
            task_id="task-demo-001",
            title="Changed command",
            user_goal="This must not reuse request-001.",
            idempotency_key="request-001",
        )

    with pytest.raises(EntityAlreadyExists):
        runtime.create_task(
            task_id="task-demo-001",
            title="A second Task-created event is forbidden",
            user_goal="Do not poison the authoritative ledger.",
            idempotency_key="request-002",
        )
    assert len(ledger.read_text(encoding="utf-8").splitlines()) == 1


def test_concurrent_duplicate_command_appends_exactly_one_event(tmp_path: Path) -> None:
    runtime = TaskRuntime(tmp_path, project="Demo")
    command = {
        "task_id": "task-concurrent",
        "title": "One concurrent goal",
        "user_goal": "Serialize duplicate callers through the ledger lock.",
        "idempotency_key": "request-concurrent",
    }

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: runtime.create_task(**command), range(2)))

    assert results[0] == results[1]
    ledger = (
        tmp_path
        / "projects"
        / "Demo"
        / "runtime"
        / "tasks"
        / "task-concurrent"
        / "events.jsonl"
    )
    assert len(ledger.read_text(encoding="utf-8").splitlines()) == 1


def test_same_business_goal_cannot_open_a_second_task_without_explicit_override(
    tmp_path: Path,
) -> None:
    runtime = TaskRuntime(tmp_path, project="Demo")
    first = runtime.create_task(
        task_id="task-one",
        title="Initial delivery",
        user_goal="Generate and review chapters one through twenty.",
        idempotency_key="request-one",
    )

    with pytest.raises(DuplicateBusinessGoal, match="task-one"):
        runtime.create_task(
            task_id="task-two",
            title="A misleading new task",
            user_goal="  GENERATE   AND REVIEW chapters one through twenty. ",
            idempotency_key="request-two",
        )

    overridden = runtime.create_task(
        task_id="task-independent",
        title="Explicit independent acceptance boundary",
        user_goal="Generate and review chapters one through twenty.",
        idempotency_key="request-independent",
        allow_duplicate_goal=True,
        independent_boundary_reason="This result has an independent approval boundary.",
    )
    assert first["task"]["goal_fingerprint"] == overridden["task"]["goal_fingerprint"]
    assert overridden["task"]["duplicate_goal_override"] == {
        "independent_boundary_reason": (
            "This result has an independent approval boundary."
        )
    }


def test_chapter_and_review_units_stay_inside_one_task_as_work_items(
    tmp_path: Path,
) -> None:
    runtime = TaskRuntime(tmp_path, project="Demo")
    runtime.create_task(
        task_id="task-book",
        title="Produce one book",
        user_goal="Generate and review chapters under one stable task.",
        idempotency_key="request-book",
    )

    projection = runtime.create_work_item(
        "task-book",
        job_id="job-main",
        work_item_id="chapter-001",
        kind="chapter",
        title="Draft chapter 1",
        idempotency_key="work-chapter-001",
    )

    assert projection["task"]["task_id"] == "task-book"
    assert projection["work_items"]["chapter-001"]["job_id"] == "job-main"
    assert projection["work_items"]["chapter-001"]["status"] == "ready"
    tasks_root = tmp_path / "projects" / "Demo" / "runtime" / "tasks"
    assert [path.name for path in tasks_root.iterdir() if path.is_dir()] == ["task-book"]

    with pytest.raises(EntityNotFound):
        runtime.create_work_item(
            "task-book",
            job_id="job-missing",
            work_item_id="review-001",
            kind="review",
            title="Review chapter 1",
            idempotency_key="work-review-001",
        )


def test_alternative_candidate_strategy_is_a_job_not_another_task(
    tmp_path: Path,
) -> None:
    runtime = TaskRuntime(tmp_path, project="Demo")
    runtime.create_task(
        task_id="task-book",
        title="Produce one book",
        user_goal="Compare candidate strategies under one business goal.",
        idempotency_key="request-book",
    )

    projection = runtime.create_job(
        "task-book",
        job_id="job-alternative",
        kind="candidate",
        strategy="hermes-ark",
        idempotency_key="job-alternative",
    )

    assert set(projection["jobs"]) == {"job-main", "job-alternative"}
    assert projection["jobs"]["job-alternative"]["strategy"] == "hermes-ark"
    tasks_root = tmp_path / "projects" / "Demo" / "runtime" / "tasks"
    assert [path.name for path in tasks_root.iterdir() if path.is_dir()] == ["task-book"]


def test_retries_are_unique_attempts_with_one_active_lease_per_work_item(
    tmp_path: Path,
) -> None:
    runtime = TaskRuntime(tmp_path, project="Demo")
    runtime.create_task(
        task_id="task-book",
        title="Produce one book",
        user_goal="Keep execution retries traceable without creating more tasks.",
        input_profile=_GOVERNED_PROFILE,
        idempotency_key="request-book",
    )
    runtime.create_work_item(
        "task-book",
        job_id="job-main",
        work_item_id="chapter-001",
        kind="chapter",
        title="Draft chapter 1",
        idempotency_key="work-chapter-001",
    )
    _record_brain_plan_gates(runtime, tmp_path, "task-book")

    first = runtime.schedule_attempt(
        "task-book",
        work_item_id="chapter-001",
        attempt_id="attempt-001",
        worker="hermes",
        provider="ark",
        execution_contract={
            "skill": "ark-video",
            "model_role": "visual",
            "role": "ArtifactProducer",
            "input_tier": "L3",
            "route": "governed_pipeline",
        },
        idempotency_key="attempt-001",
    )
    assert first["attempts"]["attempt-001"]["ordinal"] == 1
    assert first["attempts"]["attempt-001"]["status"] == "scheduled"

    with pytest.raises(ActiveAttemptExists):
        runtime.schedule_attempt(
            "task-book",
            work_item_id="chapter-001",
            attempt_id="attempt-002",
            worker="claude",
            provider="ark",
            execution_contract={
                "skill": "ark-video",
                "model_role": "visual",
                "role": "ArtifactProducer",
                "input_tier": "L3",
                "route": "governed_pipeline",
            },
            idempotency_key="attempt-002-too-early",
        )

    runtime.transition_attempt(
        "task-book",
        attempt_id="attempt-001",
        status="running",
        idempotency_key="attempt-001-running",
    )
    runtime.transition_attempt(
        "task-book",
        attempt_id="attempt-001",
        status="failed",
        idempotency_key="attempt-001-failed",
        outcome={"error_class": "upstream_502", "retryable": True},
    )
    retried = runtime.schedule_attempt(
        "task-book",
        work_item_id="chapter-001",
        attempt_id="attempt-002",
        worker="claude",
        provider="ark",
        execution_contract={
            "skill": "ark-video",
            "model_role": "visual",
            "role": "ArtifactProducer",
            "input_tier": "L3",
            "route": "governed_pipeline",
        },
        idempotency_key="attempt-002",
    )

    assert retried["attempts"]["attempt-002"]["ordinal"] == 2
    assert retried["work_items"]["chapter-001"]["active_attempt_id"] == "attempt-002"
    assert len(retried["attempts"]) == 3


def test_artifact_selection_requires_a_successful_attempt_and_bound_evidence(
    tmp_path: Path,
) -> None:
    runtime = TaskRuntime(tmp_path, project="Demo")
    runtime.create_task(
        task_id="task-book",
        title="Produce one book",
        user_goal="Select a candidate with immutable provenance.",
        input_profile=_GOVERNED_PROFILE,
        legacy_source={"run_path": "projects/Demo/runs/task-book"},
        idempotency_key="request-book",
    )
    runtime.create_work_item(
        "task-book",
        job_id="job-main",
        work_item_id="chapter-001",
        kind="chapter",
        title="Draft chapter 1",
        idempotency_key="work-chapter-001",
    )
    _record_brain_plan_gates(runtime, tmp_path, "task-book")
    attempt_outcome = execute_role_with_output(
        runtime,
        tmp_path,
        task_id="task-book",
        work_item_id="chapter-001",
        attempt_id="attempt-001",
        role="Writer",
        output={"candidate": "Only candidate text belongs here."},
    )
    artifact_path = (
        tmp_path
        / "projects"
        / "Demo"
        / "runtime"
        / "tasks"
        / "task-book"
        / "artifacts"
        / "chapter-001-v1.txt"
    )
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_text("Only candidate text belongs here.\n", encoding="utf-8")

    recorded = runtime.record_artifact_version(
        "task-book",
        artifact_id="chapter-001",
        version_id="chapter-001-v1",
        attempt_id="attempt-001",
        path=artifact_path,
        media_type="text/plain",
        idempotency_key="artifact-v1",
    )
    digest = recorded["artifacts"]["chapter-001-v1"]["sha256"]
    assert len(digest) == 64
    assert recorded["artifacts"]["chapter-001-v1"]["producer_attempt_id"] == "attempt-001"
    immutable_path = (
        tmp_path
        / "projects"
        / "Demo"
        / "runtime"
        / "tasks"
        / "task-book"
        / recorded["artifacts"]["chapter-001-v1"]["path"]
    )
    assert immutable_path != artifact_path
    assert immutable_path.read_bytes() == artifact_path.read_bytes()

    with pytest.raises(EntityNotFound):
        runtime.select_artifact_version(
            "task-book",
            version_id="chapter-001-v1",
            idempotency_key="select-before-evidence",
        )

    bound = runtime.bind_evidence(
        "task-book",
        binding_id="evidence-chapter-001-v1",
        version_id="chapter-001-v1",
        input_manifest_hash="a" * 64,
        index_snapshot_id="rag-snapshot-001",
        source_hashes={"chapter-card-001": "b" * 64, "world-rules": "c" * 64},
        audit={"verdict": "pass", "blocking_findings": 0},
        idempotency_key="evidence-v1",
    )
    assert bound["evidence_bindings"]["evidence-chapter-001-v1"]["version_id"] == "chapter-001-v1"
    execution_receipt = bound["evidence_bindings"]["evidence-chapter-001-v1"][
        "execution_receipt"
    ]
    assert execution_receipt["attempt_id"] == "attempt-001"
    assert execution_receipt["worker"] == "claude_code"
    assert execution_receipt["provider"] == "deepseek"
    assert execution_receipt["outcome"] == attempt_outcome

    artifact_path.write_text("a later mutable candidate revision\n", encoding="utf-8")
    assert runtime.verify_evidence("task-book")["ok"] is True

    immutable_path.write_text("tampered candidate\n", encoding="utf-8")
    with pytest.raises(LedgerIntegrityError, match="SHA256"):
        runtime.select_artifact_version(
            "task-book",
            version_id="chapter-001-v1",
            idempotency_key="select-tampered",
        )
    immutable_path.write_text("Only candidate text belongs here.\n", encoding="utf-8")

    selected = runtime.select_artifact_version(
        "task-book",
        version_id="chapter-001-v1",
        idempotency_key="select-v1",
    )
    assert selected["selected_artifact_version"] == "chapter-001-v1"
    assert runtime.verify_evidence("task-book")["ok"] is True
    for work_item_id, work_item in selected["work_items"].items():
        if work_item["status"] != "accepted":
            if work_item["status"] == "ready":
                runtime.transition_work_item(
                    "task-book",
                    work_item_id=work_item_id,
                    status="running",
                    idempotency_key=f"{work_item_id}-running-for-completion",
                )
            runtime.transition_work_item(
                "task-book",
                work_item_id=work_item_id,
                status="accepted",
                idempotency_key=f"{work_item_id}-accepted-for-completion",
            )
    runtime.transition_task(
        "task-book", status="ready", idempotency_key="task-ready"
    )
    runtime.transition_task(
        "task-book", status="running", idempotency_key="task-running"
    )
    completed = runtime.transition_task(
        "task-book", status="completed", idempotency_key="task-completed"
    )
    assert completed["task"]["status"] == "completed"

    rejected = runtime.change_artifact_disposition(
        "task-book",
        version_id="chapter-001-v1",
        disposition="rejected_pre_v3",
        reason_code="longform_governance_v3_reaudit",
        feedback_digest="d" * 64,
        idempotency_key="reject-v1",
    )
    assert rejected["selected_artifact_version"] is None
    assert rejected["task"]["status"] == "ready"
    assert rejected["artifacts"]["chapter-001-v1"]["disposition"] == "rejected_pre_v3"
    assert rejected["artifacts"]["chapter-001-v1"]["selection_eligible"] is False

    repeated = runtime.change_artifact_disposition(
        "task-book",
        version_id="chapter-001-v1",
        disposition="rejected_pre_v3",
        reason_code="longform_governance_v3_reaudit",
        feedback_digest="d" * 64,
        idempotency_key="reject-v1",
    )
    assert repeated == rejected

    with pytest.raises(InvalidTransition, match="not selection eligible"):
        runtime.select_artifact_version(
            "task-book",
            version_id="chapter-001-v1",
            idempotency_key="reselect-rejected-v1",
        )

    assert runtime.rebuild_task("task-book") == rejected


def test_work_item_dependencies_activate_without_creating_child_tasks(
    tmp_path: Path,
) -> None:
    runtime = TaskRuntime(tmp_path, project="Demo")
    runtime.create_task(
        task_id="task-book",
        title="Produce one book",
        user_goal="Run drafting and review in dependency order.",
        idempotency_key="request-book",
    )
    runtime.create_work_item(
        "task-book",
        job_id="job-main",
        work_item_id="chapter-001",
        kind="chapter",
        title="Draft chapter 1",
        idempotency_key="work-chapter-001",
    )
    pending = runtime.create_work_item(
        "task-book",
        job_id="job-main",
        work_item_id="review-001",
        kind="review",
        title="Review chapter 1",
        depends_on=["chapter-001"],
        idempotency_key="work-review-001",
    )
    assert pending["work_items"]["review-001"]["status"] == "pending"

    running = runtime.transition_work_item(
        "task-book",
        work_item_id="chapter-001",
        status="running",
        idempotency_key="chapter-running",
    )
    accepted = runtime.transition_work_item(
        "task-book",
        work_item_id="chapter-001",
        status="accepted",
        idempotency_key="chapter-accepted",
    )

    assert running["work_items"]["review-001"]["status"] == "pending"
    assert accepted["work_items"]["review-001"]["status"] == "ready"


def test_work_item_created_after_dependencies_are_accepted_is_ready(
    tmp_path: Path,
) -> None:
    runtime = TaskRuntime(tmp_path, project="Demo")
    runtime.create_task(
        task_id="task-late-dependent",
        title="Create the reviewer after planning",
        user_goal="Allow dynamic work-item expansion after a gate passes.",
        idempotency_key="request-late-dependent",
    )
    runtime.create_work_item(
        "task-late-dependent",
        job_id="job-main",
        work_item_id="brain-plan",
        kind="planning",
        title="Accept the Brain plan",
        idempotency_key="work-brain-plan",
    )
    runtime.transition_work_item(
        "task-late-dependent",
        work_item_id="brain-plan",
        status="running",
        idempotency_key="brain-plan-running",
    )
    runtime.transition_work_item(
        "task-late-dependent",
        work_item_id="brain-plan",
        status="accepted",
        idempotency_key="brain-plan-accepted",
    )

    created = runtime.create_work_item(
        "task-late-dependent",
        job_id="job-main",
        work_item_id="writer",
        kind="prose",
        title="Write the accepted scope",
        depends_on=["brain-plan"],
        idempotency_key="work-writer",
    )

    assert created["work_items"]["writer"]["status"] == "ready"


def test_project_rebuild_and_doctor_trust_ledgers_not_cached_indexes(
    tmp_path: Path,
) -> None:
    runtime = TaskRuntime(tmp_path, project="Demo")
    runtime.create_task(
        task_id="task-one",
        title="First goal",
        user_goal="Rebuild every cached view.",
        idempotency_key="request-one",
    )
    task_dir = tmp_path / "projects" / "Demo" / "runtime" / "tasks" / "task-one"
    (task_dir / "projections" / "task.yml").write_text("corrupt: true\n", encoding="utf-8")
    index_path = tmp_path / "projects" / "Demo" / "runtime" / "task_index.yml"
    index_path.write_text("fake: index\n", encoding="utf-8")

    rebuilt = runtime.rebuild_project()

    assert rebuilt["task_count"] == 1
    assert rebuilt["tasks"][0]["task_id"] == "task-one"
    assert yaml.safe_load(index_path.read_text(encoding="utf-8")) == rebuilt
    assert runtime.doctor_project()["ok"] is True
    for name in (
        "task.yml",
        "jobs.yml",
        "work_items.yml",
        "attempts.yml",
        "artifact_index.yml",
        "evidence.yml",
        "progress.yml",
        "handoff.yml",
    ):
        assert (task_dir / "projections" / name).is_file()
    collected_paths = {
        record.source.path
        for record in SourceCollector(tmp_path).collect_project(
            "Demo", domain="code_engineering"
        )
    }
    assert "projects/Demo/runtime/knowledge/selected_artifacts.yml" in collected_paths
    assert "projects/Demo/runtime/tasks/task-one/events.jsonl" not in collected_paths

    ledger_path = task_dir / "events.jsonl"
    event = json.loads(ledger_path.read_text(encoding="utf-8"))
    event["payload"]["title"] = "tampered"
    ledger_path.write_text(json.dumps(event) + "\n", encoding="utf-8")

    diagnosis = runtime.doctor_project()
    assert diagnosis["ok"] is False
    assert diagnosis["tasks"]["task-one"]["ok"] is False
    with pytest.raises(LedgerIntegrityError, match="ledger integrity failure"):
        runtime.rebuild_project()


def test_runtime_policy_declares_project_rag_and_hermes_ark_primary() -> None:
    root = Path(__file__).resolve().parents[1]
    policy = load_agentlab_configs(root, keys=["task_runtime_v2"])["task_runtime_v2"]

    assert policy["identity"]["rule"] == "one_business_goal_one_task"
    assert policy["knowledge"]["per_task_database"] is False
    assert policy["knowledge"]["indexed_runtime_surface"] == [
        "runtime/knowledge/selected_artifacts.yml"
    ]
    assert (
        policy["worker_routing"]["visual_generation"]["primary_contract"]
        == "hermes_ark_artifact_producer"
    )
    assert (
        policy["worker_routing"]["visual_generation"]["fallback_contract"]
        == "claude_seedance_artifact_fallback"
    )


def test_task_lifecycle_is_projected_from_validated_transition_events(
    tmp_path: Path,
) -> None:
    runtime = TaskRuntime(tmp_path, project="Demo")
    runtime.create_task(
        task_id="task-demo-001",
        title="One goal",
        user_goal="Run one governed task.",
        idempotency_key="request-001",
    )

    ready = runtime.transition_task(
        "task-demo-001",
        status="ready",
        idempotency_key="transition-ready",
    )
    running = runtime.transition_task(
        "task-demo-001",
        status="running",
        idempotency_key="transition-running",
    )

    assert ready["task"]["status"] == "ready"
    assert running["task"]["status"] == "running"
    assert running["last_event_sequence"] == 3

    with pytest.raises(InvalidTransition):
        runtime.transition_task(
            "task-demo-001",
            status="created",
            idempotency_key="transition-backwards",
        )

    with pytest.raises(EntityNotFound):
        runtime.transition_task(
            "task-missing",
            status="ready",
            idempotency_key="missing-ready",
        )
    assert not (
        tmp_path / "projects" / "Demo" / "runtime" / "tasks" / "task-missing"
    ).exists()
