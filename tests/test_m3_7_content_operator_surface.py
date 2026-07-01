"""M3-7 Content Project Operator Surface — promotion chain visibility tests."""

from __future__ import annotations

from pathlib import Path

import yaml

from agent_runtime.operator_os.content_surface import build_content_project_state


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _make_crown_project(root: Path) -> Path:
    """Create a Crown-of-Ash project fixture with artifacts and promotion chain."""
    proj = root / "projects" / "Crown_of_Ash"
    brain = proj / "project_brain"
    runs = proj / "runs"
    brain.mkdir(parents=True)

    # artifact index with current, candidate, archived
    _write_yaml(proj / "project_artifact_index.yml", {
        "artifacts": [
            {"artifact_id": "ch1_v2", "type": "chapter", "status": "current"},
            {"artifact_id": "ch2_draft", "type": "chapter", "status": "candidate"},
            {"artifact_id": "ch1_v1", "type": "chapter", "status": "archived"},
        ],
    })

    # fact snapshot
    _write_yaml(brain / "project_fact_snapshot.yml", {
        "project": "Crown_of_Ash",
        "event_count": 5,
    })

    # task with promotion chain: candidate → lineage → proposal → acceptance
    t1 = runs / "task_promote_ch1"
    t1.mkdir(parents=True)

    _write_yaml(t1 / "state_transition_proposal.yml", {
        "artifact_id": "ch2_draft",
        "from_status": "candidate",
        "to_status": "current",
        "replaces": "ch1_v2",
        "status": "pending",
    })

    _write_yaml(t1 / "artifact_lineage.yml", {
        "artifact_id": "ch2_draft",
        "parent": "world_bible_v3",
        "derived_from": ["ch1_v2", "outline_act2"],
    })

    _write_yaml(t1 / "continuity_report.yml", {
        "phase_id": "continuity_check",
        "warnings": [
            "timeline discrepancy: character age at chapter 2 start",
        ],
    })

    _write_yaml(t1 / "phase_acceptance.yml", {
        "phase_id": "promote_ch2",
        "verdict": "PASS",
        "recorded_at": "2026-07-01T04:00:00Z",
        "state_transition": {
            "applied": True,
            "archive_receipt": "archive/ch1_v2_final.md",
        },
    })

    # task with a completed promotion
    t2 = runs / "task_completed_ch1"
    t2.mkdir(parents=True)
    _write_yaml(t2 / "state_transition_proposal.yml", {
        "artifact_id": "ch1_v2",
        "from_status": "candidate",
        "to_status": "current",
        "replaces": "ch1_v1",
        "status": "applied",
    })

    # create production/candidate/archive dirs
    (proj / "production").mkdir(exist_ok=True)
    (proj / "candidates").mkdir(exist_ok=True)
    (proj / "archive").mkdir(exist_ok=True)

    return proj


def test_content_project_state_has_all_required_sections() -> None:
    """build_content_project_state must return all required sections."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _make_crown_project(root)
        proj = root / "projects" / "Crown_of_Ash"
        state = build_content_project_state(proj)

        required = {
            "project", "production_root", "candidate_roots", "archive_root",
            "artifact_index", "fact_snapshot", "state_transition_proposals",
            "artifact_lineages", "continuity_warnings", "chapter_batch_status",
            "promotion_readiness", "blocking_hygiene_errors", "blocking_reasons",
        }
        assert required.issubset(set(state.keys())), f"Missing: {required - set(state.keys())}"


def test_artifact_index_counts() -> None:
    """Artifact index should correctly count current/candidate/archived."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _make_crown_project(root)
        proj = root / "projects" / "Crown_of_Ash"
        state = build_content_project_state(proj)

        ai = state["artifact_index"]
        assert ai["current_count"] == 1
        assert ai["candidate_count"] == 1
        assert ai["archived_count"] == 1


def test_state_transition_proposals_collected() -> None:
    """All state_transition_proposal.yml files should be collected."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _make_crown_project(root)
        proj = root / "projects" / "Crown_of_Ash"
        state = build_content_project_state(proj)

        assert len(state["state_transition_proposals"]) == 2
        statuses = {p["status"] for p in state["state_transition_proposals"]}
        assert "pending" in statuses
        assert "applied" in statuses


def test_promotion_readiness_with_blocking_continuity() -> None:
    """Continuity warnings should block promotion readiness."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _make_crown_project(root)
        proj = root / "projects" / "Crown_of_Ash"
        state = build_content_project_state(proj)

        assert state["promotion_readiness"]["ready"] is False
        assert any("continuity" in r.lower() for r in state["promotion_readiness"]["reasons"])


def test_blocking_reasons_per_candidate() -> None:
    """Each candidate should have blocking reasons analyzed."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _make_crown_project(root)
        proj = root / "projects" / "Crown_of_Ash"
        state = build_content_project_state(proj)

        assert len(state["blocking_reasons"]) == 1
        assert state["blocking_reasons"][0]["artifact_id"] == "ch2_draft"


def test_multiple_current_artifacts_is_blocking() -> None:
    """Multiple current artifacts should produce a blocking hygiene error."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        proj = root / "projects" / "Crown_of_Ash"
        brain = proj / "project_brain"
        brain.mkdir(parents=True)

        # two artifacts both marked "current"
        _write_yaml(proj / "project_artifact_index.yml", {
            "artifacts": [
                {"artifact_id": "ch1_v2", "type": "chapter", "status": "current"},
                {"artifact_id": "ch1_v3", "type": "chapter", "status": "current"},
            ],
        })

        state = build_content_project_state(proj)
        assert len(state["blocking_hygiene_errors"]) >= 1
        assert any("multiple_current_artifacts" in e.get("type", "") for e in state["blocking_hygiene_errors"])
        assert state["promotion_readiness"]["ready"] is False


def test_empty_project_returns_valid_state() -> None:
    """Empty project should return valid structure without errors."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        proj = root / "projects" / "Empty"
        (proj / "project_brain").mkdir(parents=True)

        state = build_content_project_state(proj)
        assert state["project"] == "Empty"
        assert state["artifact_index"]["current_count"] == 0
        assert state["promotion_readiness"]["ready"] is False
