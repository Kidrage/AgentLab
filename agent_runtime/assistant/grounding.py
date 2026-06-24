from .models import AssistantQuestion, AssistantAnswer, AssistantStateSnapshot, AssistantGroundingSource
from .state_reader import read_project_state
from .modes import get_mode
from agent_runtime.llm_provider import generate_text, resolve_llm_settings
from agent_runtime.config_loader import load_agentlab_configs

def answer_question(question: AssistantQuestion) -> AssistantAnswer:
    mode = get_mode(question.mode)
    
    snapshot = read_project_state(question.project)
    
    if not snapshot.known:
        return AssistantAnswer(
            mode=question.mode,
            question=question.question,
            answer="The information is unavailable from current project state. (Project not found)",
            grounding_sources=[],
            warnings=snapshot.warnings,
            confidence="none"
        )
        
    # Format state for LLM
    state_context = f"Project: {snapshot.project_id}\n"
    state_context += f"Cost: ${snapshot.cost_summary}\n"
    state_context += f"Phase Statuses: {snapshot.phase_statuses}\n"
    
    from agent_runtime.run_task import _PROJECT_ROOT
    configs = load_agentlab_configs(_PROJECT_ROOT)
    settings = resolve_llm_settings(
        agent_name="Supervisor",
        agent_registry=configs.get("agents", {}),
        model_providers=configs.get("model_providers", {}),
        model_profiles=configs.get("model_profiles", {}),
    )
    
    system_prompt = (
        f"You are the AgentLab Assistant operating in '{mode.name}' mode. "
        "You MUST NOT hallucinate or guess. Use ONLY the provided project state summary. "
        "If the answer is not in the state summary, say so clearly. "
    )
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Project State Summary:\n{state_context}\n\nQuestion: {question.question}"}
    ]
    
    try:
        result = generate_text(settings, configs.get("model_providers", {}), messages)
        answer_text = result.content
        confidence = "high"
    except Exception as e:
        answer_text = "The LLM provider is unavailable. Using deterministic fallback."
        confidence = "low"
        
    grounding = [AssistantGroundingSource(path=src, reason="State source") for src in snapshot.source_files]
    if not grounding:
        answer_text = "The information is unavailable from current project state."
        confidence = "none"
        
    return AssistantAnswer(
        mode=question.mode,
        question=question.question,
        answer=answer_text,
        grounding_sources=grounding,
        warnings=snapshot.warnings,
        confidence=confidence,
        next_safe_action="Inspect the dashboard" if mode.name == "operator" else None
    )
