"""Tests for M2-12.5 Goal Storage — deterministic artifact persistence."""

from __future__ import annotations

import pytest
import yaml

from agent_runtime.goals.parser import parse_goal_command
from agent_runtime.goals.compiler import (
    compile_goal_set,
    compile_goal_plan,
    compile_goal_progress,
    compile_goal_report,
    compile_goal_validate,
)


@pytest.fixture
def goal_action():
    return parse_goal_command("/goal set Build a CLI app --project TestStorage")


class TestGoalStorageArtifacts:
    """Verify full goal lifecycle produces all expected Project Brain artifacts."""

    def test_full_lifecycle_creates_all_expected_files(self, goal_action, tmp_path):
        project = "TestStorage"
        brain_dir = tmp_path / "projects" / project / "project_brain"

        compile_goal_set(goal_action, tmp_path, project)
        compile_goal_plan(goal_action, tmp_path, project)
        compile_goal_progress(goal_action, tmp_path, project)
        compile_goal_validate(goal_action, tmp_path, project)
        compile_goal_report(goal_action, tmp_path, project)

        expected_files = [
            "goal_contract.yml",
            "mission_contract.yml",
            "workflow_plan.yml",
            "mainline_program.yml",
            "mainline_acceptance_contract.yml",
            "scenario_validation_plan.yml",
            "mainline_progress.yml",
            "mainline_completion_report.md",
            "next_actions.yml",
            "decision_log.yml",
            "acceptance_history.yml",
        ]
        for filename in expected_files:
            assert (brain_dir / filename).is_file(), f"Missing: {filename}"

    def test_goal_contract_has_required_fields(self, goal_action, tmp_path):
        compile_goal_set(goal_action, tmp_path, "TestStorage")
        brain_dir = tmp_path / "projects" / "TestStorage" / "project_brain"
        contract = yaml.safe_load(
            (brain_dir / "goal_contract.yml").read_text(encoding="utf-8")
        )
        assert "goal_id" in contract
        assert "project" in contract
        assert "text" in contract
        assert "domain" in contract
        assert "template_id" in contract
        assert "status" in contract

    def test_decision_log_grows_with_each_action(self, goal_action, tmp_path):
        project = "TestStorage"
        brain_dir = tmp_path / "projects" / project / "project_brain"

        compile_goal_set(goal_action, tmp_path, project)
        log1 = yaml.safe_load((brain_dir / "decision_log.yml").read_text(encoding="utf-8"))
        count1 = len(log1.get("entries", []))

        compile_goal_plan(goal_action, tmp_path, project)
        log2 = yaml.safe_load((brain_dir / "decision_log.yml").read_text(encoding="utf-8"))
        count2 = len(log2.get("entries", []))

        assert count2 > count1

    def test_acceptance_history_grows_with_each_action(self, goal_action, tmp_path):
        project = "TestStorage"
        brain_dir = tmp_path / "projects" / project / "project_brain"

        compile_goal_set(goal_action, tmp_path, project)
        hist1 = yaml.safe_load(
            (brain_dir / "acceptance_history.yml").read_text(encoding="utf-8")
        )
        count1 = len(hist1.get("entries", []))

        compile_goal_plan(goal_action, tmp_path, project)
        hist2 = yaml.safe_load(
            (brain_dir / "acceptance_history.yml").read_text(encoding="utf-8")
        )
        count2 = len(hist2.get("entries", []))

        assert count2 > count1

    def test_mainline_program_has_stages(self, goal_action, tmp_path):
        compile_goal_set(goal_action, tmp_path, "TestStorage")
        compile_goal_plan(goal_action, tmp_path, "TestStorage")
        brain_dir = tmp_path / "projects" / "TestStorage" / "project_brain"
        mainline = yaml.safe_load(
            (brain_dir / "mainline_program.yml").read_text(encoding="utf-8")
        )
        assert len(mainline.get("stages", [])) > 0

    def test_out_dir_shadow_has_all_project_brain_files(self, goal_action, tmp_path):
        project = "TestStorage"
        out = tmp_path / "out"

        compile_goal_set(goal_action, tmp_path, project, out_dir=out)
        compile_goal_plan(goal_action, tmp_path, project, out_dir=out)
        compile_goal_progress(goal_action, tmp_path, project, out_dir=out)
        compile_goal_report(goal_action, tmp_path, project, out_dir=out)

        out_brain = out / "projects" / project / "project_brain"
        expected = [
            "goal_contract.yml",
            "mission_contract.yml",
            "workflow_plan.yml",
            "mainline_program.yml",
            "mainline_acceptance_contract.yml",
            "scenario_validation_plan.yml",
            "mainline_progress.yml",
            "mainline_completion_report.md",
        ]
        for filename in expected:
            assert (out_brain / filename).is_file(), f"Missing in out_dir: {filename}"
