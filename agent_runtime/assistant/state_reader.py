import json
from pathlib import Path
import yaml

def explain_phase(project: str, phase: str) -> str:
    from agent_runtime.run_task import _PROJECT_ROOT
    project_dir = _PROJECT_ROOT / "projects" / project
    task_dir = project_dir / "tasks" / phase
    state_path = task_dir / "state.yml"
    plan_path = task_dir / "workflow_plan.yml"
    
    if not state_path.exists():
        return f"Could not find state for phase '{phase}' in project '{project}'. Path {state_path} does not exist."
    
    state_data = yaml.safe_load(state_path.read_text()) or {}
    
    status = state_data.get("status", "unknown")
    current_agent = state_data.get("current_agent", "none")
    last_event = state_data.get("last_event", "none")
    
    explanation = f"# Phase Explanation: {phase}\n\n"
    explanation += f"**Status**: {status}\n"
    explanation += f"**Current Agent**: {current_agent}\n"
    explanation += f"**Last Event**: {last_event}\n\n"
    
    if plan_path.exists():
        plan_data = yaml.safe_load(plan_path.read_text()) or {}
        route = plan_data.get("route", {})
        if route:
            explanation += "**Planned Agents**:\n"
            for agent in route.get("agents", []):
                explanation += f"- {agent}\n"
    else:
        explanation += "_No workflow_plan.yml found._\n"
        
    return explanation

def explain_cost(project: str) -> str:
    from agent_runtime.run_task import _PROJECT_ROOT
    project_dir = _PROJECT_ROOT / "projects" / project
    timeline_path = project_dir / "observability" / "timeline.jsonl"
    
    if not timeline_path.exists():
        return f"No cost records found for project '{project}'. Timeline {timeline_path} does not exist."
        
    total_cost = 0.0
    cost_events = []
    
    with open(timeline_path, "r") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                event = json.loads(line)
                if event.get("event_type") == "cost_estimated":
                    cost = float(event.get("cost_usd", 0.0))
                    total_cost += cost
                    cost_events.append(event)
            except Exception:
                pass
                
    explanation = f"# Cost Explanation: {project}\n\n"
    explanation += f"**Total Estimated Cost (USD)**: ${total_cost:.4f}\n\n"
    if cost_events:
        explanation += "### Breakdown by task:\n"
        for evt in cost_events:
            explanation += f"- Task {evt.get('task_id', 'unknown')}: ${evt.get('cost_usd', 0.0):.4f}\n"
            
    return explanation
