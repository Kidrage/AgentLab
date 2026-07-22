from __future__ import annotations

import json
from pathlib import Path

from agent_runtime.task_runtime_v2 import TaskInputClassifier, TaskRuntime


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
