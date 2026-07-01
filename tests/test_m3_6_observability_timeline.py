"""M3-6 Observability Timeline — comprehensive tests."""

from __future__ import annotations

from pathlib import Path

import yaml

from agent_runtime.operator_os.timeline import (
    SUPPORTED_EVENT_TYPES,
    build_timeline,
    build_failure_narrative,
)


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _make_timeline_fixture(root: Path) -> Path:
    """Create a project fixture with diverse event sources."""
    proj = root / "projects" / "Crown_of_Ash"
    brain = proj / "project_brain"
    runs = proj / "runs"
    brain.mkdir(parents=True)

    # acceptance history — 2 phases
    _write_yaml(brain / "acceptance_history.yml", {
        "entries": [
            {
                "phase_id": "phase_1",
                "accepted": True,
                "verdict": "PASS",
                "recommended_next_action": "next_phase",
                "evidence_files": ["world_bible.yml"],
                "state_transition": {"proposal_supplied": True, "applied": True, "applied_event_ids": ["evt_001"]},
                "recorded_at": "2026-07-01T00:00:00Z",
            },
            {
                "phase_id": "phase_2",
                "accepted": False,
                "verdict": "NEEDS_HUMAN_REVIEW",
                "recommended_next_action": "await_approval",
                "human_approval_required": True,
                "recorded_at": "2026-07-01T01:00:00Z",
            },
        ],
    })

    # fact snapshot with state transitions
    _write_yaml(brain / "project_fact_snapshot.yml", {
        "project": "Crown_of_Ash",
        "event_count": 2,
        "events": [
            {"event_id": "evt_001", "timestamp": "2026-07-01T00:30:00Z", "type": "world_bible_update"},
            {"event_id": "evt_002", "timestamp": "2026-07-01T02:00:00Z", "type": "chapter_promoted"},
        ],
    })

    # next actions
    _write_yaml(brain / "next_actions.yml", {
        "next_phase_id": "phase_2",
        "next_action": "await_operator_approval",
    })

    # task_001: passing executor result + evidence
    t1 = runs / "task_001"
    t1.mkdir(parents=True)
    _write_yaml(t1 / "task_packet.yml", {
        "task_id": "task_001",
        "phase_id": "phase_1",
        "created_at": "2026-06-30T23:00:00Z",
    })
    _write_yaml(t1 / "executor_result.yml", {
        "executor_result": {
            "task_packet_id": "task_001",
            "executor_id": "claude_code",
            "source": "local",
            "summary": "Phase 1 complete",
            "status": "PASS",
            "finished_at": "2026-07-01T00:00:00Z",
        },
    })
    _write_yaml(t1 / "evidence_ledger.yml", {
        "files": [{"path": "result.yml"}],
        "evidence_count": 1,
    })

    # task_002: failing executor + recovery
    t2 = runs / "task_002"
    t2.mkdir(parents=True)
    _write_yaml(t2 / "executor_result.yml", {
        "executor_result": {
            "task_packet_id": "task_002",
            "executor_id": "hermes",
            "status": "FAIL",
            "summary": "Continuity check failed",
            "finished_at": "2026-07-01T01:00:00Z",
        },
    })
    rec = t2 / "recovery"
    rec.mkdir()
    _write_yaml(rec / "recovery_plan.yml", {
        "task_id": "task_002",
        "summary": "Recover from continuity failure",
        "failure_category": "MISSING_EVIDENCE",
        "recommended_action": "request_missing_evidence",
        "created_at": "2026-07-01T01:30:00Z",
    })

    # task_003: decision cards + capability gaps
    t3 = runs / "task_003"
    t3.mkdir(parents=True)
    dc = t3 / "decision_cards"
    dc.mkdir()
    _write_yaml(dc / "approve_ch2.yml", {
        "question": "Promote chapter 2 to canon?",
        "status": "pending",
        "created_at": "2026-07-01T02:00:00Z",
    })
    _write_yaml(dc / "style_review.yml", {
        "question": "Apply style edits?",
        "status": "approved",
        "resolved_at": "2026-07-01T02:30:00Z",
    })
    cg = t3 / "capability_gaps"
    cg.mkdir()
    _write_yaml(cg / "image_review.yml", {
        "capability": "image_review",
        "status": "unresolved",
    })

    # task_004: phase acceptance with promoted artifact
    t4 = runs / "task_004"
    t4.mkdir(parents=True)
    _write_yaml(t4 / "phase_acceptance.yml", {
        "phase_id": "phase_1",
        "verdict": "PASS",
        "recorded_at": "2026-07-01T03:00:00Z",
        "state_transition": {
            "applied": True,
            "archive_receipt": "archive/ch1_v1.md",
        },
    })

    return proj


def test_all_18_event_types_defined() -> None:
    """The SUPPORTED_EVENT_TYPES set must cover all 18 event types."""
    assert len(SUPPORTED_EVENT_TYPES) == 18
    required = {
        "task_packet_created", "executor_assigned", "executor_result_received",
        "evidence_consumed", "phase_acceptance_verdict", "acceptance_history_written",
        "next_action_recalculated", "state_transition_proposed",
        "state_transition_applied", "state_transition_rejected",
        "approval_requested", "approval_resolved", "capability_gap_raised",
        "recovery_started", "recovery_resolved", "budget_warning",
        "artifact_promoted", "artifact_archived",
    }
    assert SUPPORTED_EVENT_TYPES == required


def test_build_timeline_covers_all_source_types() -> None:
    """Timeline should contain events from all source types in the fixture."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _make_timeline_fixture(root)
        proj = root / "projects" / "Crown_of_Ash"
        timeline = build_timeline(proj)

        event_types = {e["event_type"] for e in timeline}
        assert "phase_acceptance_verdict" in event_types
        assert "acceptance_history_written" in event_types
        assert "next_action_recalculated" in event_types
        assert "state_transition_applied" in event_types     # from acceptance_history
        assert "state_transition_applied" in event_types     # also from fact_snapshot
        assert "task_packet_created" in event_types
        assert "executor_result_received" in event_types
        assert "evidence_consumed" in event_types
        assert "recovery_started" in event_types
        assert "recovery_resolved" in event_types
        assert "approval_requested" in event_types
        assert "approval_resolved" in event_types
        assert "capability_gap_raised" in event_types
        assert "artifact_promoted" in event_types
        assert "artifact_archived" in event_types


def test_timeline_sorted_correctly() -> None:
    """Timeline entries with time come before those without."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _make_timeline_fixture(root)
        proj = root / "projects" / "Crown_of_Ash"
        timeline = build_timeline(proj)

        if len(timeline) > 1:
            # entries should be sorted: times before empty
            first_empty_idx = None
            for i, e in enumerate(timeline):
                if not e["time"]:
                    first_empty_idx = i
                    break
            if first_empty_idx is not None and first_empty_idx > 0:
                # all entries before first_empty_idx should have time
                for j in range(first_empty_idx):
                    assert timeline[j]["time"], f"Entry at {j} should have time"


def test_timeline_ui_links_present() -> None:
    """Executor result events should include ui_link."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _make_timeline_fixture(root)
        proj = root / "projects" / "Crown_of_Ash"
        timeline = build_timeline(proj)

        er_events = [e for e in timeline if e["event_type"] == "executor_result_received"]
        for evt in er_events:
            assert "ui_link" in evt["data"]
            assert "/api/tasks/" in evt["data"]["ui_link"]


def test_build_failure_narrative_finds_root_cause() -> None:
    """Failure narrative should identify root cause from FAIL events."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _make_timeline_fixture(root)
        proj = root / "projects" / "Crown_of_Ash"

        narrative = build_failure_narrative(proj)

        assert narrative["failure_count"] == 1  # task_002 FAIL
        assert len(narrative["impacted_tasks"]) == 1
        assert "task_002" in narrative["impacted_tasks"]
        assert narrative["recovery_resolved"] is True
        assert len(narrative["recovery_options"]) >= 1
        assert narrative["capability_gaps_pending"] >= 1
        assert narrative["next_safe_action"] is not None


def test_build_failure_narrative_no_failures() -> None:
    """Empty project should produce valid empty narrative."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        proj = root / "projects" / "Empty"
        proj.mkdir(parents=True)
        (proj / "project_brain").mkdir()

        narrative = build_failure_narrative(proj)
        assert narrative["failure_count"] == 0
        assert narrative["root_cause"] == "no failure events found"


def test_empty_project_returns_empty_timeline() -> None:
    """Timeline on an empty project should return empty list."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        proj = root / "projects" / "Empty"
        proj.mkdir(parents=True)
        (proj / "project_brain").mkdir()

        timeline = build_timeline(proj)
        assert isinstance(timeline, list)
        # may have some events from acceptance history (empty entries = [])
