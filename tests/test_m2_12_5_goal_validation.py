"""Tests for M2-12.5 Goal Validation — blocking behavior and deterministic checks."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agent_runtime.goals.parser import parse_goal_command
from agent_runtime.goals.compiler import (
    compile_goal_set,
    compile_goal_plan,
    compile_goal_progress,
)
from agent_runtime.goals.validation import validate_goal_acceptance


@pytest.fixture
def brain_with_all_artifacts(tmp_path):
    """Set up a complete Project Brain with all required artifacts."""
    action = parse_goal_command("/goal set Build a CLI app --project TestVal")
    compile_goal_set(action, tmp_path, "TestVal")
    compile_goal_plan(action, tmp_path, "TestVal")
    compile_goal_progress(action, tmp_path, "TestVal")
    return tmp_path / "projects" / "TestVal" / "project_brain"


class TestValidationMissingMainlineProgram:
    def test_validate_blocks_when_mainline_program_missing(self, tmp_path):
        brain_dir = tmp_path / "projects" / "Empty" / "project_brain"
        brain_dir.mkdir(parents=True)

        result = validate_goal_acceptance(brain_dir)
        assert result["status"] == "blocked"
        assert "mainline_program.yml" in result["message"]


class TestValidationBlockingBehavior:
    def test_validate_returns_blocked_when_required_artifacts_missing(self, tmp_path):
        """Block when a stage requires an artifact that doesn't exist."""
        brain_dir = tmp_path / "projects" / "TestBlock" / "project_brain"
        brain_dir.mkdir(parents=True)

        # Write a mainline_program with a stage that requires a missing artifact
        mainline = {
            "project": "TestBlock",
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
        import yaml
        (brain_dir / "mainline_program.yml").write_text(
            yaml.dump(mainline), encoding="utf-8"
        )
        # goal_contract.yml exists (evidence requirement)
        (brain_dir / "goal_contract.yml").write_text("project: TestBlock\n", encoding="utf-8")

        # Also write acceptance_contract with the same stages
        acceptance = {
            "project": "TestBlock",
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

        result = validate_goal_acceptance(brain_dir)
        assert result["status"] == "blocked"
        assert any(
            "nonexistent_artifact.yml" in reason
            for reason in result.get("blocking_reasons", [])
        )

    def test_validate_returns_blocked_when_required_evidence_missing(self, tmp_path):
        brain_dir = tmp_path / "projects" / "TestBlock" / "project_brain"
        brain_dir.mkdir(parents=True)

        mainline = {
            "project": "TestBlock",
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
        import yaml
        (brain_dir / "mainline_program.yml").write_text(
            yaml.dump(mainline), encoding="utf-8"
        )
        (brain_dir / "goal_contract.yml").write_text("project: TestBlock\n", encoding="utf-8")

        acceptance = {
            "project": "TestBlock",
            "stages": [
                {
                    "stage_id": "test_stage",
                    "required_artifacts": [],
                    "required_evidence": ["operator_demo_report"],
                    "acceptance_gates": [],
                }
            ],
        }
        (brain_dir / "mainline_acceptance_contract.yml").write_text(
            yaml.dump(acceptance), encoding="utf-8"
        )

        result = validate_goal_acceptance(brain_dir)
        assert result["status"] == "blocked"
        assert any(
            "operator_demo_report" in reason
            for reason in result.get("blocking_reasons", [])
        )

    def test_validate_returns_blocked_when_acceptance_gate_missing(self, tmp_path):
        brain_dir = tmp_path / "projects" / "TestBlock" / "project_brain"
        brain_dir.mkdir(parents=True)

        mainline = {
            "project": "TestBlock",
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
            "gates": {},  # Gate not provided
        }
        import yaml
        (brain_dir / "mainline_program.yml").write_text(
            yaml.dump(mainline), encoding="utf-8"
        )
        (brain_dir / "goal_contract.yml").write_text("project: TestBlock\n", encoding="utf-8")

        acceptance = {
            "project": "TestBlock",
            "stages": [
                {
                    "stage_id": "test_stage",
                    "required_artifacts": [],
                    "required_evidence": [],
                    "acceptance_gates": ["required_gate_not_present"],
                }
            ],
        }
        (brain_dir / "mainline_acceptance_contract.yml").write_text(
            yaml.dump(acceptance), encoding="utf-8"
        )

        result = validate_goal_acceptance(brain_dir)
        assert result["status"] == "blocked"
        assert any(
            "required_gate_not_present" in reason
            for reason in result.get("blocking_reasons", [])
        )

    def test_validate_returns_ok_when_all_present(self, brain_with_all_artifacts):
        result = validate_goal_acceptance(brain_with_all_artifacts)
        assert result["status"] == "pass"
        assert len(result.get("blocking_reasons", [])) == 0

    def test_future_reserved_m3_stage_does_not_block(self, tmp_path):
        brain_dir = tmp_path / "projects" / "TestBlock" / "project_brain"
        brain_dir.mkdir(parents=True)

        mainline = {
            "project": "TestBlock",
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
        import yaml
        (brain_dir / "mainline_program.yml").write_text(
            yaml.dump(mainline), encoding="utf-8"
        )
        (brain_dir / "goal_contract.yml").write_text("project: TestBlock\n", encoding="utf-8")

        acceptance = {
            "project": "TestBlock",
            "stages": [
                {
                    "stage_id": "m2_stage",
                    "required_artifacts": [],
                    "required_evidence": [],
                    "acceptance_gates": [],
                },
                {
                    "stage_id": "m3_future_stage",
                    "required_artifacts": ["m3_nonexistent.yml"],
                    "required_evidence": ["m3_missing_evidence"],
                    "acceptance_gates": ["m3_gate_missing"],
                },
            ],
        }
        (brain_dir / "mainline_acceptance_contract.yml").write_text(
            yaml.dump(acceptance), encoding="utf-8"
        )

        result = validate_goal_acceptance(brain_dir)
        # M2 stage has no requirements, M3 future stage should be skipped
        assert result["status"] == "pass"

    def test_acceptance_history_records_blocked(self, tmp_path):
        brain_dir = tmp_path / "projects" / "TestBlock" / "project_brain"
        brain_dir.mkdir(parents=True)

        mainline = {
            "project": "TestBlock",
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
        import yaml
        (brain_dir / "mainline_program.yml").write_text(
            yaml.dump(mainline), encoding="utf-8"
        )
        (brain_dir / "goal_contract.yml").write_text("project: TestBlock\n", encoding="utf-8")
        (brain_dir / "acceptance_history.yml").write_text(
            "entries: []\n", encoding="utf-8"
        )

        acceptance = {
            "project": "TestBlock",
            "stages": [
                {
                    "stage_id": "test_stage",
                    "required_artifacts": ["missing_artifact.yml"],
                    "required_evidence": [],
                    "acceptance_gates": [],
                }
            ],
        }
        (brain_dir / "mainline_acceptance_contract.yml").write_text(
            yaml.dump(acceptance), encoding="utf-8"
        )

        result = validate_goal_acceptance(brain_dir)
        assert result["status"] == "blocked"

        # Check acceptance_history was updated with blocked entry
        hist = yaml.safe_load(
            (brain_dir / "acceptance_history.yml").read_text(encoding="utf-8")
        )
        entries = hist.get("entries", [])
        assert len(entries) >= 1
        assert entries[-1]["status"] == "blocked"

    def test_acceptance_history_records_pass(self, brain_with_all_artifacts):
        result = validate_goal_acceptance(brain_with_all_artifacts)
        assert result["status"] == "pass"

        hist = yaml.safe_load(
            (brain_with_all_artifacts / "acceptance_history.yml").read_text(encoding="utf-8")
        )
        entries = hist.get("entries", [])
        assert any(e.get("status") == "pass" for e in entries)
