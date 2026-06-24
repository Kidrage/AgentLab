from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

@dataclass
class AssistantModePolicy:
    allowed_intents: List[str]
    can_call_llm: bool
    can_modify_state: bool
    can_execute_tools: bool
    can_approve_actions: bool

@dataclass
class AssistantMode:
    name: str
    policy: AssistantModePolicy

@dataclass
class AssistantQuestion:
    mode: str
    project: str
    question: str

@dataclass
class AssistantGroundingSource:
    path: str
    reason: str

@dataclass
class AssistantStateSnapshot:
    project_id: str
    known: bool
    current_phase: str = ""
    phase_statuses: Dict[str, str] = field(default_factory=dict)
    blocked_items: List[str] = field(default_factory=list)
    pending_approvals: List[str] = field(default_factory=list)
    cost_summary: float = 0.0
    recent_events: List[str] = field(default_factory=list)
    acceptance_reports: List[str] = field(default_factory=list)
    recovery_events: List[str] = field(default_factory=list)
    route_decisions: List[str] = field(default_factory=list)
    worker_status: List[str] = field(default_factory=list)
    source_files: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

@dataclass
class AssistantAnswer:
    mode: str
    question: str
    answer: str
    grounding_sources: List[AssistantGroundingSource]
    warnings: List[str]
    confidence: str
    next_safe_action: Optional[str] = None
