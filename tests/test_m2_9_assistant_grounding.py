import pytest
from agent_runtime.assistant.grounding import answer_question
from agent_runtime.assistant.models import AssistantQuestion

def test_grounding_known_project(tmp_path, monkeypatch):
    monkeypatch.setattr("agent_runtime.run_task._PROJECT_ROOT", tmp_path)
    # create fake project
    proj_dir = tmp_path / "projects" / "Demo"
    proj_dir.mkdir(parents=True)
    
    q = AssistantQuestion(mode="operator", project="Demo", question="Cost?")
    a = answer_question(q)
    assert "deterministic fallback" in a.answer or a.confidence == "none"

def test_operator_cannot_execute():
    from agent_runtime.assistant.modes import get_mode
    mode = get_mode("operator")
    assert mode.policy.can_execute_tools is False
    assert mode.policy.can_approve_actions is False
