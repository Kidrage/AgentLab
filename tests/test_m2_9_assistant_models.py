import pytest
from agent_runtime.assistant.models import (
    AssistantMode, AssistantModePolicy, AssistantQuestion,
    AssistantAnswer, AssistantGroundingSource, AssistantStateSnapshot
)

def test_assistant_models():
    policy = AssistantModePolicy(allowed_intents=["explain_project_status"], can_call_llm=True, can_modify_state=False, can_execute_tools=False, can_approve_actions=False)
    mode = AssistantMode(name="operator", policy=policy)
    assert mode.name == "operator"
    assert mode.policy.can_call_llm is True
    assert mode.policy.can_approve_actions is False

def test_assistant_question():
    q = AssistantQuestion(mode="operator", project="Demo", question="What's up?")
    assert q.mode == "operator"

def test_assistant_snapshot():
    snapshot = AssistantStateSnapshot(project_id="Demo", known=True)
    assert snapshot.project_id == "Demo"
    assert snapshot.cost_summary == 0.0

def test_assistant_answer():
    a = AssistantAnswer(
        mode="operator",
        question="Q",
        answer="A",
        grounding_sources=[],
        warnings=["No sources"],
        confidence="none"
    )
    assert a.answer == "A"
