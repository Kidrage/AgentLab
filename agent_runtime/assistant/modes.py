from agent_runtime.llm_provider import generate_text, resolve_llm_settings
from agent_runtime.config_loader import load_agentlab_configs
import yaml
import json

def handle_ask(project: str, question: str) -> str:
    from agent_runtime.run_task import _PROJECT_ROOT
    project_dir = _PROJECT_ROOT / "projects" / project
    tasks_dir = project_dir / "tasks"
    
    # Gather state summary
    state_summary = f"Project: {project}\n\n"
    
    # Collect all phases
    if tasks_dir.exists():
        for phase_dir in tasks_dir.iterdir():
            if not phase_dir.is_dir():
                continue
            state_path = phase_dir / "state.yml"
            if state_path.exists():
                try:
                    state_data = yaml.safe_load(state_path.read_text()) or {}
                    state_summary += f"Phase [{phase_dir.name}]:\n"
                    state_summary += f"  Status: {state_data.get('status', 'unknown')}\n"
                    state_summary += f"  Last Event: {state_data.get('last_event', 'none')}\n"
                except Exception:
                    pass
    
    # Cost
    timeline_path = project_dir / "observability" / "timeline.jsonl"
    total_cost = 0.0
    if timeline_path.exists():
        with open(timeline_path, "r") as f:
            for line in f:
                if not line.strip(): continue
                try:
                    event = json.loads(line)
                    if event.get("event_type") == "cost_estimated":
                        total_cost += float(event.get("cost_usd", 0.0))
                except Exception:
                    pass
    state_summary += f"\nTotal Accumulated Cost: ${total_cost:.4f}\n"
    
    # Call LLM
    configs = load_agentlab_configs(_PROJECT_ROOT)
    settings = resolve_llm_settings(
        agent_name="Supervisor",  # Use Supervisor's profile for the assistant
        agent_registry=configs.get("agents", {}),
        model_providers=configs.get("model_providers", {}),
        model_profiles=configs.get("model_profiles", {}),
    )
    
    system_prompt = (
        "You are the AgentLab Assistant. Your job is to answer questions about the current project state. "
        "You MUST NOT hallucinate or guess. Use ONLY the provided project state summary. "
        "If the answer is not in the state summary, say so clearly. "
        "Cite the specific phase or metric from the state when answering."
    )
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Project State Summary:\n{state_summary}\n\nQuestion: {question}"}
    ]
    
    try:
        result = generate_text(settings, configs.get("model_providers", {}), messages)
        return result.content
    except Exception as e:
        return f"Error communicating with LLM provider: {e}"
