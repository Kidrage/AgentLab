import pytest
from agent_runtime.assistant.modes import get_mode

def test_get_operator_mode():
    mode = get_mode("operator")
    assert mode.name == "operator"
    assert "explain_project_status" in mode.policy.allowed_intents

def test_get_planner_mode():
    mode = get_mode("planner")
    assert mode.name == "planner"

def test_get_reviewer_mode():
    mode = get_mode("reviewer")
    assert mode.name == "reviewer"

def test_get_teacher_mode():
    mode = get_mode("teacher")
    assert mode.name == "teacher"

def test_unknown_mode():
    with pytest.raises(ValueError):
        get_mode("unknown")
