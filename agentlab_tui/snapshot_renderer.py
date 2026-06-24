from typing import Optional
from agent_runtime.assistant.state_reader import read_project_state
from agent_runtime.assistant.grounding import answer_question
from agent_runtime.assistant.models import AssistantQuestion

def render_tui_snapshot(project: Optional[str] = None, view: str = "overview") -> str:
    """Render a text snapshot of the requested view for headless testing."""
    if not project:
        return f"=== AgentLab TUI Headless Snapshot ===\nView: {view}\nProject: [None selected]\n"
        
    state = read_project_state(project)
    
    # Bridge to M2-9 to get next safe action and warnings
    operator_q = AssistantQuestion(mode="operator", project=project, question="What is the next safe action?")
    operator_ans = answer_question(operator_q)
    
    output = []
    output.append(f"=== AgentLab TUI Headless Snapshot ===")
    output.append(f"Project: {project} (Known: {state.known})")
    output.append(f"View: {view}")
    
    if view == "overview":
        output.append(f"Phase: {state.current_phase}")
        output.append(f"Cost: ${state.cost_summary}")
        output.append(f"Next Safe Action: {operator_ans.next_safe_action}")
    elif view == "tasks":
        output.append(f"Blocked Items: {state.blocked_items}")
    elif view == "workers":
        output.append("Worker Registry: (Not loaded in skeleton)")
    elif view == "costs":
        output.append(f"Total Cost: ${state.cost_summary}")
    elif view == "approvals":
        output.append(f"Pending Approvals: {state.pending_approvals}")
    elif view == "recovery":
        output.append(f"Recovery Events: {state.recovery_events}")
    elif view == "routes":
        output.append(f"Route Decisions: {state.route_decisions}")
    else:
        output.append(f"Unknown view: {view}")
        
    if state.warnings or operator_ans.warnings:
        output.append("\nWarnings:")
        for w in set(state.warnings + operator_ans.warnings):
            output.append(f" - {w}")
            
    return "\n".join(output)
