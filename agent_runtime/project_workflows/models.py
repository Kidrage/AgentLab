from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

class PhasePlan(BaseModel):
    phase_id: str
    title: str
    goal: str
    required_inputs: List[str] = Field(default_factory=list)
    expected_outputs: List[str] = Field(default_factory=list)
    expected_artifacts: List[str] = Field(default_factory=list)
    required_capabilities: List[str] = Field(default_factory=list)
    recommended_skills: List[str] = Field(default_factory=list)
    recommended_executors: List[str] = Field(default_factory=list)
    acceptance_gates: List[str] = Field(default_factory=list)
    human_decision_points: List[str] = Field(default_factory=list)
    failure_recovery: List[str] = Field(default_factory=list)
    asset_registry_updates: List[str] = Field(default_factory=list)
    next_phase_conditions: List[str] = Field(default_factory=list)
    must_read_artifacts: List[str] = Field(default_factory=list)
    missing_facts: List[Dict[str, Any]] = Field(default_factory=list)
    plan_status: str = "draft"
    self_check: Dict[str, Any] = Field(default_factory=dict)
    revision_log: List[Dict[str, Any]] = Field(default_factory=list)
    artifact_intent: Dict[str, Any] = Field(default_factory=dict)

class ProjectWorkflowPlan(BaseModel):
    project_id: Optional[str] = None
    template_id: str
    project_type: str
    mission_contract_path: str
    phases: List[PhasePlan] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    decision_points: List[str] = Field(default_factory=list)
