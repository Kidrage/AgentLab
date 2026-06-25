"""Tests for M2-12.5 Goal Validation — blocking behavior and deterministic checks."""

from pathlib import Path

import pytest
import yaml

from agent_runtime.goals.validation import compile_goal_validate
from agent_runtime.goals.action_schema import GoalActionSchema
from agent_runtime.goals.compiler import compile_goal_set, compile_goal_plan
from agent_runtime.goals.progress import compile_goal_progress


@pytest.fixture
def setup_brain(tmp_path):
    """Set up a complete Project Brain with all required artifacts."""
    action = GoalActionSchema(command="/goal", action="set", text="Build a CLI app", project="TestVal")
    compile_goal_set(action, tmp_path)
    compile_goal_plan(GoalActionSchema(action="plan", project="TestVal"), tmp_path)
    compile_goal_progress(GoalActionSchema(action="progress", project="TestVal"), tmp_path)
    return tmp_path


class TestValidationMissingMainlineProgram:
    def test_validate_errors_when_mainline_program_missing(self, tmp_path):
        brain_dir = get_brain_dir(tmp_path, "Empty")
        brain_dir.mkdir(parents=True)

        result = compile_goal_validate(
            GoalActionSchema(action="validate", project="Empty"), tmp_path
        )
        assert result.status == "error"
        assert "mainline" in result.message.lower()


class TestValidationBlockingBehavior:
    def test_validate_returns_blocked_when_required_artifacts_missing(self, tmp_path):
        brain_dir = get_brain_dir(tmp_path, "TestBlock")
        brain_dir.mkdir(parents=True)

        mainline = {
            "stages": [
                {
                    "stage_id": "test_stage",
                    "status": "pending",
                    "blocks_m2_closure": True,
                    "required_artifacts": ["nonexistent_artifact.yml"],
                    "required_evidence": ["goal_contract.yml"],
                    "acceptance_gates": ["demo_passed"],
                }
            ],
            "evidence": [],
            "gates": {"demo_passed": True},
        }
        (brain_dir / "mainline_program.yml").write_text(
            yaml.dump(mainline), encoding="utf-8"
        )
        (brain_dir / "goal_contract.yml").write_text(
            "project: TestBlock\n", encoding="utf-8"
        )
        acceptance = {
            "stages": [
                {
                    "stage_id": "test_stage",
                    "required_artifacts": ["nonexistent_artifact.yml"],
                    "required_evidence": ["goal_contract.yml"],
                    "acceptance_gates": ["demo_passed"],
                }
            ],
        }
        (brain_dir / "mainline_acceptance_contract.yml").write_text(
            yaml.dump(acceptance), encoding="utf-8"
        )

        result = compile_goal_validate(
            GoalActionSchema(action="validate", project="TestBlock"), tmp_path
        )
        assert result.status == "blocked"
        assert "nonexistent_artifact.yml" in result.message

    def test_validate_returns_blocked_when_required_evidence_missing(self, tmp_path):
        brain_dir = get_brain_dir(tmp_path, "TestBlock")
        brain_dir.mkdir(parents=True)

        mainline = {
            "stages": [
                {
                    "stage_id": "test_stage",
                    "status": "pending",
                    "blocks_m2_closure": True,
                    "required_artifacts": [],
                    "required_evidence": ["operator_demo_report"],
                    "acceptance_gates": [],
                }
            ],
            "evidence": [],
            "gates": {},
        }
        (brain_dir / "mainline_program.yml").write_text(
            yaml.dump(mainline), encoding="utf-8"
        )
        (brain_dir / "goal_contract.yml").write_text(
            "project: TestBlock\n", encoding="utf-8"
        )

        result = compile_goal_validate(
            GoalActionSchema(action="validate", project="TestBlock"), tmp_path
        )
        assert result.status == "blocked"
        assert "operator_demo_report" in result.message

    def test_validate_returns_blocked_when_acceptance_gate_missing(self, tmp_path):
        brain_dir = get_brain_dir(tmp_path, "TestBlock")
        brain_dir.mkdir(parents=True)

        mainline = {
            "stages": [
                {
                    "stage_id": "test_stage",
                    "status": "pending",
                    "blocks_m2_closure": True,
                    "required_artifacts": [],
                    "required_evidence": [],
                    "acceptance_gates": ["required_gate_not_present"],
                }
            ],
            "evidence": [],
            "gates": {},
        }
        (brain_dir / "mainline_program.yml").write_text(
            yaml.dump(mainline), encoding="utf-8"
        )
        (brain_dir / "goal_contract.yml").write_text(
            "project: TestBlock\n", encoding="utf-8"
        )

        result = compile_goal_validate(
            GoalActionSchema(action="validate", project="TestBlock"), tmp_path
        )
        assert result.status == "blocked"
        assert "required_gate_not_present" in result.message

    def test_validate_returns_ok_when_all_present(self, setup_brain):
        result = compile_goal_validate(
            GoalActionSchema(action="validate", project="TestVal"), setup_brain
        )
        assert result.status == "ok"

    def test_future_reserved_m3_stage_does_not_block(self, tmp_path):
        brain_dir = get_brain_dir(tmp_path, "TestBlock")
        brain_dir.mkdir(parents=True)

        mainline = {
            "stages": [
                {
                    "stage_id": "m2_stage",
                    "status": "pending",
                    "blocks_m2_closure": True,
                    "required_artifacts": [],
                    "required_evidence": [],
                    "acceptance_gates": [],
                },
                {
                    "stage_id": "m3_future_stage",
                    "status": "future_reserved",
                    "blocks_m2_closure": False,
                    "required_artifacts": ["m3_nonexistent.yml"],
                    "required_evidence": ["m3_missing_evidence"],
                    "acceptance_gates": ["m3_gate_missing"],
                },
            ],
            "evidence": [],
            "gates": {},
        }
        (brain_dir / "mainline_program.yml").write_text(
            yaml.dump(mainline), encoding="utf-8"
        )
        (brain_dir / "goal_contract.yml").write_text(
            "project: TestBlock\n", encoding="utf-8"
        )

        result = compile_goal_validate(
            GoalActionSchema(action="validate", project="TestBlock"), tmp_path
        )
        # M2 stage has no requirements, M3 future stage should be skipped
        assert result.status == "ok"

    def test_acceptance_history_records_blocked(self, tmp_path):
        brain_dir = get_brain_dir(tmp_path, "TestBlock")
        brain_dir.mkdir(parents=True)

        mainline = {
            "stages": [
                {
                    "stage_id": "test_stage",
                    "status": "pending",
                    "blocks_m2_closure": True,
                    "required_artifacts": ["missing_artifact.yml"],
                    "required_evidence": [],
                    "acceptance_gates": [],
                }
            ],
            "evidence": [],
            "gates": {},
        }
        (brain_dir / "mainline_program.yml").write_text(
            yaml.dump(mainline), encoding="utf-8"
        )
        (brain_dir / "goal_contract.yml").write_text(
            "project: TestBlock\n", encoding="utf-8"
        )
        (brain_dir / "acceptance_history.yml").write_text(
            "items: []\n", encoding="utf-8"
        )

        result = compile_goal_validate(
            GoalActionSchema(action="validate", project="TestBlock"), tmp_path
        )
        assert result.status == "blocked"

        hist = yaml.safe_load(
            (brain_dir / "acceptance_history.yml").read_text(encoding="utf-8")
        )
        entries = hist.get("items", [])
        assert any(e.get("status") == "blocked" for e in entries)

    def test_acceptance_history_records_pass(self, setup_brain):
        result = compile_goal_validate(
            GoalActionSchema(action="validate", project="TestVal"), setup_brain
        )
        assert result.status == "ok"

        brain_dir = setup_brain / "projects" / "TestVal" / "project_brain"
        hist = yaml.safe_load(
            (brain_dir / "acceptance_history.yml").read_text(encoding="utf-8")
        )
        entries = hist.get("items", [])
        assert any(e.get("status") == "pass" for e in entries)


def get_brain_dir(root: Path, project: str) -> Path:
    return root / "projects" / project / "project_brain"


class TestScenarioValidationFields:
    def test_scenario_validation_has_required_fields(self, setup_brain):
        brain_dir = setup_brain / "projects" / "TestVal" / "project_brain"
        sv = yaml.safe_load(
            (brain_dir / "scenario_validation_plan.yml").read_text(encoding="utf-8")
        )
        for sc in sv.get("scenarios", []):
            assert "scenario_id" in sc
            assert "description" in sc
            assert "required_artifacts" in sc
            assert "required_evidence" in sc
            assert "validation_method" in sc
            assert "pass_condition" in sc
            assert "blocking_if_missing" in sc
