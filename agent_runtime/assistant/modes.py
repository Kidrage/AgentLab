from .models import AssistantMode, AssistantModePolicy

MODES = {
    "operator": AssistantMode(
        name="operator",
        policy=AssistantModePolicy(
            allowed_intents=[
                "explain_project_status",
                "explain_blockers",
                "explain_pending_approvals",
                "explain_cost_status",
                "explain_next_safe_action"
            ],
            can_call_llm=True,
            can_modify_state=False,
            can_execute_tools=False,
            can_approve_actions=False,
        )
    ),
    "planner": AssistantMode(
        name="planner",
        policy=AssistantModePolicy(
            allowed_intents=[
                "explain_roadmap",
                "explain_phase_plan",
                "suggest_next_task_packet"
            ],
            can_call_llm=True,
            can_modify_state=False,
            can_execute_tools=False,
            can_approve_actions=False,
        )
    ),
    "reviewer": AssistantMode(
        name="reviewer",
        policy=AssistantModePolicy(
            allowed_intents=[
                "explain_acceptance_verdict",
                "explain_failed_gate",
                "explain_retry_or_redesign_reason"
            ],
            can_call_llm=True,
            can_modify_state=False,
            can_execute_tools=False,
            can_approve_actions=False,
        )
    ),
    "teacher": AssistantMode(
        name="teacher",
        policy=AssistantModePolicy(
            allowed_intents=[
                "explain_routing_decision",
                "explain_worker_choice",
                "explain_cost_policy",
                "explain_recovery_policy",
                "explain_system_behavior"
            ],
            can_call_llm=True,
            can_modify_state=False,
            can_execute_tools=False,
            can_approve_actions=False,
        )
    )
}

def get_mode(mode_name: str) -> AssistantMode:
    if mode_name not in MODES:
        raise ValueError(f"Unknown assistant mode: {mode_name}")
    return MODES[mode_name]
