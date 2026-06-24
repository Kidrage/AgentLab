from __future__ import annotations

from pathlib import Path
import sys
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent_runtime"))

from agent_runtime.program_manager.scope_checker import check_scope
from agent_runtime.program_manager.evidence_checker import check_evidence
from agent_runtime.program_manager.next_action_decider import decide_verdict
from agent_runtime.program_manager.phase_acceptance import accept_phase


def test_scope_checker():
    phase_plan = {
        "allowed_files": ["src/main.py", "tests/"],
        "forbidden_files": ["config/secrets.yml", ".env"],
    }

    # Test clean changes
    res = check_scope(phase_plan, ["src/main.py", "tests/test_main.py"])
    assert res["has_drift"] is False
    assert res["has_violations"] is False

    # Test scope drift
    res = check_scope(phase_plan, ["src/main.py", "scripts/deploy.sh"])
    assert res["has_drift"] is True
    assert res["scope_drift"] == ["scripts/deploy.sh"]
    assert res["has_violations"] is False

    # Test violations
    res = check_scope(phase_plan, ["src/main.py", ".env"])
    assert res["has_violations"] is True
    assert res["unauthorized_edits"] == [".env"]


def test_evidence_checker(tmp_path: Path):
    phase_plan = {
        "evidence_required": ["report.json", "logs/run.log"],
    }

    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()

    # Empty dir -> missing evidence
    res = check_evidence(phase_plan, evidence_dir)
    assert res["has_missing"] is True
    assert res["missing_evidence"] == ["report.json", "logs/run.log"]

    # Partial evidence
    (evidence_dir / "report.json").write_text("{}", encoding="utf-8")
    res = check_evidence(phase_plan, evidence_dir)
    assert res["has_missing"] is True
    assert res["missing_evidence"] == ["logs/run.log"]

    # All evidence met
    logs_dir = evidence_dir / "logs"
    logs_dir.mkdir()
    (logs_dir / "run.log").write_text("ok", encoding="utf-8")
    res = check_evidence(phase_plan, evidence_dir)
    assert res["has_missing"] is False
    assert len(res["missing_evidence"]) == 0


def test_next_action_decider():
    # Pass case
    scope = {"has_drift": False, "has_violations": False}
    evidence = {"has_missing": False}
    tests = {"passed": True, "failed_count": 0}
    res = decide_verdict(scope, evidence, tests, human_approval_required=False)
    assert res["verdict"] == "accept"
    assert res["recommended_next_action"] == "next_phase"

    # Human gate case
    res = decide_verdict(scope, evidence, tests, human_approval_required=True)
    assert res["verdict"] == "ask_user"
    assert res["recommended_next_action"] == "ask_user"

    # Scope drift case
    scope_drift = {"has_drift": True, "has_violations": False, "scope_drift": ["deploy.sh"]}
    res = decide_verdict(scope_drift, evidence, tests, human_approval_required=False)
    assert res["verdict"] == "ask_user"
    assert res["recommended_next_action"] == "ask_user"

    # Test failure case
    tests_fail = {"passed": False, "failed_count": 2}
    res = decide_verdict(scope, evidence, tests_fail, human_approval_required=False)
    assert res["verdict"] == "retry"
    assert res["recommended_next_action"] == "retry_same"

    # Missing evidence case
    evidence_missing = {"has_missing": True, "missing_evidence": ["report.json"]}
    res = decide_verdict(scope, evidence_missing, tests, human_approval_required=False)
    assert res["verdict"] == "blocked"
    assert res["recommended_next_action"] == "ask_user"

    # Unauthorized edit violation (highest priority)
    scope_violation = {"has_drift": False, "has_violations": True, "unauthorized_edits": [".env"]}
    res = decide_verdict(scope_violation, evidence_missing, tests_fail, human_approval_required=True)
    assert res["verdict"] == "rollback"
    assert res["recommended_next_action"] == "rollback_phase"


def test_accept_phase_end_to_end(tmp_path: Path):
    phase_plan_path = tmp_path / "phase_plan.yml"
    phase_plan_path.write_text(
        yaml.safe_dump({
            "project": "TestProject",
            "phase_id": "phase_001",
            "goal": "Verify phase accept",
            "outputs": ["app.py"],
            "evidence_required": ["evidence.txt"],
            "human_decision_points": [],
        }),
        encoding="utf-8"
    )

    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    (evidence_dir / "evidence.txt").write_text("evidence data", encoding="utf-8")

    out_dir = tmp_path / "out"

    # Execute accept_phase
    res = accept_phase(phase_plan_path, evidence_dir, out_dir)
    assert res["accepted"] is True
    assert res["verdict"] == "PASS"
    assert res["verdict_details"] == "accept"

    assert (out_dir / "phase_acceptance.yml").is_file()
    assert (out_dir / "phase_acceptance.md").is_file()

    # Verify Markdown report content
    report_text = (out_dir / "phase_acceptance.md").read_text(encoding="utf-8")
    assert "# AgentLab Phase Acceptance Report: phase_001" in report_text
    assert "✅ **PASS**" in report_text or "✅ **ACCEPT**" in report_text
