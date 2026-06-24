import yaml
from pathlib import Path

def explain_route(decision_path: Path) -> str:
    if not decision_path.exists():
        return f"Decision file {decision_path} not found."
        
    try:
        data = yaml.safe_load(decision_path.read_text()) or {}
    except yaml.YAMLError as exc:
        return f"Error reading decision file: {exc}"
        
    # The decision file might be a single decision or a list/dict of decisions.
    # In M2-7/8 it's typically a route_plan with a list of decisions.
    plan = data.get("route_plan", data)
    decisions = plan.get("decisions", [])
    
    if not decisions:
        # Maybe it's a direct dictionary format
        decisions = [data]
        
    explanation = f"# Route Explanation from {decision_path.name}\n\n"
    
    for idx, d in enumerate(decisions):
        role = d.get("role", "unknown")
        selected = d.get("selected_worker", "none")
        profile = d.get("route_profile", "unknown")
        rejected = d.get("rejected_alternatives", [])
        
        explanation += f"## Role: {role}\n"
        explanation += f"**Selected Worker**: {selected}\n"
        explanation += f"**Route Profile**: {profile}\n"
        
        if rejected:
            explanation += "**Rejected Alternatives**:\n"
            for alt in rejected:
                worker_id = alt.get("worker_id", "unknown")
                reason = alt.get("reason", "unknown")
                explanation += f"- {worker_id}: {reason}\n"
        else:
            explanation += "_No alternatives were evaluated or rejected._\n"
            
        explanation += "\n"
        
    return explanation
