from __future__ import annotations

from pathlib import Path
import sys
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent_runtime"))

from agent_runtime.recovery.replanning import replan_phase


def test_replan_evidence_missing(tmp_path: Path):
    acceptance = {
        "phase_id": "phase_1",
        "verdict": "FAIL",
        "missing_evidence": ["test_evidence.yml"],
    }
    out_dir = tmp_path / "out"

    res = replan_phase(acceptance, out_dir=out_dir)
    assert res["failure_reason"] == "evidence_missing"
    assert res["recommended_next_action"] == "ask_user"
    assert (out_dir / "replan_plan.yml").is_file()


def test_replan_capability_gap(tmp_path: Path):
    acceptance = {
        "phase_id": "phase_1",
        "verdict": "BLOCKED",
        "verdict_details": "blocked",
        "required_capability": "image_understanding",
    }
    out_dir = tmp_path / "out"

    res = replan_phase(acceptance, out_dir=out_dir)
    assert res["failure_reason"] == "capability_gap"
    assert res["recommended_next_action"] == "ask_user"
    assert (out_dir / "capability_gap_decision_card.yml").is_file()


def test_replan_budget_exceeded(tmp_path: Path):
    acceptance = {
        "phase_id": "phase_1",
        "verdict": "FAIL",
        "budget_exceeded": True,
    }
    out_dir = tmp_path / "out"

    res = replan_phase(acceptance, out_dir=out_dir)
    assert res["failure_reason"] == "budget_exceeded"
    assert res["recommended_next_action"] == "stop_safely"


def test_replan_scope_drift(tmp_path: Path):
    acceptance = {
        "phase_id": "phase_1",
        "verdict": "FAIL",
        "scope_status": {"has_violations": True, "unauthorized_edits": [".env"]},
    }
    out_dir = tmp_path / "out"

    res = replan_phase(acceptance, out_dir=out_dir)
    assert res["failure_reason"] == "scope_drift"
    assert res["recommended_next_action"] == "rollback_phase"


def test_replan_retry_capping(tmp_path: Path):
    acceptance = {
        "phase_id": "phase_1",
        "verdict": "FAIL",
        "test_results": {"passed": False},
    }

    brain_dir = tmp_path / "brain"
    brain_dir.mkdir()
    history_path = brain_dir / "acceptance_history.yml"

    # 0 failed attempts initially
    yaml.dump({"entries": []}, history_path.open("w", encoding="utf-8"))
    res = replan_phase(acceptance, project_brain_dir=brain_dir, out_dir=tmp_path / "out1")
    assert res["retry_count"] == 0
    assert res["recommended_next_action"] == "retry_same"

    # 1 failed attempt in history
    history = {
        "entries": [
            {"phase_id": "phase_1", "accepted": False, "verdict": "FAIL"}
        ]
    }
    yaml.dump(history, history_path.open("w", encoding="utf-8"))
    res = replan_phase(acceptance, project_brain_dir=brain_dir, out_dir=tmp_path / "out2")
    assert res["retry_count"] == 1
    assert res["recommended_next_action"] == "retry_same"

    # 3 failed attempts in history (retry limit is 3)
    history = {
        "entries": [
            {"phase_id": "phase_1", "accepted": False, "verdict": "FAIL"},
            {"phase_id": "phase_1", "accepted": False, "verdict": "FAIL"},
            {"phase_id": "phase_1", "accepted": False, "verdict": "FAIL"},
        ]
    }
    yaml.dump(history, history_path.open("w", encoding="utf-8"))
    res = replan_phase(acceptance, project_brain_dir=brain_dir, out_dir=tmp_path / "out3", retry_limit=3)
    assert res["retry_count"] == 3
    assert res["recommended_next_action"] == "ask_user"
