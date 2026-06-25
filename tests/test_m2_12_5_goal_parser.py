import pytest
from agent_runtime.goals.parser import parse_goal_command

def test_goal_raw_text_parses_as_set():
    action = parse_goal_command("/goal fix things")
    assert action.action == "set"
    assert action.text == "fix things"
    assert action.language == "en"

def test_goal_chinese_raw_text_parses_as_set():
    action = parse_goal_command("/目标 修复 AgentLab M2 主线并验收")
    assert action.action == "set"
    assert action.text == "修复 AgentLab M2 主线并验收"
    assert action.language == "zh"
    
def test_goal_status_maps_to_canonical():
    action = parse_goal_command("/goal status")
    assert action.action == "status"

def test_goal_chinese_progress_maps_to_canonical():
    action = parse_goal_command("/目标 进度")
    assert action.action == "progress"

def test_goal_short_chinese_validate_maps_to_canonical():
    action = parse_goal_command("/验收")
    assert action.action == "validate"

def test_unknown_command_returns_blocked():
    action = parse_goal_command("/foo bar")
    assert action.status == "error"

def test_parser_does_not_call_subprocess(monkeypatch):
    import subprocess
    def fail(*args, **kwargs):
        raise AssertionError("goal parser must not call subprocess")
    monkeypatch.setattr(subprocess, "run", fail)
    action = parse_goal_command("/目标 修复 AgentLab M2 主线并验收")
    assert action.action == "set"
