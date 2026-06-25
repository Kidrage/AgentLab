"""Tests for M2-12.5 Goal Surfaces — shared schema and integration points."""

from __future__ import annotations

from agent_runtime.goals.parser import GoalActionSchema, parse_goal_command


class TestSharedGoalActionSchema:
    def test_schema_is_serializable(self):
        action = GoalActionSchema(
            action="set",
            project="Test",
            text="Build a CLI app",
            domain="codebase_build",
        )
        data = {
            "action": action.action,
            "project": action.project,
            "text": action.text,
            "domain": action.domain,
            "template_id": action.template_id,
            "aliases": action.aliases,
            "raw_parts": action.raw_parts,
        }
        assert data["action"] == "set"
        assert data["project"] == "Test"
        assert data["text"] == "Build a CLI app"
        assert data["domain"] == "codebase_build"

    def test_schema_has_all_required_fields(self):
        action = parse_goal_command("/goal set Build something")
        # Verify all fields are present
        assert hasattr(action, "action")
        assert hasattr(action, "project")
        assert hasattr(action, "text")
        assert hasattr(action, "domain")
        assert hasattr(action, "template_id")
        assert hasattr(action, "aliases")
        assert hasattr(action, "raw_parts")

    def test_chinese_and_english_share_same_schema(self):
        en = parse_goal_command("/goal set Build a CLI")
        zh = parse_goal_command("/目标 设定 构建CLI")
        assert isinstance(en, GoalActionSchema)
        assert isinstance(zh, GoalActionSchema)
        assert en.action == "set"
        assert zh.action == "set"

    def test_short_aliases_share_same_schema(self):
        short_result = parse_goal_command("/mb Build something")
        full_result = parse_goal_command("/goal set Build something")
        assert short_result.action == "set"
        assert full_result.action == "set"


class TestGoalSurfacesIntegration:
    def test_parser_is_importable_from_goals_module(self):
        import agent_runtime.goals
        assert hasattr(agent_runtime.goals, "parse_goal_command")
        assert hasattr(agent_runtime.goals, "GoalActionSchema")

    def test_compiler_is_importable_from_goals_module(self):
        import agent_runtime.goals
        assert hasattr(agent_runtime.goals, "compile_goal_set")
        assert hasattr(agent_runtime.goals, "compile_goal_plan")
        assert hasattr(agent_runtime.goals, "compile_goal_progress")
        assert hasattr(agent_runtime.goals, "compile_goal_validate")
        assert hasattr(agent_runtime.goals, "compile_goal_report")

    def test_templates_are_importable(self):
        import agent_runtime.goals
        assert hasattr(agent_runtime.goals, "TEMPLATES")
        assert hasattr(agent_runtime.goals, "get_template")

    def test_validation_is_importable(self):
        import agent_runtime.goals
        assert hasattr(agent_runtime.goals, "validate_goal_acceptance")
