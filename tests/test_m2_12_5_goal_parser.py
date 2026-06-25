"""Tests for M2-12.5 Goal Parser — deterministic command parsing."""

from __future__ import annotations

import pytest

from agent_runtime.goals.parser import (
    GoalActionSchema,
    _infer_domain,
    _resolve_action,
    parse_goal_command,
)


class TestActionResolution:
    def test_english_goal_set(self):
        assert _resolve_action("/goal set") == "set"
        assert _resolve_action("/goal plan") == "plan"
        assert _resolve_action("/goal progress") == "progress"
        assert _resolve_action("/goal validate") == "validate"
        assert _resolve_action("/goal report") == "report"

    def test_chinese_goal_set(self):
        assert _resolve_action("/目标 set") == "set"
        assert _resolve_action("/目标 plan") == "plan"

    def test_bare_english_actions(self):
        assert _resolve_action("set") == "set"
        assert _resolve_action("plan") == "plan"
        assert _resolve_action("validate") == "validate"
        assert _resolve_action("report") == "report"

    def test_bare_chinese_actions(self):
        assert _resolve_action("目标") == "set"
        assert _resolve_action("计划") == "plan"
        assert _resolve_action("验证") == "validate"
        assert _resolve_action("报告") == "report"

    def test_default_is_set(self):
        assert _resolve_action("") == "set"
        assert _resolve_action("unknown gibberish") == "set"

    def test_short_aliases(self):
        assert _resolve_action("/mb") == "set"
        assert _resolve_action("/jh") == "plan"
        assert _resolve_action("/jz") == "progress"
        assert _resolve_action("/yz") == "validate"
        assert _resolve_action("/bg") == "report"


class TestDomainInference:
    def test_codebase_domain(self):
        assert _infer_domain("I want to build a Python CLI app") == "codebase_build"

    def test_longform_domain(self):
        assert _infer_domain("Write a science fiction novel series") == "longform_creation"

    def test_research_domain(self):
        assert _infer_domain("Conduct a systematic literature review") == "research_archive"

    def test_video_domain(self):
        assert _infer_domain("Create a YouTube video series about computing") == "video_generation"

    def test_document_domain(self):
        assert _infer_domain("Build a knowledge base from technical documents") == "document_knowledgebase"

    def test_local_automation_domain(self):
        assert _infer_domain("Automate my file organization workflow") == "local_automation"

    def test_unknown_falls_back(self):
        assert _infer_domain("") == "unknown_large_project"
        assert _infer_domain("xyzzy foobar blarg") == "unknown_large_project"


class TestParseGoalCommand:
    def test_parse_english_goal(self):
        result = parse_goal_command("/goal set Build a CLI app")
        assert isinstance(result, GoalActionSchema)
        assert result.action == "set"
        assert "Build a CLI app" in result.text
        assert result.domain != ""

    def test_parse_chinese_goal(self):
        result = parse_goal_command("/目标 设定 构建一个CLI应用")
        assert isinstance(result, GoalActionSchema)
        assert result.action == "set"
        assert "构建一个CLI应用" in result.text

    def test_parse_extracts_project(self):
        result = parse_goal_command("/goal set Build app --project MyProject")
        assert result.project == "MyProject"

    def test_parse_without_project(self):
        result = parse_goal_command("/goal set Build app")
        assert result.project == ""

    def test_parse_bare_text(self):
        result = parse_goal_command("I want to write a novel")
        assert result.action == "set"
        assert "I want to write a novel" in result.text

    def test_parse_plan_command(self):
        result = parse_goal_command("/goal plan MyProject")
        assert result.action == "plan"

    def test_parse_progress_command(self):
        result = parse_goal_command("/goal progress MyProject")
        assert result.action == "progress"

    def test_parse_validate_command(self):
        result = parse_goal_command("/goal validate MyProject")
        assert result.action == "validate"

    def test_parse_report_command(self):
        result = parse_goal_command("/goal report MyProject")
        assert result.action == "report"

    def test_parse_short_chinese_alias(self):
        result = parse_goal_command("/mb 修复AgentLab")
        assert result.action == "set"
        assert "修复AgentLab" in result.text

    def test_parse_short_validate_alias(self):
        result = parse_goal_command("/yz MyProject")
        assert result.action == "validate"
