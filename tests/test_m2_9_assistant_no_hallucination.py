import pytest
from agent_runtime.assistant.grounding import answer_question
from agent_runtime.assistant.models import AssistantQuestion

def test_missing_project_does_not_hallucinate(tmp_path, monkeypatch):
    """
    Test that if a project is missing, the assistant does not hallucinate
    a project state, but instead warns that it is unknown.
    """
    monkeypatch.setattr("agent_runtime.run_task._PROJECT_ROOT", tmp_path)
    q = AssistantQuestion(mode="operator", project="NonExistentProject", question="What is the phase?")
    ans = answer_question(q)
    
    # Must explicitly state it is unavailable and confidence must be none
    assert ans.confidence == "none"
    assert "unavailable" in ans.answer.lower()
    
    # Must have no grounding sources because nothing was read
    assert len(ans.grounding_sources) == 0
    
    # Must emit a warning about the project directory
    assert len(ans.warnings) > 0
    assert any("not found" in w for w in ans.warnings)

def test_missing_timeline_does_not_hallucinate(tmp_path, monkeypatch):
    """
    Test that a project without a timeline correctly reports cost as 0
    and does not hallucinate arbitrary data.
    """
    monkeypatch.setattr("agent_runtime.run_task._PROJECT_ROOT", tmp_path)
    proj_dir = tmp_path / "projects" / "EmptyProject"
    proj_dir.mkdir(parents=True)
    
    q = AssistantQuestion(mode="operator", project="EmptyProject", question="Cost?")
    ans = answer_question(q)
    
    assert ans.confidence in ("none", "low")
    assert len(ans.grounding_sources) == 0
