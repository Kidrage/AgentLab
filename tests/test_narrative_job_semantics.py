from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agent_runtime.background_job_controller import (
    consume_process_receipt,
    create_crown_delivery_job,
    load_job_state,
    schedule_next_attempt,
    write_process_receipt,
)
from agent_runtime.brain.mission_contract import build_mission_contract
from agent_runtime.narrative.jobs.crown_adapter import (
    create_crown_audit_job_from_contract,
    upgrade_crown_job_state,
)
from narrative_test_authority import install_narrative_test_authority


NOW = "2026-07-19T10:00:00+00:00"


def test_full_heavy_audit_request_compiles_to_durable_audit_only_identity() -> None:
    request = """
    对 Crown_of_Ash 第1章到第10章执行完整 heavy audit。
    必须输出 fiction_review.yml、continuity_failure_report.yml，若发现问题还要输出
    revision_or_rewrite_proposal.yml；findings 属于审计结论。
    """

    contract = build_mission_contract(
        request,
        project_id="Crown_of_Ash",
        task_id="task_crown_heavy_audit_ch001_ch010",
    )

    assert contract["narrative_job_identity"] == {
        "job_kind": "narrative_audit",
        "run_mode": "audit_only",
        "candidate_set_id": None,
        "source_job_id": None,
        "source_run_id": None,
        "triggered_by_audit_id": None,
        "attempt_id": None,
        "lease_token": None,
    }
    assert contract["route_decision"]["selected_route"] == "narrative_heavy_audit"


def test_background_attempt_copies_persisted_identity_without_reclassification(
    tmp_path: Path,
) -> None:
    (tmp_path / "projects" / "Crown_of_Ash").mkdir(parents=True)
    state = create_crown_delivery_job(
        tmp_path,
        project="Crown_of_Ash",
        job_id="crown-candidate-v1",
        eval_id="crown-candidate-v1",
        start_chapter=1,
        end_chapter=3,
        writer_worker="fake_writer",
        **install_narrative_test_authority(tmp_path, writer="fake_writer"),
        chapter_state_plan="runs/shared/chapter_state_plan.yml",
        candidate_set_id="candidate-set-001",
        now=NOW,
    )
    assert state["job_kind"] == "narrative_generation"
    assert state["run_mode"] == "generate_candidate"

    attempt = schedule_next_attempt(
        tmp_path,
        project="Crown_of_Ash",
        job_id="crown-candidate-v1",
        now=NOW,
    )
    request = yaml.safe_load(Path(attempt["action_request_path"]).read_text())

    assert request["job_kind"] == "narrative_generation"
    assert request["run_mode"] == "generate_candidate"
    assert request["candidate_set_id"] == "candidate-set-001"
    assert request["attempt_id"] == attempt["attempt_id"]
    assert request["lease_token"] == attempt["lease_token"]


def test_expired_attempt_lease_cannot_overwrite_authoritative_state(
    tmp_path: Path,
) -> None:
    (tmp_path / "projects" / "Crown_of_Ash").mkdir(parents=True)
    create_crown_delivery_job(
        tmp_path,
        project="Crown_of_Ash",
        job_id="crown-candidate-v1",
        eval_id="crown-candidate-v1",
        start_chapter=1,
        end_chapter=3,
        writer_worker="fake_writer",
        **install_narrative_test_authority(tmp_path, writer="fake_writer"),
        chapter_state_plan="runs/shared/chapter_state_plan.yml",
        now=NOW,
    )
    attempt = schedule_next_attempt(
        tmp_path, project="Crown_of_Ash", job_id="crown-candidate-v1", now=NOW
    )
    write_process_receipt(
        tmp_path,
        project="Crown_of_Ash",
        job_id="crown-candidate-v1",
        attempt_id=attempt["attempt_id"],
        idempotency_key=attempt["idempotency_key"],
        lease_token="expired-lease",
        outcome="success",
        exit_code=0,
        result={"status": "pass"},
        now=NOW,
    )

    with pytest.raises(ValueError, match="lease token"):
        consume_process_receipt(
            tmp_path,
            project="Crown_of_Ash",
            job_id="crown-candidate-v1",
            now=NOW,
        )

    state = load_job_state(tmp_path, "Crown_of_Ash", "crown-candidate-v1")
    assert state["status"] == "preflight"
    assert state["active_attempt"]["lease_token"] == attempt["lease_token"]


def test_legacy_crown_job_migrates_from_structured_job_type_not_prose() -> None:
    state = upgrade_crown_job_state(
        {
            "schema_version": 1,
            "job_type": "crown_narrative_delivery",
            "user_request": "heavy audit rewrite proposal misleading prose",
            "updated_at": NOW,
            "config": {},
            "active_attempt": {
                "attempt_id": "attempt-0001-preflight",
                "idempotency_key": "job:attempt-0001-preflight",
                "scheduled_at": NOW,
            },
        }
    )

    assert state["job_kind"] == "narrative_generation"
    assert state["run_mode"] == "generate_candidate"
    assert state["schema_version"] == 2
    assert state["active_attempt"]["lease_token"].startswith("legacy:")


def test_compiled_audit_identity_drives_real_background_creation(tmp_path: Path) -> None:
    (tmp_path / "projects" / "Crown_of_Ash").mkdir(parents=True)
    contract = build_mission_contract(
        "审计 Crown_of_Ash 第1章到第10章，并输出 revision_or_rewrite_proposal.yml。",
        project_id="Crown_of_Ash",
        task_id="audit-intake-v1",
    )

    state = create_crown_audit_job_from_contract(
        tmp_path,
        mission_contract=contract,
        job_id="audit-v1",
        eval_id="audit-v1",
        start_chapter=1,
        end_chapter=10,
        now=NOW,
    )

    assert state["job_kind"] == "narrative_audit"
    assert state["run_mode"] == "audit_only"
    assert state["status"] == "awaiting_heavy_audit"
    assert state["config"]["narrative_adapter"] == "crown"
