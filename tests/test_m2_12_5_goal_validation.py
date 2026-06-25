from agent_runtime.goals.validation import compile_goal_validate
from agent_runtime.goals.action_schema import GoalActionSchema
from agent_runtime.goals.compiler import compile_goal_set, compile_goal_plan

def test_missing_evidence_blocks_acceptance(tmp_path):
    action_set = GoalActionSchema(command="/goal", action="set", text="build an app", project="TestProj")
    compile_goal_set(action_set, tmp_path)
    compile_goal_plan(GoalActionSchema(action="plan", project="TestProj"), tmp_path)
    
    res = compile_goal_validate(GoalActionSchema(action="validate", project="TestProj"), tmp_path)
    assert res.status == "ok"
    assert "acceptance_history.yml" in res.artifacts
