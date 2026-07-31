from __future__ import annotations

import json
import hashlib
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

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
from agent_runtime.narrative.auto_acceptance import (
    auto_accept_and_project_candidate,
    project_detached_candidate_state,
    record_detached_candidate_acceptance,
)
from agent_runtime.narrative.state_store import (
    NarrativeStateConflict,
    NarrativeStateStore,
    narrative_payload_sha256,
)
from agent_runtime.task_runtime_v2.narrative_projection_executor import (
    NarrativeProjectionAttemptExecutor,
)
from agent_runtime.project_truth import (
    ChangeSet,
    ProjectTruthStore,
    ResourceChange,
)
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


def test_user_acceptance_work_item_cannot_run_without_signed_gate(
    tmp_path: Path,
) -> None:
    runtime = TaskRuntime(tmp_path, project="Demo")
    runtime.create_task(
        task_id="task-user-gate",
        title="Project accepted prose",
        user_goal="Project only the exact user-accepted candidate.",
        idempotency_key="request-user-gate",
    )
    created = runtime.create_work_item(
        "task-user-gate",
        job_id="job-main",
        work_item_id="state-projector",
        kind="verification",
        title="Project accepted narrative state",
        requires_user_acceptance=True,
        idempotency_key="work-user-gate",
    )

    assert created["work_items"]["state-projector"][
        "requires_user_acceptance"
    ] is True
    with pytest.raises(InvalidTransition, match="signed narrative user"):
        runtime.transition_work_item(
            "task-user-gate",
            work_item_id="state-projector",
            status="running",
            idempotency_key="run-user-gate",
        )


def test_detached_dual_review_auto_acceptance_releases_state_projector(
    tmp_path: Path,
) -> None:
    config = tmp_path / "config"
    config.mkdir()
    (config / "task_input_tiers.yml").write_bytes(
        (Path(__file__).resolve().parents[1] / "config" / "task_input_tiers.yml")
        .read_bytes()
    )
    project = tmp_path / "projects" / "Demo"
    production = project / "production"
    outputs = project / "runs" / "task-detached" / "outputs"
    production.mkdir(parents=True)
    outputs.mkdir(parents=True)
    chapter_cards = production / "chapter_cards" / "index.yml"
    chapter_cards.parent.mkdir()
    chapter_cards.write_text(
        yaml.safe_dump(
            {
                "schema_version": 3,
                "contract_version": "chapter-contract/v3",
                "project": "Demo",
                "chapter_state_plan": [
                    {
                        "chapter": 1,
                        "opening_state": "ordinary",
                        "closing_state": "mark_awake",
                        "turn": "ash_mark_awakens",
                        "protagonist_drive": {
                            "desire_delta": "hide_the_awakened_mark"
                        },
                        "world_state_delta": {
                            "axis": "chapter_001_story_state",
                            "before": "ordinary",
                            "after": "mark_awake",
                            "cause": "ash_mark_awakens",
                            "evidence_target": "first_resonance",
                        },
                        "foreshadow_actions": [
                            {
                                "foreshadow_id": "fs_ch001",
                                "action": "seed",
                                "evidence_target": "uncommanded_pulse",
                            }
                        ],
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    candidate = outputs / "chapter_001.md"
    candidate.write_text("第一章\n灰烬逆流。\n", encoding="utf-8")
    candidate_sha256 = hashlib.sha256(candidate.read_bytes()).hexdigest()
    runtime = TaskRuntime(tmp_path, project="Demo")
    runtime.create_task(
        task_id="task-detached",
        title="Project accepted prose",
        user_goal="Auto-project only a dual-reviewed exact candidate.",
        idempotency_key="request-detached",
        input_profile=_GOVERNED_PROFILE,
    )
    _record_brain_plan_gates(runtime, tmp_path, "task-detached")
    senior_attempt_id = "senior-editor-final-attempt-001"
    reader_attempt_id = "reader-panel-final-attempt-001"
    for work_item_id in ("senior-editor-final", "reader-panel-final"):
        runtime.create_work_item(
            "task-detached",
            job_id="job-main",
            work_item_id=work_item_id,
            kind="quality-review",
            title=f"Review {work_item_id}",
            idempotency_key=f"work-{work_item_id}",
        )
    senior_outcome = execute_role_with_output(
        runtime,
        tmp_path,
        task_id="task-detached",
        work_item_id="senior-editor-final",
        attempt_id=senior_attempt_id,
        role="Reviewer",
        output={
            "candidate_sha256": candidate_sha256,
            "length_gate": "PASS",
            "continuity_gate": "PASS",
            "scene_order_gate": "PASS",
            "single_anomaly_gate": "PASS",
            "mark_no_glow_gate": "PASS",
            "knowledge_boundary_gate": "PASS",
            "institutional_detail_gate": "PASS",
            "character_policy_gate": "PASS",
            "remaining_blockers": [],
            "verdict": "PASS",
        },
    )
    reader_outcome = execute_role_with_output(
        runtime,
        tmp_path,
        task_id="task-detached",
        work_item_id="reader-panel-final",
        attempt_id=reader_attempt_id,
        role="Reviewer",
        output={
            "candidate_sha256": candidate_sha256,
            "verdict": "PASS",
            "clarity": {"score": "9.5/10"},
            "hook": {"score": "9.0/10"},
            "pacing": {"score": "8.5/10"},
            "emotional_credibility": {"score": "9.0/10"},
            "agency_read": {"score": "9.5/10"},
            "policy_risks": [],
            "remaining_blockers": [],
        },
    )
    for work_item_id in ("senior-editor-final", "reader-panel-final"):
        runtime.transition_work_item(
            "task-detached",
            work_item_id=work_item_id,
            status="running",
            idempotency_key=f"run-{work_item_id}",
        )
        runtime.transition_work_item(
            "task-detached",
            work_item_id=work_item_id,
            status="accepted",
            idempotency_key=f"accept-{work_item_id}",
        )
    runtime.create_work_item(
        "task-detached",
        job_id="job-main",
        work_item_id="state-projector",
        kind="verification",
        title="Project accepted narrative state",
        depends_on=["senior-editor-final", "reader-panel-final"],
        requires_user_acceptance=True,
        idempotency_key="work-detached",
    )
    runtime.create_work_item(
        "task-detached",
        job_id="job-main",
        work_item_id="chapter-002-authorial-director",
        kind="planning",
        title="Begin the next chapter",
        depends_on=["state-projector"],
        idempotency_key="work-next-chapter",
    )
    senior_output_sha256 = senior_outcome["output_sha256"]
    reader_output_sha256 = reader_outcome["output_sha256"]
    attempts = runtime.load_task("task-detached")["attempts"]

    def execution(attempt_id: str) -> dict[str, Any]:
        attempt = attempts[attempt_id]
        contract = attempt["execution_contract"]
        return {
            "cli_agent": attempt["worker"],
            "runtime_provider": contract["runtime_provider"],
            "model_id": contract["model_id"],
            "model_tier": contract["model_tier"],
            "fallback_used": False,
        }
    senior_review = outputs / "senior_editor_final_review.yml"
    senior_review.write_text(
        yaml.safe_dump(
            {
                "schema_version": "senior-editor-final-review/v1",
                "status": "pass",
                "disposition": "candidate_only",
                "project": "Demo",
                "task_id": "task-detached",
                "work_item_id": "senior-editor-final",
                "chapter_id": 1,
                "source_attempt_id": senior_attempt_id,
                "source_output_sha256": senior_output_sha256,
                "execution": execution(senior_attempt_id),
                "candidate_sha256": candidate_sha256,
                "gates": {
                    "length": "pass",
                    "continuity": "pass",
                    "scene_order": "pass",
                    "single_anomaly": "pass",
                    "mark_no_glow": "pass",
                    "knowledge_boundary": "pass",
                    "institutional_detail": "pass",
                    "character_policy": "pass",
                },
                "remaining_blockers": [],
                "verdict": "PASS",
                "authority": {
                    "may_accept_candidate": False,
                    "may_modify_canonical": False,
                    "may_project_state": False,
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    reader_review = outputs / "reader_panel_final_review.yml"
    reader_review.write_text(
        yaml.safe_dump(
            {
                "schema_version": "reader-panel-final-review/v1",
                "status": "pass",
                "disposition": "candidate_only",
                "project": "Demo",
                "task_id": "task-detached",
                "work_item_id": "reader-panel-final",
                "chapter_id": 1,
                "source_attempt_id": reader_attempt_id,
                "source_output_sha256": reader_output_sha256,
                "execution": execution(reader_attempt_id),
                "candidate_sha256": candidate_sha256,
                "scores": {
                    "clarity": 9.5,
                    "hook": 9.0,
                    "pacing": 8.5,
                    "emotional_credibility": 9.0,
                    "agency": 9.5,
                },
                "policy_risks": [],
                "remaining_blockers": [],
                "verdict": "PASS",
                "authority": {
                    "may_accept_candidate": False,
                    "may_modify_canonical": False,
                    "may_project_state": False,
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    policy_path = production / "outbound_context_policy.yml"
    policy_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "narrative-outbound-auto-approval/v1",
                "status": "active",
                "project": "Demo",
                "authorization": {
                    "mode": "policy_auto_approve",
                    "user_authorized": True,
                    "user_responsibility": "final_part_acceptance_only",
                },
                "constraints": {
                    "candidate_only": True,
                    "state_projection_requires_user_acceptance": False,
                    "fallback_allowed": False,
                },
                "automatic_acceptance": {
                    "mode": "dual_review_hard_gate_auto_project",
                    "required_review_roles": [
                        "senior_editor",
                        "reader_simulation_panel",
                    ],
                    "require_all_hard_gates": True,
                    "exception_action": "pause",
                    "user_acceptance_scope": "final_part_only",
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    policy_sha256 = hashlib.sha256(policy_path.read_bytes()).hexdigest()
    truth = ProjectTruthStore(project)
    pointer = truth.initialize("Demo")
    truth.commit(
        ChangeSet(
            project_id="Demo",
            expected_snapshot_id=pointer.current_snapshot_id,
            actor_id="user",
            idempotency_key="authorize-detached-mode",
            reason="Authorize detached automatic candidate acceptance.",
            resources=(
                ResourceChange(
                    key="policies.outbound_context_auto_approval",
                    content={
                        "schema_version": (
                            "narrative-outbound-auto-approval-authority/v1"
                        ),
                        "status": "active",
                        "project": "Demo",
                        "policy_path": "production/outbound_context_policy.yml",
                        "policy_sha256": policy_sha256,
                        "authorized_by": "user",
                    },
                ),
            ),
        )
    )
    state_store = NarrativeStateStore(project / "project_brain", project="Demo")
    state_store.bootstrap(
        {
            "schema_version": "narrative-bootstrap/v1",
            "project": "Demo",
            "precedence": ["chapter_contract"],
            "sources": [
                {
                    "path": chapter_cards.relative_to(project).as_posix(),
                    "sha256": hashlib.sha256(
                        chapter_cards.read_bytes()
                    ).hexdigest(),
                }
            ],
            "base_state": {},
        }
    )
    passing_senior_review = senior_review.read_bytes()
    invalid_senior_review = yaml.safe_load(
        senior_review.read_text(encoding="utf-8")
    )
    invalid_senior_review["gates"].pop("length")
    senior_review.write_text(
        yaml.safe_dump(invalid_senior_review, sort_keys=False),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="hard gates"):
        auto_accept_and_project_candidate(
            tmp_path,
            project="Demo",
            task_id="task-detached",
            work_item_id="state-projector",
            chapter_id=1,
            candidate_path=candidate,
            senior_editor_review_path=senior_review,
            reader_panel_review_path=reader_review,
            idempotency_key="invalid-detached-acceptance",
        )
    assert runtime.load_task("task-detached")["task"]["status"] == "paused"
    runtime.transition_task(
        "task-detached",
        status="ready",
        idempotency_key="resume-after-invalid-detached-acceptance",
    )
    senior_review.write_bytes(passing_senior_review)

    recorded = record_detached_candidate_acceptance(
        tmp_path,
        project="Demo",
        task_id="task-detached",
        work_item_id="state-projector",
        chapter_id=1,
        candidate_path=candidate,
        senior_editor_review_path=senior_review,
        reader_panel_review_path=reader_review,
        idempotency_key="auto-accept-chapter-001",
    )
    passing_reader_review = reader_review.read_bytes()
    changed_reader_review = yaml.safe_load(
        reader_review.read_text(encoding="utf-8")
    )
    changed_reader_review["execution"]["fallback_used"] = True
    reader_review.write_text(
        yaml.safe_dump(changed_reader_review, sort_keys=False),
        encoding="utf-8",
    )
    with pytest.raises(
        InvalidTransition,
        match="automatic acceptance record is stale or invalid",
    ):
        runtime.transition_work_item(
            "task-detached",
            work_item_id="state-projector",
            status="running",
            idempotency_key="run-detached-projector",
        )
    reader_review.write_bytes(passing_reader_review)
    changed_reader_review = yaml.safe_load(
        reader_review.read_text(encoding="utf-8")
    )
    changed_reader_review["reader_note"] = ["still passing but replaced"]
    reader_review.write_text(
        yaml.safe_dump(changed_reader_review, sort_keys=False),
        encoding="utf-8",
    )
    with pytest.raises(
        InvalidTransition,
        match="automatic acceptance record is stale or invalid",
    ):
        runtime.transition_work_item(
            "task-detached",
            work_item_id="state-projector",
            status="running",
            idempotency_key="run-detached-projector",
        )
    reader_review.write_bytes(passing_reader_review)
    failed_projection_attempt_id = "state-projector-detached-chapter-001-attempt-001"
    failed_attempt_key = (
        "project-detached-chapter-001.attempt."
        f"{failed_projection_attempt_id}"
    )
    NarrativeProjectionAttemptExecutor(tmp_path, project="Demo").start(
        task_id="task-detached",
        work_item_id="state-projector",
        attempt_id=failed_projection_attempt_id,
        candidate_sha256=candidate_sha256,
        acceptance_record_id=recorded["record_id"],
        idempotency_key=failed_attempt_key,
    )
    runtime.transition_attempt(
        "task-detached",
        attempt_id=failed_projection_attempt_id,
        status="failed",
        outcome={"reason": "synthetic_post_start_failure"},
        idempotency_key=f"{failed_attempt_key}.failed",
    )
    running = runtime.transition_work_item(
        "task-detached",
        work_item_id="state-projector",
        status="running",
        idempotency_key="run-detached-projector",
    )
    projected = project_detached_candidate_state(
        tmp_path,
        project="Demo",
        task_id="task-detached",
        work_item_id="state-projector",
        idempotency_key="project-detached-chapter-001",
    )
    replayed = project_detached_candidate_state(
        tmp_path,
        project="Demo",
        task_id="task-detached",
        work_item_id="state-projector",
        idempotency_key="project-detached-chapter-001",
    )

    assert recorded["status"] == "accepted"
    assert recorded["candidate_sha256"] == candidate_sha256
    assert running["work_items"]["state-projector"]["status"] == "running"
    assert projected["status"] == "pass"
    assert projected["verification"]["status"] == "pass"
    assert projected["verification"]["hard_fact_count"] == 4
    assert projected["authority_commit"]["status"] == "committed"
    assert replayed["authority_commit"]["status"] == "already_committed"
    verified_commit_path = tmp_path / projected["authority_commit"][
        "verified_commit_path"
    ]
    forged_commit = deepcopy(
        yaml.safe_load(verified_commit_path.read_text(encoding="utf-8"))
    )
    forged_commit["state_delta"]["forged_state"] = True
    forged_delta_sha256 = narrative_payload_sha256(forged_commit["state_delta"])
    forged_commit["source_projection_sha256"] = forged_delta_sha256
    forged_commit["state_delta_sha256"] = forged_delta_sha256
    project_root = tmp_path / "projects" / "Demo"
    for section_name in ("seal", "delta_verification"):
        section = forged_commit[section_name]
        original_receipt = project_root / section["receipt_path"]
        forged_receipt = original_receipt.with_name(
            f"forged_{original_receipt.name}"
        )
        receipt_data = yaml.safe_load(original_receipt.read_text(encoding="utf-8"))
        receipt_data["source_projection_sha256"] = forged_delta_sha256
        if section_name == "seal":
            receipt_data["state_delta_sha256"] = forged_delta_sha256
            section["state_delta_sha256"] = forged_delta_sha256
        forged_receipt.write_text(
            yaml.safe_dump(receipt_data, sort_keys=False),
            encoding="utf-8",
        )
        section["source_projection_sha256"] = forged_delta_sha256
        section["receipt_path"] = forged_receipt.relative_to(project_root).as_posix()
        section["receipt_sha256"] = hashlib.sha256(
            forged_receipt.read_bytes()
        ).hexdigest()
    with pytest.raises(NarrativeStateConflict, match="Scribe Attempt output"):
        state_store.commit(forged_commit)
    authoritative = state_store.read()
    assert authoritative["chapters"]["1"]["artifact_sha256"] == candidate_sha256
    assert authoritative["world_axes"]["chapter_001_story_state"][
        "after"
    ] == "mark_awake"
    final_projection = runtime.load_task("task-detached")
    assert final_projection["work_items"]["state-projector"]["status"] == "accepted"
    assert final_projection["attempts"][senior_attempt_id]["status"] == "succeeded"
    assert final_projection["attempts"][reader_attempt_id]["status"] == "succeeded"
    projection_attempt_id = "state-projector-detached-chapter-001-attempt-002"
    assert final_projection["attempts"][failed_projection_attempt_id]["status"] == "failed"
    assert final_projection["attempts"][projection_attempt_id]["status"] == "succeeded"


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


def test_attempt_output_parser_recovers_final_fenced_yaml_after_reasoning() -> None:
    content = """# Supervisor Report

## Output

Reasoning before the structured result.
```yaml
brain_scope_decision:
  approved: true
```yaml
brain_scope_decision:
  approved: true
execution_plan:
  status: approved
```

## stderr

none
"""

    assert TaskRuntime._parse_attempt_output_mapping(content) == {
        "brain_scope_decision": {"approved": True},
        "execution_plan": {"status": "approved"},
    }


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

    selected_manifest = (
        tmp_path
        / "projects"
        / "Demo"
        / "runtime"
        / "knowledge"
        / "selected_artifacts.yml"
    )
    selected_manifest.write_text(
        yaml.safe_dump(
            {
                "schema_version": "task-runtime-selected-artifacts/v2",
                "project": "Demo",
                "selected_artifacts": [
                    {
                        "task_id": "forged",
                        "artifact_id": "forged",
                        "text": "FORGED-RUNTIME-PROJECTION",
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    forged_paths = {
        record.source.path
        for record in SourceCollector(tmp_path).collect_project(
            "Demo", domain="code_engineering"
        )
    }
    assert "projects/Demo/runtime/knowledge/selected_artifacts.yml" not in forged_paths
    runtime.rebuild_project()

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
