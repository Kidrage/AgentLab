from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml

from agent_runtime.task_runtime_v2 import (
    InvalidTransition,
    TaskInputClassifier,
    TaskRuntime,
)
from task_runtime_v2_support import execute_role_with_output


def test_exact_single_detail_patch_routes_to_brain_direct_with_trace(tmp_path: Path) -> None:
    classifier = TaskInputClassifier(tmp_path)

    decision = classifier.classify(
        {
            "kind": "exact_patch",
            "scope": "single_detail",
            "target_count": 1,
            "canon_impact": "candidate",
            "risk_flags": [],
        }
    )

    assert decision["tier"] == "L0"
    assert decision["route"] == "brain_direct"
    assert decision["worker_limit"] == 0
    assert decision["full_audit_required"] is False
    assert {"input_classification", "change_receipt", "memory_update"}.issubset(
        decision["required_records"]
    )


def test_local_creative_patch_routes_to_one_worker_without_full_audit(
    tmp_path: Path,
) -> None:
    decision = TaskInputClassifier(tmp_path).classify(
        {
            "kind": "creative_patch",
            "scope": "localized",
            "target_count": 2,
            "canon_impact": "candidate",
            "risk_flags": [],
        }
    )

    assert decision["tier"] == "L1"
    assert decision["route"] == "single_worker"
    assert decision["worker_limit"] == 1
    assert decision["full_audit_required"] is False


def test_local_continuity_risk_escalates_to_checked_worker(tmp_path: Path) -> None:
    decision = TaskInputClassifier(tmp_path).classify(
        {
            "kind": "exact_patch",
            "scope": "single_detail",
            "target_count": 1,
            "canon_impact": "canonical",
            "risk_flags": ["age_continuity", "relationship_continuity"],
        }
    )

    assert decision["tier"] == "L2"
    assert decision["route"] == "single_worker_checked"
    assert decision["worker_limit"] == 1
    assert decision["full_audit_required"] is False
    assert "targeted_continuity_check" in decision["validation_gates"]


def test_prose_build_cannot_be_downgraded_below_governed_pipeline(
    tmp_path: Path,
) -> None:
    decision = TaskInputClassifier(tmp_path).classify(
        {
            "kind": "prose_build",
            "scope": "multi_chapter",
            "target_count": 0,
            "canon_impact": "canonical",
            "risk_flags": ["longform_continuity"],
            "requested_tier": "L0",
        }
    )

    assert decision["tier"] == "L3"
    assert decision["route"] == "governed_pipeline"
    assert decision["brain_decision_required"] is True
    assert decision["full_audit_required"] is True
    assert "brain_scope_decision" in decision["required_records"]
    assert "requested_tier_below_required" in decision["escalation_reasons"]


def test_task_runtime_records_input_classification_in_authoritative_creation_event(
    tmp_path: Path,
) -> None:
    runtime = TaskRuntime(tmp_path, project="Demo")
    profile = {
        "kind": "creative_patch",
        "scope": "localized",
        "target_count": 1,
        "canon_impact": "candidate",
        "risk_flags": [],
    }

    created = runtime.create_task(
        task_id="task-local-patch",
        title="Refine one local detail",
        user_goal="Refine one named detail and retain traceable memory.",
        input_profile=profile,
        idempotency_key="request-local-patch",
    )

    assert created["task"]["input_classification"]["tier"] == "L1"
    ledger = (
        tmp_path
        / "projects"
        / "Demo"
        / "runtime"
        / "tasks"
        / "task-local-patch"
        / "events.jsonl"
    )
    event = json.loads(ledger.read_text(encoding="utf-8").splitlines()[0])
    assert event["payload"]["input_profile"] == profile
    assert event["payload"]["input_classification"]["route"] == "single_worker"


def test_missing_input_profile_fails_closed_to_governed_pipeline(tmp_path: Path) -> None:
    created = TaskRuntime(tmp_path, project="Demo").create_task(
        task_id="task-unclassified",
        title="Unclassified request",
        user_goal="Retain safe behavior for a legacy caller.",
        idempotency_key="request-unclassified",
    )

    decision = created["task"]["input_classification"]
    assert decision["tier"] == "L3"
    assert decision["route"] == "governed_pipeline"
    assert "missing_input_profile" in decision["escalation_reasons"]
    assert decision["admission_ready"] is False


def test_partial_profile_cannot_fail_open_to_direct_patch(tmp_path: Path) -> None:
    decision = TaskInputClassifier(tmp_path).classify(
        {
            "kind": "exact_patch",
            "scope": "single_detail",
            "canon_impact": "candidate",
        }
    )

    assert decision["tier"] == "L3"
    assert decision["admission_ready"] is False
    assert "missing_required_fact:target_count" in decision["escalation_reasons"]
    assert "missing_required_fact:risk_flags" in decision["escalation_reasons"]


def test_provisional_task_accepts_only_supervisor_intake_then_records_brain_profile(
    tmp_path: Path,
) -> None:
    runtime = TaskRuntime(tmp_path, project="Demo")
    runtime.create_task(
        task_id="task-brain-intake",
        title="Brain intake",
        user_goal="Decide whether this one local detail needs a Worker.",
        idempotency_key="create-brain-intake",
    )
    runtime.create_work_item(
        "task-brain-intake",
        job_id="job-main",
        work_item_id="brain-intake",
        kind="intake",
        title="Brain input classification",
        idempotency_key="work-brain-intake",
    )
    input_profile = {
        "kind": "creative_patch",
        "scope": "localized",
        "target_count": 1,
        "canon_impact": "candidate",
        "risk_flags": [],
    }
    execute_role_with_output(
        runtime,
        tmp_path,
        task_id="task-brain-intake",
        work_item_id="brain-intake",
        attempt_id="attempt-brain-intake",
        role="Supervisor",
        output={"input_profile": input_profile},
    )

    with pytest.raises(InvalidTransition, match="does not match"):
        runtime.classify_task_input(
            "task-brain-intake",
            input_profile={**input_profile, "target_count": 2},
            producer_attempt_id="attempt-brain-intake",
            idempotency_key="mismatched-brain-classification",
        )

    classified = runtime.classify_task_input(
        "task-brain-intake",
        input_profile=input_profile,
        producer_attempt_id="attempt-brain-intake",
        idempotency_key="brain-classification-recorded",
    )

    assert classified["task"]["input_classification"]["tier"] == "L1"
    assert classified["task"]["input_classification"]["admission_ready"] is True


def test_l1_runtime_enforces_one_worker_and_route_contract(tmp_path: Path) -> None:
    runtime = TaskRuntime(tmp_path, project="Demo")
    runtime.create_task(
        task_id="task-worker-limit",
        title="One worker only",
        user_goal="Apply two local details with one worker identity.",
        input_profile={
            "kind": "creative_patch",
            "scope": "localized",
            "target_count": 2,
            "canon_impact": "candidate",
            "risk_flags": [],
        },
        idempotency_key="create-worker-limit",
    )
    for suffix in ("one", "two"):
        runtime.create_work_item(
            "task-worker-limit",
            job_id="job-main",
            work_item_id=f"patch-{suffix}",
            kind="patch",
            title=f"Patch {suffix}",
            idempotency_key=f"work-{suffix}",
        )

    runtime.schedule_attempt(
        "task-worker-limit",
        work_item_id="patch-one",
        attempt_id="attempt-one",
        worker="claude_code",
        provider="deepseek",
        execution_contract={
            "role": "Writer",
            "input_tier": "L1",
            "route": "single_worker",
        },
        idempotency_key="attempt-one",
    )
    runtime.transition_attempt(
        "task-worker-limit",
        attempt_id="attempt-one",
        status="running",
        idempotency_key="attempt-one-running",
    )
    with pytest.raises(InvalidTransition, match="owned by RoleAttemptExecutor"):
        runtime.transition_attempt(
            "task-worker-limit",
            attempt_id="attempt-one",
            status="succeeded",
            outcome={},
            idempotency_key="attempt-one-unverified-success",
        )
    runtime.transition_attempt(
        "task-worker-limit",
        attempt_id="attempt-one",
        status="failed",
        outcome={"reason": "unverified test attempt"},
        idempotency_key="attempt-one-failed",
    )
    execute_role_with_output(
        runtime,
        tmp_path,
        task_id="task-worker-limit",
        work_item_id="patch-one",
        attempt_id="attempt-one-executed",
        role="Writer",
        output={"candidate": "one local patch"},
    )

    with pytest.raises(InvalidTransition, match="one delegated worker"):
        runtime.schedule_attempt(
            "task-worker-limit",
            work_item_id="patch-two",
            attempt_id="attempt-two",
            worker="qwen",
            provider="dashscope",
            execution_contract={
                "role": "Writer",
                "input_tier": "L1",
                "route": "single_worker",
            },
            idempotency_key="attempt-two",
        )


def test_l3_blocks_writer_until_brain_plan_records_exist(tmp_path: Path) -> None:
    runtime = TaskRuntime(tmp_path, project="Demo")
    runtime.create_task(
        task_id="task-governed",
        title="Governed prose",
        user_goal="Build prose only after Brain scope and quality planning.",
        input_profile={
            "kind": "prose_build",
            "scope": "multi_chapter",
            "target_count": 0,
            "canon_impact": "canonical",
            "risk_flags": ["longform_continuity"],
        },
        idempotency_key="create-governed",
    )
    runtime.create_work_item(
        "task-governed",
        job_id="job-main",
        work_item_id="writer",
        kind="prose",
        title="Writer prose build",
        idempotency_key="work-writer",
    )

    with pytest.raises(InvalidTransition, match="Brain scope and execution plan"):
        runtime.schedule_attempt(
            "task-governed",
            work_item_id="writer",
            attempt_id="writer-one",
            worker="claude_code",
            provider="deepseek",
            execution_contract={
                "role": "Writer",
                "input_tier": "L3",
                "route": "governed_pipeline",
            },
            idempotency_key="writer-one",
        )


def test_brain_scope_record_requires_supervisor_ownership_and_scope_fields(
    tmp_path: Path,
) -> None:
    runtime = TaskRuntime(tmp_path, project="Demo")
    runtime.create_task(
        task_id="task-brain-owned",
        title="Brain-owned scope",
        user_goal="Require a genuine Brain scope decision.",
        input_profile={
            "kind": "prose_build",
            "scope": "multi_chapter",
            "target_count": 0,
            "canon_impact": "canonical",
            "risk_flags": ["longform_continuity"],
        },
        idempotency_key="create-brain-owned",
    )
    source = (
        tmp_path
        / "projects"
        / "Demo"
        / "runtime"
        / "tasks"
        / "task-brain-owned"
        / "records"
        / "staging"
        / "scope.yml"
    )
    source.parent.mkdir(parents=True)
    source.write_text(
        yaml.safe_dump(
            {
                "schema_version": "brain-scope-decision/v1",
                "approved": True,
                "chapter_start": 1,
                "chapter_end": 1,
                "target_cjk_chars": 3000,
                "quality_thresholds": {"overall": 0.8},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(InvalidTransition, match="cannot be produced by role"):
        runtime.record_trace(
            "task-brain-owned",
            record_id="fake-writer-scope",
            record_type="brain_scope_decision",
            producer="claude_code",
            producer_role="Writer",
            path=source,
            idempotency_key="fake-writer-scope",
        )

    source.write_text(
        "schema_version: brain-scope-decision/v1\n"
        "producer_attempt_id: missing-attempt\n"
        f"source_output_sha256: {'a' * 64}\n"
        "approved: true\n",
        encoding="utf-8",
    )
    with pytest.raises(InvalidTransition, match="chapter_start"):
        runtime.record_trace(
            "task-brain-owned",
            record_id="incomplete-brain-scope",
            record_type="brain_scope_decision",
            producer="codex",
            producer_role="Supervisor",
            path=source,
            idempotency_key="incomplete-brain-scope",
        )


def test_brain_scope_record_must_match_supervisor_attempt_output(tmp_path: Path) -> None:
    runtime = TaskRuntime(tmp_path, project="Demo")
    runtime.create_task(
        task_id="task-brain-provenance",
        title="Brain scope provenance",
        user_goal="Bind scope decisions to the actual Brain output.",
        input_profile={
            "kind": "prose_build",
            "scope": "multi_chapter",
            "target_count": 0,
            "canon_impact": "canonical",
            "risk_flags": ["longform_continuity"],
        },
        idempotency_key="create-brain-provenance",
    )
    runtime.create_work_item(
        "task-brain-provenance",
        job_id="job-main",
        work_item_id="brain-plan",
        kind="planning",
        title="Brain plan",
        idempotency_key="work-brain-provenance",
    )
    output_scope = {
        "schema_version": "brain-scope-decision/v1",
        "approved": True,
        "chapter_start": 1,
        "chapter_end": 1,
        "target_cjk_chars": 3000,
        "quality_thresholds": {"overall": 0.8},
    }
    outcome = execute_role_with_output(
        runtime,
        tmp_path,
        task_id="task-brain-provenance",
        work_item_id="brain-plan",
        attempt_id="brain-provenance-attempt",
        role="Supervisor",
        output={"brain_scope_decision": output_scope},
    )
    source = (
        tmp_path
        / "projects"
        / "Demo"
        / "runtime"
        / "tasks"
        / "task-brain-provenance"
        / "records"
        / "staging"
        / "scope.yml"
    )
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(
        yaml.safe_dump(
            {
                **output_scope,
                "chapter_end": 2,
                "producer_attempt_id": "brain-provenance-attempt",
                "source_output_sha256": outcome["output_sha256"],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(InvalidTransition, match="does not match the producer"):
        runtime.record_trace(
            "task-brain-provenance",
            record_id="mismatched-brain-scope",
            record_type="brain_scope_decision",
            producer="codex",
            producer_role="Supervisor",
            path=source,
            idempotency_key="mismatched-brain-scope",
        )


def test_completion_requires_immutable_change_and_memory_records(tmp_path: Path) -> None:
    runtime = TaskRuntime(tmp_path, project="Demo")
    runtime.create_task(
        task_id="task-direct",
        title="Direct micro patch",
        user_goal="Apply one exact detail and retain memory.",
        input_profile={
            "kind": "exact_patch",
            "scope": "single_detail",
            "target_count": 1,
            "canon_impact": "candidate",
            "risk_flags": [],
        },
        idempotency_key="create-direct",
    )
    runtime.transition_task(
        "task-direct", status="ready", idempotency_key="direct-ready"
    )
    runtime.transition_task(
        "task-direct", status="running", idempotency_key="direct-running"
    )

    with pytest.raises(InvalidTransition, match="required trace records"):
        runtime.transition_task(
            "task-direct", status="completed", idempotency_key="direct-complete-early"
        )

    staging = (
        tmp_path
        / "projects"
        / "Demo"
        / "runtime"
        / "tasks"
        / "task-direct"
        / "records"
        / "staging"
    )
    staging.mkdir(parents=True)
    changed_file = tmp_path / "projects" / "Demo" / "candidate" / "detail.yml"
    changed_file.parent.mkdir(parents=True, exist_ok=True)
    changed_file.write_text("detail: retained\n", encoding="utf-8")
    changed_path = changed_file.relative_to(tmp_path).as_posix()
    changed_hash = hashlib.sha256(changed_file.read_bytes()).hexdigest()
    for record_type in ("change_receipt", "memory_update"):
        source = staging / f"{record_type}.yml"
        schema_version = (
            "change-receipt/v1"
            if record_type == "change_receipt"
            else "memory-update-receipt/v1"
        )
        list_field = (
            "changed_paths" if record_type == "change_receipt" else "updated_paths"
        )
        source.write_text(
            yaml.safe_dump(
                {
                    "schema_version": schema_version,
                    "status": "pass",
                    list_field: [changed_path],
                    "content_hashes": {changed_path: changed_hash},
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        runtime.record_trace(
            "task-direct",
            record_id=f"record-{record_type}",
            record_type=record_type,
            producer="brain",
            producer_role="Supervisor",
            path=source,
            idempotency_key=f"record-{record_type}",
        )

    completed = runtime.transition_task(
        "task-direct", status="completed", idempotency_key="direct-complete"
    )

    assert completed["task"]["status"] == "completed"
    assert {record["record_type"] for record in completed["trace_records"].values()} == {
        "change_receipt",
        "memory_update",
    }
    assert runtime.doctor_project()["ok"] is True


def test_legacy_event_without_classification_rebuilds_from_ledger_only(
    tmp_path: Path,
) -> None:
    runtime = TaskRuntime(tmp_path, project="Demo")
    ledger = (
        tmp_path
        / "projects"
        / "Demo"
        / "runtime"
        / "tasks"
        / "task-legacy-ledger"
        / "events.jsonl"
    )
    ledger.parent.mkdir(parents=True)
    event = {
        "schema_version": "task-runtime-event/v2",
        "event_id": "evt-legacy",
        "sequence": 1,
        "task_id": "task-legacy-ledger",
        "project": "Demo",
        "entity_type": "task",
        "entity_id": "task-legacy-ledger",
        "event_type": "TASK_CREATED",
        "recorded_at": "2026-07-22T00:00:00+00:00",
        "idempotency_key": "legacy-create",
        "previous_event_hash": None,
        "payload": {
            "title": "Legacy v2 task",
            "user_goal": "Rebuild exactly what the old ledger contains.",
            "default_job": {"job_id": "job-main", "kind": "inline"},
        },
    }
    canonical = json.dumps(
        event, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    event["event_hash"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    ledger.write_text(
        json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )

    projection = runtime.rebuild_task("task-legacy-ledger")

    assert "input_classification" not in projection["task"]
