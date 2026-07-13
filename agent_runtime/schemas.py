"""Pydantic model skeletons for AgentLab task reports."""

from typing import Literal, Optional
from pydantic import BaseModel, Field


AgentName = Literal[
    "Supervisor",
    "RepoScout",
    "Researcher",
    "Observer",
    "InterfaceMapper",
    "Coder",
    "ArtifactProducer",
    "Writer",
    "Reviewer",
    "Scribe",
    "PromptEngineer",
    "TesterAuditor",
    "Archivist",
    "Verifier",
]


ExecutionBackend = Literal["codex", "qwen", "langgraph", "codex_full_driver"]


class TaskRunRequest(BaseModel):
    project: str
    task_id: str
    user_request_path: Optional[str] = None
    run_dir: Optional[str] = None
    execution_backend: ExecutionBackend = "codex"
    recommended_route: list[AgentName] = Field(default_factory=list)


class TokenBudget(BaseModel):
    phase: str
    estimated_input_tokens: int = 0
    estimated_output_tokens: int = 0
    estimated_total_tokens: int = 0
    warning_threshold_tokens: int = 0
    stop_threshold_tokens: int = 0
    actual_tokens: Optional[int] = None
    variance_tokens: Optional[int] = None
    notes: str = ""


class AgentReport(BaseModel):
    task_id: str
    agent_name: str
    status: Literal["draft", "complete", "blocked"] = "draft"
    summary: str = ""
    files_read: list[str] = Field(default_factory=list)
    files_changed: list[str] = Field(default_factory=list)
    commands_run: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    token_budgets: list[TokenBudget] = Field(default_factory=list)


class AgentRoute(BaseModel):
    task_size: Literal["small", "medium", "large"]
    agents: list[AgentName]
    rationale: list[str] = Field(default_factory=list)
    skipped_agents: list[AgentName] = Field(default_factory=list)
    route_key: str = "small_task"


class AiderInvocationPlan(BaseModel):
    enabled: bool = False
    repo_path: str
    command: list[str] = Field(default_factory=list)
    read_only_context: list[str] = Field(default_factory=list)
    editable_files: list[str] = Field(default_factory=list)
    message_file: Optional[str] = None
    missing_inputs: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class WorkflowPlan(BaseModel):
    project: str
    task_id: str
    agentlab_root: str
    project_root: str
    repo_path: str
    run_dir: str
    user_request_path: str
    execution_backend: ExecutionBackend = "codex"
    budget_mode: str = "balanced"
    budget_profile: str = ""
    project_size: str = "L2"
    risk_level: str = "R1"
    route: AgentRoute
    token_budgets: list[TokenBudget] = Field(default_factory=list)
    included_agents: dict[str, dict] = Field(default_factory=dict)
    model_profiles: dict[str, dict] = Field(default_factory=dict)
    validation_gates: list[dict] = Field(default_factory=list)
    skills: dict = Field(default_factory=dict)
    memory_policy: dict = Field(default_factory=dict)
    execution_policy: dict = Field(default_factory=dict)
    harness_policy: dict = Field(default_factory=dict)
    harness_status: dict = Field(default_factory=dict)
    mission_contract: dict = Field(default_factory=dict, exclude=True)
    long_project_governance: dict = Field(default_factory=dict)
    artifact_intent: dict = Field(default_factory=dict)
    production_pack: dict = Field(default_factory=dict)
    missing_inputs: list[str] = Field(default_factory=list)
    aider_plan: Optional[AiderInvocationPlan] = None
    notes: list[str] = Field(default_factory=list)


class LLMSettings(BaseModel):
    provider: str
    provider_type: str = "openai_compatible"
    model: str
    base_url: Optional[str] = None
    api_key_configured: bool = False
    temperature: float = 0.2
    top_p: float = 1.0
    max_output_tokens: int = 2000
    profile_name: str = ""


class LLMCallResult(BaseModel):
    provider: str
    model: str
    content: str
    status: Literal["completed", "fallback_handoff", "blocked_user_decision"] = "completed"
    fallback_from: Optional[str] = None
    error: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    raw_usage: dict = Field(default_factory=dict)


class TaskState(BaseModel):
    project: str
    task_id: str
    current_agent: Optional[str] = None
    completed_agents: list[str] = Field(default_factory=list)
    reports: dict[str, str] = Field(default_factory=dict)
    status: Literal[
        "new",
        "planned",
        "running",
        "in_progress",
        "paused",
        "blocked",
        "recoverable",
        "failed_recoverable",
        "validating",
        "auditing",
        "archiving",
        "syncing",
        "complete",
        "completed",
        "failed",
        "archived",
    ] = "new"
    execution_mode: str = ""
    last_event: str = ""
    updated_at: str = ""


class BrainDecision(BaseModel):
    timestamp: str
    project: str
    task_id: str
    agent_name: str
    decision_type: Literal["traversal", "token_budget", "loop_check", "user_decision", "codex_quota"]
    decision: Literal["approve", "continue_with_warning", "narrow_scope", "ask_user", "stop_replan"]
    reason: str
    requested_scope: str = ""
    approved_scope: str = ""
    estimated_files: Optional[int] = None
    estimated_tokens: Optional[int] = None
    token_budget_total: Optional[int] = None
    token_usage_total: Optional[int] = None
    requires_user: bool = False
    question: str = ""
    default_recommendation: str = ""


class ValidationReport(BaseModel):
    task_id: str
    commands_run: list[str] = Field(default_factory=list)
    passed: bool = False
    notes: str = ""


class AuditFinding(BaseModel):
    severity: Literal["low", "medium", "high"]
    file_path: Optional[str] = None
    line: Optional[int] = None
    finding: str
    recommendation: str = ""
