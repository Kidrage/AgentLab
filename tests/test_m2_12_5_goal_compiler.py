import pytest
from agent_runtime.goals.compiler import compile_goal_set, compile_goal_plan
from agent_runtime.goals.action_schema import GoalActionSchema
from pathlib import Path

def test_goal_set_creates_contract(tmp_path):
    action = GoalActionSchema(command="/goal", action="set", text="build an app", project="TestProj")
    res = compile_goal_set(action, tmp_path)
    assert res.status == "ok"
    brain_dir = tmp_path / "projects" / "TestProj" / "project_brain"
    assert (brain_dir / "goal_contract.yml").exists()

def test_goal_plan_creates_artifacts(tmp_path):
    action_set = GoalActionSchema(command="/goal", action="set", text="build an app", project="TestProj")
    compile_goal_set(action_set, tmp_path)
    
    action_plan = GoalActionSchema(command="/goal", action="plan", project="TestProj")
    res = compile_goal_plan(action_plan, tmp_path)
    assert res.status == "ok"
    
    brain_dir = tmp_path / "projects" / "TestProj" / "project_brain"
    assert (brain_dir / "mission_contract.yml").exists()
    assert (brain_dir / "workflow_plan.yml").exists()
    assert (brain_dir / "mainline_program.yml").exists()
    assert (brain_dir / "mainline_acceptance_contract.yml").exists()
    assert (brain_dir / "scenario_validation_plan.yml").exists()

def test_goal_progress_report(tmp_path):
    action_set = GoalActionSchema(command="/goal", action="set", text="build an app", project="TestProj")
    compile_goal_set(action_set, tmp_path)
    compile_goal_plan(GoalActionSchema(action="plan", project="TestProj"), tmp_path)
    
    from agent_runtime.goals.progress import compile_goal_progress
    from agent_runtime.goals.report import compile_goal_report
    
    res_prog = compile_goal_progress(GoalActionSchema(action="progress", project="TestProj"), tmp_path)
    assert res_prog.status == "ok"
    
    res_rep = compile_goal_report(GoalActionSchema(action="report", project="TestProj"), tmp_path)
    assert res_rep.status == "ok"
    assert (tmp_path / "projects" / "TestProj" / "project_brain" / "mainline_completion_report.md").exists()
