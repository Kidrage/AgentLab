"""Tests for M2-12.5 Goal Compiler — deterministic artifact generation."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agent_runtime.goals.parser import GoalActionSchema, parse_goal_command
from agent_runtime.goals.compiler import (
    compile_goal_set,
    compile_goal_plan,
    compile_goal_progress,
    compile_goal_report,
)


@pytest.fixture
def goal_action():
    return parse_goal_command("/goal set Build a Python CLI task runner app --project TestProject")


class TestCompileGoalSet:
    def test_compile_goal_set_creates_goal_contract(self, goal_action, tmp_path):
        result = compile_goal_set(goal_action, tmp_path, "TestProject")
        assert result["ok"] is True
        assert result["artifact"] == "goal_contract.yml"

        brain_dir = tmp_path / "projects" / "TestProject" / "project_brain"
        assert (brain_dir / "goal_contract.yml").is_file()

    def test_compile_goal_set_writes_decision_log(self, goal_action, tmp_path):
        compile_goal_set(goal_action, tmp_path, "TestProject")
        brain_dir = tmp_path / "projects" / "TestProject" / "project_brain"
        log = yaml.safe_load((brain_dir / "decision_log.yml").read_text(encoding="utf-8"))
        assert len(log.get("entries", [])) >= 1

    def test_compile_goal_set_writes_acceptance_history(self, goal_action, tmp_path):
        compile_goal_set(goal_action, tmp_path, "TestProject")
        brain_dir = tmp_path / "projects" / "TestProject" / "project_brain"
        hist = yaml.safe_load((brain_dir / "acceptance_history.yml").read_text(encoding="utf-8"))
        assert len(hist.get("entries", [])) >= 1

    def test_compile_goal_set_shadows_to_out_dir(self, goal_action, tmp_path):
        out = tmp_path / "out"
        compile_goal_set(goal_action, tmp_path, "TestProject", out_dir=out)
        assert (out / "goal_contract.yml").is_file()


class TestCompileGoalPlan:
    def test_compile_goal_plan_creates_mission_contract(self, goal_action, tmp_path):
        compile_goal_set(goal_action, tmp_path, "TestProject")
        result = compile_goal_plan(goal_action, tmp_path, "TestProject")
        assert result["ok"] is True

        brain_dir = tmp_path / "projects" / "TestProject" / "project_brain"
        assert (brain_dir / "mission_contract.yml").is_file()

    def test_compile_goal_plan_creates_workflow_plan(self, goal_action, tmp_path):
        compile_goal_set(goal_action, tmp_path, "TestProject")
        compile_goal_plan(goal_action, tmp_path, "TestProject")

        brain_dir = tmp_path / "projects" / "TestProject" / "project_brain"
        assert (brain_dir / "workflow_plan.yml").is_file()

    def test_compile_goal_plan_creates_mainline_program(self, goal_action, tmp_path):
        compile_goal_set(goal_action, tmp_path, "TestProject")
        compile_goal_plan(goal_action, tmp_path, "TestProject")

        brain_dir = tmp_path / "projects" / "TestProject" / "project_brain"
        assert (brain_dir / "mainline_program.yml").is_file()

    def test_compile_goal_plan_creates_acceptance_contract(self, goal_action, tmp_path):
        compile_goal_set(goal_action, tmp_path, "TestProject")
        compile_goal_plan(goal_action, tmp_path, "TestProject")

        brain_dir = tmp_path / "projects" / "TestProject" / "project_brain"
        assert (brain_dir / "mainline_acceptance_contract.yml").is_file()

    def test_compile_goal_plan_creates_scenario_validation_plan(self, goal_action, tmp_path):
        compile_goal_set(goal_action, tmp_path, "TestProject")
        compile_goal_plan(goal_action, tmp_path, "TestProject")

        brain_dir = tmp_path / "projects" / "TestProject" / "project_brain"
        assert (brain_dir / "scenario_validation_plan.yml").is_file()

    def test_compile_goal_plan_creates_next_actions(self, goal_action, tmp_path):
        compile_goal_set(goal_action, tmp_path, "TestProject")
        compile_goal_plan(goal_action, tmp_path, "TestProject")

        brain_dir = tmp_path / "projects" / "TestProject" / "project_brain"
        assert (brain_dir / "next_actions.yml").is_file()

    def test_compile_goal_plan_shadows_to_out_dir(self, goal_action, tmp_path):
        compile_goal_set(goal_action, tmp_path, "TestProject")
        out = tmp_path / "out"
        compile_goal_plan(goal_action, tmp_path, "TestProject", out_dir=out)

        out_brain = out / "projects" / "TestProject" / "project_brain"
        assert (out_brain / "mainline_program.yml").is_file()
        assert (out_brain / "scenario_validation_plan.yml").is_file()

    def test_scenario_validation_has_required_fields(self, goal_action, tmp_path):
        compile_goal_set(goal_action, tmp_path, "TestProject")
        compile_goal_plan(goal_action, tmp_path, "TestProject")

        brain_dir = tmp_path / "projects" / "TestProject" / "project_brain"
        scenario = yaml.safe_load(
            (brain_dir / "scenario_validation_plan.yml").read_text(encoding="utf-8")
        )
        for sc in scenario.get("scenarios", []):
            assert "scenario_id" in sc
            assert "description" in sc
            assert "required_artifacts" in sc
            assert "required_evidence" in sc
            assert "validation_method" in sc
            assert "pass_condition" in sc
            assert "blocking_if_missing" in sc


class TestCompileGoalProgress:
    def test_compile_goal_progress_creates_mainline_progress(self, goal_action, tmp_path):
        compile_goal_set(goal_action, tmp_path, "TestProject")
        compile_goal_plan(goal_action, tmp_path, "TestProject")
        result = compile_goal_progress(goal_action, tmp_path, "TestProject")
        assert result["ok"] is True

        brain_dir = tmp_path / "projects" / "TestProject" / "project_brain"
        assert (brain_dir / "mainline_progress.yml").is_file()


class TestCompileGoalReport:
    def test_compile_goal_report_creates_report(self, goal_action, tmp_path):
        compile_goal_set(goal_action, tmp_path, "TestProject")
        compile_goal_plan(goal_action, tmp_path, "TestProject")
        compile_goal_progress(goal_action, tmp_path, "TestProject")
        result = compile_goal_report(goal_action, tmp_path, "TestProject")
        assert result["ok"] is True
        assert result["artifact"] == "mainline_completion_report.md"

        brain_dir = tmp_path / "projects" / "TestProject" / "project_brain"
        assert (brain_dir / "mainline_completion_report.md").is_file()
