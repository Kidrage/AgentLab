from __future__ import annotations

import dataclasses
from datetime import datetime
from typing import Any, Dict, Optional

@dataclasses.dataclass
class Event:
    """
    Unified observability event covering mission, routing, worker assignment, 
    cost, approvals, execution, evidence, acceptance, and recovery.
    """
    event_id: str
    event_type: str  # e.g., 'worker_assigned', 'cost_estimated', 'approval_requested'
    timestamp: str   # ISO 8601 format
    project_id: str
    details: Dict[str, Any]
    
    # Optional correlation contexts
    source: str = "system"
    user_id: Optional[str] = None
    worker_id: Optional[str] = None
    task_id: Optional[str] = None
    role_id: Optional[str] = None
    cost_usd: Optional[float] = None
    schema_version: str = "m2.7.1"
    
    def __post_init__(self):
        validate_event_type(self.event_type)
        if not self.timestamp:
            raise ValueError("timestamp must be present")
        if not self.project_id:
            raise ValueError("project_id must be present")
        if not isinstance(self.details, dict):
            raise ValueError("details must be a dict")
        if self.cost_usd is not None and (not isinstance(self.cost_usd, (int, float)) or self.cost_usd < 0):
            raise ValueError("cost_usd must be numeric and non-negative")
            
    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)
        
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Event:
        return cls(**data)

def validate_event_type(event_type: str) -> None:
    if event_type not in VALID_EVENT_TYPES:
        raise ValueError(f"Unknown event type: {event_type}")

# Valid event types defined in M2-7 spec
VALID_EVENT_TYPES = {
    "mission_compiled",
    "worker_detected",
    "worker_auditioned",
    "role_assigned",
    "route_decision_created",
    "approval_requested",
    "approval_accepted",
    "approval_rejected",
    "task_packet_created",
    "executor_started",
    "executor_finished",
    "artifact_created",
    "evidence_collected",
    "cost_estimated",
    "cost_recorded",
    "phase_accepted",
    "phase_retried",
    "recovery_planned",
    "config_changed",
    "ui_action"
}
