"""Tests for M2-12.5 Goal Parser — deterministic command parsing with safety tripwires."""

import pytest
from agent_runtime.goals.parser import parse_goal_command


class TestParseEnglishCommands:
    def test_goal_raw_text_parses_as_set(self):
        action = parse_goal_command("/goal fix things")
        assert action.action == "set"
        assert action.text == "fix things"
        assert action.language == "en"

    def test_goal_set_explicit(self):
        action = parse_goal_command("/goal set Build a CLI app")
        assert action.action == "set"
        assert action.text == "Build a CLI app"

    def test_goal_plan_explicit(self):
        action = parse_goal_command("/goal plan MyProject")
        assert action.action == "plan"

    def test_goal_progress_explicit(self):
        action = parse_goal_command("/goal progress MyProject")
        assert action.action == "progress"

    def test_goal_validate_explicit(self):
        action = parse_goal_command("/goal validate MyProject")
        assert action.action == "validate"

    def test_goal_report_explicit(self):
        action = parse_goal_command("/goal report MyProject")
        assert action.action == "report"


class TestParseChineseCommands:
    def test_goal_chinese_raw_text_parses_as_set(self):
        action = parse_goal_command("/目标 修复 AgentLab M2 主线并验收")
        assert action.action == "set"
        assert action.text == "修复 AgentLab M2 主线并验收"
        assert action.language == "zh"

    def test_goal_chinese_set_with_action_word(self):
        action = parse_goal_command("/目标 设定 构建CLI应用")
        assert action.action == "set"
        assert "构建CLI应用" in action.text

    def test_goal_chinese_plan(self):
        action = parse_goal_command("/目标 计划 MyProject")
        assert action.action == "plan"

    def test_goal_chinese_progress(self):
        action = parse_goal_command("/目标 进度")
        assert action.action == "progress"


class TestParseShortAliases:
    def test_short_plan_chinese(self):
        action = parse_goal_command("/计划")
        assert action.action == "plan"

    def test_short_progress_chinese(self):
        action = parse_goal_command("/进度")
        assert action.action == "progress"

    def test_short_validate_chinese(self):
        action = parse_goal_command("/验收")
        assert action.action == "validate"

    def test_short_report_chinese(self):
        action = parse_goal_command("/报告")
        assert action.action == "report"


class TestParserSafety:
    def test_parser_does_not_call_subprocess(self, monkeypatch):
        import subprocess

        def fail(*args, **kwargs):
            raise AssertionError("goal parser must not call subprocess")

        monkeypatch.setattr(subprocess, "run", fail)
        action = parse_goal_command("/目标 修复 AgentLab M2 主线并验收")
        assert action.action == "set"
        assert "AgentLab M2" in action.text
