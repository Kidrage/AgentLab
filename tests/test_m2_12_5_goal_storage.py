"""Tests for M2-12.5 Goal Storage — deterministic artifact persistence."""

import yaml
from pathlib import Path
from agent_runtime.goals.storage import get_project_brain_dir, write_yaml, read_yaml, append_to_yaml_list
from agent_runtime.goals.action_schema import GoalActionSchema
from agent_runtime.goals.compiler import compile_goal_set, compile_goal_plan
from agent_runtime.goals.progress import compile_goal_progress
from agent_runtime.goals.report import compile_goal_report


class TestProjectBrainStorage:
    def test_project_brain_stores_artifacts(self, tmp_path):
        brain_dir = get_project_brain_dir(tmp_path, "ProjX")
        assert brain_dir.name == "project_brain"
        write_yaml(brain_dir / "test.yml", {"hello": "world"})
        data = read_yaml(brain_dir / "test.yml")
        assert data["hello"] == "world"

    def test_read_yaml_returns_empty_dict_for_missing_file(self, tmp_path):
        brain_dir = get_project_brain_dir(tmp_path, "ProjX")
        data = read_yaml(brain_dir / "nonexistent.yml")
        assert data == {}

    def test_append_to_yaml_list_creates_new_file(self, tmp_path):
        brain_dir = get_project_brain_dir(tmp_path, "ProjX")
        append_to_yaml_list(brain_dir / "new_list.yml", {"key": "value"})
        data = read_yaml(brain_dir / "new_list.yml")
        assert "items" in data
        assert len(data["items"]) == 1
        assert data["items"][0]["key"] == "value"

    def test_append_to_yaml_list_appends(self, tmp_path):
        brain_dir = get_project_brain_dir(tmp_path, "ProjX")
        append_to_yaml_list(brain_dir / "list.yml", {"num": 1})
        append_to_yaml_list(brain_dir / "list.yml", {"num": 2})
        data = read_yaml(brain_dir / "list.yml")
        assert len(data["items"]) == 2

    def test_get_project_brain_dir_creates_directory(self, tmp_path):
        brain_dir = get_project_brain_dir(tmp_path, "NewProj")
        assert brain_dir.exists()
        assert brain_dir.is_dir()


class TestGoalStorageArtifacts:
    """Verify full goal lifecycle produces all expected artifacts."""

    def test_full_lifecycle_creates_all_expected_files(self, tmp_path):
        project = "TestStorage"
        action_set = GoalActionSchema(command="/goal", action="set",
                                      text="Build a CLI app", project=project)
        compile_goal_set(action_set, tmp_path)
        compile_goal_plan(GoalActionSchema(action="plan", project=project), tmp_path)
        compile_goal_progress(GoalActionSchema(action="progress", project=project), tmp_path)

        brain_dir = tmp_path / "projects" / project / "project_brain"
        expected = [
            "goal_contract.yml",
            "mission_contract.yml",
            "workflow_plan.yml",
            "mainline_program.yml",
            "mainline_acceptance_contract.yml",
            "scenario_validation_plan.yml",
            "mainline_progress.yml",
            "next_actions.yml",
            "decision_log.yml",
            "acceptance_history.yml",
        ]
        for filename in expected:
            assert (brain_dir / filename).is_file(), f"Missing: {filename}"

    def test_goal_contract_has_required_fields(self, tmp_path):
        action = GoalActionSchema(command="/goal", action="set",
                                  text="Test goal", project="TestStorage")
        compile_goal_set(action, tmp_path)
        brain_dir = tmp_path / "projects" / "TestStorage" / "project_brain"
        contract = yaml.safe_load(
            (brain_dir / "goal_contract.yml").read_text(encoding="utf-8"))
        assert "goal_id" in contract
        assert "project" in contract
        assert "compiled_template" in contract
