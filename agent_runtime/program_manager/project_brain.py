from __future__ import annotations

from pathlib import Path

import yaml

from agent_runtime.atomic_io import atomic_write_text, atomic_write_yaml
from agent_runtime.program_manager.context_compressor import write_phase_summary, write_snapshot
from agent_runtime.program_manager.milestone import build_milestone_graph
from agent_runtime.program_manager.phase_planner import build_phase_plan
from agent_runtime.program_manager.project_brief import build_project_brief_data
from agent_runtime.program_manager.project_goal import load_mission_contract
from agent_runtime.program_manager.replanner import recommend_next_action
from agent_runtime.program_manager.roadmap import build_roadmap


def build_project_brain(
    mission_contract_path: Path,
    project: str,
    out_dir: Path,
    workflow_plan_path: Path | None = None,
) -> dict:
    contract = load_mission_contract(mission_contract_path)
    brief = build_project_brief_data(project, contract)

    workflow_plan = {}
    if workflow_plan_path and workflow_plan_path.exists():
        try:
            workflow_plan = yaml.safe_load(workflow_plan_path.read_text(encoding="utf-8")) or {}
        except Exception:
            pass
    
    if not workflow_plan and workflow_plan_path is not None:
        from agent_runtime.project_workflows.planner import create_project_workflow_plan
        agentlab_root = Path(__file__).resolve().parents[2]
        try:
            workflow_plan_obj = create_project_workflow_plan(
                mission_contract_path=mission_contract_path,
                agentlab_root=agentlab_root,
                project_id=project,
            )
            if hasattr(workflow_plan_obj, "model_dump"):
                workflow_plan = workflow_plan_obj.model_dump()
            else:
                workflow_plan = workflow_plan_obj.dict()
        except Exception:
            pass

    if workflow_plan and "phases" in workflow_plan:
        milestones = []
        for i, phase in enumerate(workflow_plan["phases"]):
            milestones.append({
                "milestone_id": f"m{i + 1}",
                "phase_id": phase.get("phase_id", f"phase_{i + 1:02d}"),
                "title": phase.get("title", ""),
                "goal": phase.get("goal", ""),
                "status": "planned",
                "expected_artifacts": phase.get("expected_artifacts", []),
                "acceptance_gates": phase.get("acceptance_gates", []),
                "must_read_artifacts": phase.get("must_read_artifacts", []),
                "missing_facts": phase.get("missing_facts", []),
                "plan_status": phase.get("plan_status", "draft"),
                "self_check": phase.get("self_check", {}),
                "revision_log": phase.get("revision_log", []),
            })
        roadmap = {
            "project": project,
            "task_type": contract.get("task_type", "unknown"),
            "milestones": milestones,
            "no_direct_execution": True,
            "acceptance_required_before_next_phase": True,
        }
    else:
        roadmap = build_roadmap(brief)

    graph = build_milestone_graph(roadmap)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "phase_summaries").mkdir(exist_ok=True)
    (out_dir / "snapshots").mkdir(exist_ok=True)
    atomic_write_text(out_dir / "product_vision.md", _render_product_vision(brief))
    atomic_write_yaml(out_dir / "project_brief.yml", brief)
    atomic_write_yaml(out_dir / "roadmap.yml", roadmap)
    atomic_write_yaml(out_dir / "milestone_graph.yml", graph)
    atomic_write_yaml(out_dir / "decision_log.yml", {"entries": []})
    atomic_write_yaml(out_dir / "acceptance_history.yml", {"entries": []})
    atomic_write_yaml(out_dir / "unresolved_questions.yml", {"questions": []})
    atomic_write_yaml(out_dir / "known_risks.yml", {"risks": brief.get("risk_flags", [])})
    atomic_write_yaml(out_dir / "architecture_state.yml", {"state": "planned", "modules": []})
    
    # Write current_phase.yml
    milestones_list = roadmap.get("milestones") or []
    first_phase_id = milestones_list[0]["phase_id"] if milestones_list else "phase_01"
    current_phase = {
        "phase_id": first_phase_id,
        "status": "planned"
    }
    atomic_write_yaml(out_dir / "current_phase.yml", current_phase)
    
    # Write phase_plan.yml
    first_phase = build_phase_plan(brief, roadmap, first_phase_id)
    atomic_write_yaml(out_dir / "phase_plan.yml", first_phase)

    next_actions = recommend_next_action({"entries": []}, roadmap)
    atomic_write_yaml(out_dir / "next_actions.yml", next_actions)
    write_snapshot(out_dir, "initial", {"project_brief": brief, "roadmap": roadmap})
    return {"ok": True, "project_brain_dir": str(out_dir), "next_action": next_actions}


def build_project_plan(project_brain_dir: Path, out_dir: Path, phase_id: str | None = None) -> dict:
    brief = yaml.safe_load((project_brain_dir / "project_brief.yml").read_text(encoding="utf-8")) or {}
    roadmap = yaml.safe_load((project_brain_dir / "roadmap.yml").read_text(encoding="utf-8")) or {}
    phase = build_phase_plan(brief, roadmap, phase_id=phase_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_yaml(out_dir / "phase_plan.yml", phase)
    atomic_write_yaml(out_dir / "roadmap.yml", roadmap)
    write_phase_summary(
        project_brain_dir,
        str(phase.get("phase_id")),
        {"verdict": "planned", "outputs": phase.get("outputs"), "next_action": "executor_task_create"},
    )
    return phase


def build_project_next_actions(project_brain_dir: Path, out_dir: Path) -> dict:
    roadmap = yaml.safe_load((project_brain_dir / "roadmap.yml").read_text(encoding="utf-8")) or {}
    history_path = project_brain_dir / "acceptance_history.yml"
    history = yaml.safe_load(history_path.read_text(encoding="utf-8")) if history_path.exists() else {"entries": []}
    next_actions = recommend_next_action(history or {"entries": []}, roadmap)
    out_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_yaml(out_dir / "next_actions.yml", next_actions)
    atomic_write_yaml(project_brain_dir / "next_actions.yml", next_actions)
    return next_actions


def _render_product_vision(brief: dict) -> str:
    return "\n".join(
        [
            f"# Product Vision: {brief.get('project')}",
            "",
            f"- task_type: {brief.get('task_type')}",
            f"- user_goal: {brief.get('user_goal')}",
            f"- intent_summary: {brief.get('intent_summary')}",
            "",
            "AgentLab should plan, produce evidence, accept phases, and preserve recoverable context.",
            "It must not directly execute long-running work without phase-level approval.",
        ]
    ) + "\n"
