import dataclasses
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any

@dataclass
class GoalContract:
    goal_id: str
    project: str
    raw_requirement: str
    compiled_template: str
    created_at: str
    status: str = "active"

@dataclass
class MissionContract:
    goal_id: str
    mission_statement: str

@dataclass
class WorkflowPlan:
    goal_id: str
    stages: List[str]

@dataclass
class MainlineStage:
    stage_id: str
    status: str = "pending"
    blocks_m2_closure: bool = True
    required_artifacts: List[str] = field(default_factory=list)
    required_evidence: List[str] = field(default_factory=list)
    acceptance_gates: List[str] = field(default_factory=list)

@dataclass
class MainlineProgram:
    goal_id: str
    template_id: str
    series: List[str] = field(default_factory=list)
    stages: List[MainlineStage] = field(default_factory=list)

@dataclass
class MainlineAcceptanceContract:
    goal_id: str
    acceptance_criteria: List[str] = field(default_factory=list)

@dataclass
class ScenarioValidationPlan:
    goal_id: str
    scenarios: List[Dict[str, Any]] = field(default_factory=list)

@dataclass
class MainlineProgress:
    goal_id: str
    completed_stages: List[str] = field(default_factory=list)
    pending_stages: List[str] = field(default_factory=list)
    blocked_stages: List[str] = field(default_factory=list)

@dataclass
class GoalCommandResult:
    status: str
    artifacts: List[str]
    message: str
