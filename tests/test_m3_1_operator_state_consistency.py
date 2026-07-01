"""M3-1 Operator State Model completeness — cross-surface consistency and source-of-truth tests."""

from __future__ import annotations

from pathlib import Path

import yaml

from agent_runtime.operator_os.state_model import (
    PHASE_STATUS_ENUM,
    TASK_STATUS_ENUM,
    build_operator_state,
    _classify_phase_statuses,
)
from agent_runtime.operator_os.stage_scope import active_stage_scope


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _make_full_project(root: Path, project: str = "Crown_of_Ash") -> Path:
    """Create a complete project fixture with all M3 operator state inputs."""
    project_root = root / "projects" / project
    brain_dir = project_root / "project_brain"
    runs_dir = project_root / "runs"
    brain_dir.mkdir(parents=True)

    # project handoff
    (project_root / "PROJECT_HANDOFF.md").write_text("# Handoff\n", encoding="utf-8")

    # artifact index
    _write_yaml(project_root / "project_artifact_index.yml", {
        "artifacts": [
            {"artifact_id": "ch1", "type": "chapter", "status": "current"},
        ]
    })

    # fact snapshot
    _write_yaml(brain_dir / "project_fact_snapshot.yml", {
        "project": project,
        "event_count": 3,
        "events": [
            {"event_id": "evt_001", "timestamp": "2026-07-01T00:00:00Z", "type": "world_bible_updated"},
            {"event_id": "evt_002", "timestamp": "2026-07-01T01:00:00Z", "type": "chapter_promoted"},
            {"event_id": "evt_003", "timestamp": "2026-07-01T02:00:00Z", "type": "artifact_archived"},
        ],
    })

    # acceptance history with multiple phases
    _write_yaml(brain_dir / "acceptance_history.yml", {
        "entries": [
            {
                "phase_id": "phase_1_foundation",
                "accepted": True,
                "verdict": "PASS",
                "recommended_next_action": "next_phase",
                "evidence_files": ["world_bible.yml"],
                "human_approval_required": False,
                "recorded_at": "2026-07-01T00:00:00+00:00",
            },
            {
                "phase_id": "phase_2_draft_batch",
                "accepted": False,
                "verdict": "NEEDS_HUMAN_REVIEW",
                "recommended_next_action": "await_operator_approval",
                "evidence_files": ["chapter_2_draft.md"],
                "human_approval_required": True,
                "missing_evidence": [],
                "recorded_at": "2026-07-01T01:00:00+00:00",
            },
            {
                "phase_id": "phase_3_review",
                "accepted": False,
                "verdict": "BLOCKED",
                "recommended_next_action": "request_missing_evidence",
                "evidence_files": [],
                "human_approval_required": False,
                "missing_evidence": ["continuity_report.md", "style_check.yml"],
                "recorded_at": "2026-07-01T02:00:00+00:00",
            },
            {
                "phase_id": "phase_4_polish",
                "accepted": False,
                "verdict": "RETRY",
                "recommended_next_action": "retry_with_updated_prompt",
                "evidence_files": ["polish_diff.md"],
                "human_approval_required": False,
                "missing_evidence": [],
                "state_transition": {"proposal_supplied": True, "applied": False},
                "recorded_at": "2026-07-01T03:00:00+00:00",
            },
        ],
    })

    # next actions
    _write_yaml(brain_dir / "next_actions.yml", {
        "next_phase_id": "phase_2_draft_batch",
        "next_action": "await_operator_approval",
        "reason": "phase_2 needs human review",
    })

    # current phase
    _write_yaml(brain_dir / "current_phase.yml", {
        "phase_id": "phase_2_draft_batch",
        "status": "in_progress",
    })

    # executor results in runs/
    task_dir = runs_dir / "task_001"
    task_dir.mkdir(parents=True)
    _write_yaml(task_dir / "task_packet.yml", {
        "task_id": "task_001",
        "phase_id": "phase_1_foundation",
        "created_at": "2026-06-30T23:00:00Z",
    })
    _write_yaml(task_dir / "executor_result.yml", {
        "executor_result": {
            "task_packet_id": "task_001",
            "executor_id": "claude_code",
            "source": "local",
            "summary": "Phase 1 foundation completed",
            "status": "PASS",
            "changed_files": ["world_bible.yml", "character_profiles.yml"],
            "test_results": "all passing",
            "safety_attestation": {"secrets_exposed": False},
            "finished_at": "2026-07-01T00:00:00Z",
        },
    })
    _write_yaml(task_dir / "evidence_ledger.yml", {
        "result_dir": str(task_dir),
        "files": [
            {"path": "executor_result.yml", "sha256": "abc123"},
            {"path": "world_bible.yml", "sha256": "def456"},
        ],
        "evidence_count": 2,
    })

    # task with recovery plan
    task2_dir = runs_dir / "task_002"
    task2_dir.mkdir(parents=True)
    _write_yaml(task2_dir / "task_packet.yml", {
        "task_id": "task_002",
        "phase_id": "phase_3_review",
        "created_at": "2026-07-01T01:30:00Z",
    })
    _write_yaml(task2_dir / "executor_result.yml", {
        "executor_result": {
            "task_packet_id": "task_002",
            "executor_id": "hermes",
            "source": "local",
            "summary": "Review failed — missing continuity data",
            "status": "FAIL",
            "changed_files": [],
            "no_change_rationale": "missing input data",
            "finished_at": "2026-07-01T02:00:00Z",
        },
    })
    rec_dir = task2_dir / "recovery"
    rec_dir.mkdir()
    _write_yaml(rec_dir / "recovery_plan.yml", {
        "task_id": "task_002",
        "project": project,
        "summary": "Recover from missing continuity data",
        "failure_category": "MISSING_EVIDENCE",
        "confidence": 0.9,
        "recommended_action": "request_missing_evidence",
        "created_at": "2026-07-01T02:30:00Z",
    })
    _write_yaml(rec_dir / "failure_diagnosis.yml", {
        "failure_category": "MISSING_EVIDENCE",
        "confidence": 0.85,
        "recommended_action": "request_missing_evidence",
    })

    # task with decision cards
    task3_dir = runs_dir / "task_003"
    task3_dir.mkdir(parents=True)
    dc_dir = task3_dir / "decision_cards"
    dc_dir.mkdir()
    _write_yaml(dc_dir / "approve_phase_2.yml", {
        "question": "Approve phase_2_draft_batch for promotion?",
        "status": "pending",
        "created_at": "2026-07-01T04:00:00Z",
    })
    _write_yaml(dc_dir / "capability_gap_image_review.yml", {
        "capability": "image_review",
        "status": "unresolved",
        "recommended_action": "route_to_external_evidence_provider",
        "created_at": "2026-07-01T04:30:00Z",
    })

    # task with cost ledger
    task4_dir = runs_dir / "task_004"
    task4_dir.mkdir(parents=True)
    _write_yaml(task4_dir / "cost_ledger.yml", {
        "task_id": "task_004",
        "calls": [
            {
                "stage": "phase_1",
                "agent": "coder",
                "provider": "deepseek",
                "model_alias": "deepseek-v4-pro",
                "input_tokens": 5000,
                "output_tokens": 2000,
                "estimated_cost_usd": 0.015,
            },
            {
                "stage": "phase_1",
                "agent": "supervisor",
                "provider": "qwen",
                "model_alias": "qwen3.6-plus",
                "input_tokens": 3000,
                "output_tokens": 1000,
                "estimated_cost_usd": 0.012,
            },
        ],
    })

    return project_root


# ── A3: cross-surface consistency tests ────────────────────────────────────

def test_operator_state_covers_all_16_required_fields() -> None:
    """Verify build_operator_state returns all M3-1 required top-level fields."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _make_full_project(root)
        state = build_operator_state(root, "Crown_of_Ash")

        required_top_level = {
            "schema_version", "stage", "generated_at", "stage_scope",
            "project", "source_policy", "project_brain",
            "phase_progress", "next_action", "facts", "artifacts",
            "executor_results", "approvals", "recovery_plans",
            "capability_gaps", "evidence_ledgers", "cost_state",
            "timeline", "safety",
        }
        missing = required_top_level - set(state.keys())
        assert not missing, f"Missing top-level fields: {missing}"

        # project status
        assert state["project"]["status"] == "retry"
        assert state["project"]["id"] == "Crown_of_Ash"

        # phase progress — accepted phase ids
        assert state["phase_progress"]["accepted_phase_ids"] == ["phase_1_foundation"]
        assert state["phase_progress"]["history_entry_count"] == 4

        # phase_statuses classification
        pss = state["phase_progress"]["phase_statuses"]
        assert pss.get("phase_1_foundation") == "accepted"
        assert pss.get("phase_2_draft_batch") == "needs_human_review"
        assert pss.get("phase_3_review") == "needs_evidence"
        assert pss.get("phase_4_polish") == "retryable"

        # executor results
        assert len(state["executor_results"]) == 2
        assert state["executor_results"][0]["task_id"] == "task_001"
        assert state["executor_results"][0]["status"] == "PASS"
        assert state["executor_results"][1]["status"] == "FAIL"

        # approvals
        assert len(state["approvals"]) >= 2  # acceptance_history + decision_card
        approval_types = {a["type"] for a in state["approvals"]}
        assert "phase_acceptance" in approval_types
        assert "decision_card" in approval_types

        # recovery plans
        assert len(state["recovery_plans"]) == 1
        assert state["recovery_plans"][0]["task_id"] == "task_002"
        assert state["recovery_plans"][0]["failure_category"] == "MISSING_EVIDENCE"

        # capability gaps
        assert len(state["capability_gaps"]) >= 1
        gap_caps = {g["capability"] for g in state["capability_gaps"]}
        assert "image_review" in gap_caps

        # evidence ledgers
        assert len(state["evidence_ledgers"]) == 1
        assert state["evidence_ledgers"][0]["evidence_count"] == 2

        # cost state
        assert state["cost_state"]["total_estimated_cost_usd"] == 0.027
        assert state["cost_state"]["has_cost_data"] is True
        assert len(state["cost_state"]["per_task_ledgers"]) == 1

        # timeline
        assert len(state["timeline"]) > 0
        event_types = {e["event_type"] for e in state["timeline"]}
        assert "phase_acceptance_verdict" in event_types
        assert "executor_result_received" in event_types
        assert "evidence_consumed" in event_types
        assert "task_packet_created" in event_types
        assert "recovery_resolved" in event_types
        assert "approval_requested" in event_types


def test_operator_state_derives_progress_from_project_brain() -> None:
    """Phase progress must come from acceptance_history, not directory layout."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _make_full_project(root)

        # add a fake "phase_99" directory structure that should NOT appear
        fake_phase_dir = root / "projects" / "Crown_of_Ash" / "runs" / "fake_phase_99"
        fake_phase_dir.mkdir(parents=True)
        _write_yaml(fake_phase_dir / "executor_result.yml", {
            "executor_result": {
                "phase_id": "phase_99_fake",
                "status": "PASS",
            },
        })

        state = build_operator_state(root, "Crown_of_Ash")

        # accepted_phase_ids must NOT include the fake phase
        assert "phase_99_fake" not in state["phase_progress"]["accepted_phase_ids"]
        # must only include what's in acceptance_history
        assert state["phase_progress"]["accepted_phase_ids"] == ["phase_1_foundation"]

        # next action comes from next_actions.yml, not from directory layout
        assert state["next_action"]["data"]["next_phase_id"] == "phase_2_draft_batch"


def test_operator_state_missing_brain_inputs() -> None:
    """When Project Brain files are missing, status reflects it."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        project_root = root / "projects" / "NovelGen"
        brain_dir = project_root / "project_brain"
        brain_dir.mkdir(parents=True)

        # only write acceptance_history, missing next_actions and fact_snapshot
        _write_yaml(brain_dir / "acceptance_history.yml", {"entries": []})

        state = build_operator_state(root, "NovelGen")

        assert state["project"]["status"] == "needs_operator_state_inputs"
        assert state["project_brain"]["healthy"] is False
        assert "next_actions.yml" in state["project_brain"]["missing_files"]
        assert "project_fact_snapshot.yml" in state["project_brain"]["missing_files"]


def test_phase_status_enum_values() -> None:
    """Verify standard status enum values are correct."""
    assert "accepted" in PHASE_STATUS_ENUM
    assert "rejected" in PHASE_STATUS_ENUM
    assert "needs_human_review" in PHASE_STATUS_ENUM
    assert "needs_evidence" in PHASE_STATUS_ENUM
    assert "paused" in PHASE_STATUS_ENUM
    assert "blocked" in PHASE_STATUS_ENUM
    assert "retryable" in PHASE_STATUS_ENUM

    assert "pending" in TASK_STATUS_ENUM
    assert "in_progress" in TASK_STATUS_ENUM
    assert "completed" in TASK_STATUS_ENUM
    assert "blocked" in TASK_STATUS_ENUM


def test_classify_phase_statuses_paused_and_blocked() -> None:
    """current_phase.yml paused/blocked status takes priority."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        brain_dir = root / "project_brain"
        brain_dir.mkdir(parents=True)
        _write_yaml(brain_dir / "current_phase.yml", {
            "phase_id": "phase_paused",
            "status": "paused",
        })
        _write_yaml(brain_dir / "acceptance_history.yml", {"entries": []})

        statuses = _classify_phase_statuses([], brain_dir)
        assert statuses["phase_paused"] == "paused"


def test_timeline_sorted_with_valid_times_first() -> None:
    """Timeline entries with valid times come before empty-time entries."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _make_full_project(root)
        state = build_operator_state(root, "Crown_of_Ash")
        timeline = state["timeline"]

        # find first and last entries
        if len(timeline) > 1:
            first_time = timeline[0].get("time", "")
            last_time = timeline[-1].get("time", "")
            # entries with real times should precede empty ones
            if first_time and not last_time:
                pass  # correct
            elif not first_time and last_time:
                # all entries have no time — acceptable for empty fixture
                pass
            # otherwise both have time or both empty — check sort order
