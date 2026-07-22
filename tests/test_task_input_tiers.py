from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from agent_runtime.task_runtime_v2 import (
    InvalidTransition,
    TaskInputClassifier,
    TaskRuntime,
)


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
    runtime.transition_attempt(
        "task-worker-limit",
        attempt_id="attempt-one",
        status="succeeded",
        outcome={"receipt": "receipt-one"},
        idempotency_key="attempt-one-succeeded",
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
    for record_type in ("change_receipt", "memory_update"):
        source = staging / f"{record_type}.yml"
        source.write_text(f"record_type: {record_type}\nstatus: pass\n", encoding="utf-8")
        runtime.record_trace(
            "task-direct",
            record_id=f"record-{record_type}",
            record_type=record_type,
            producer="brain",
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
