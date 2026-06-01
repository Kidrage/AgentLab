"""AgentLab State schema for LangGraph integration.

Defines the shared state TypedDict that flows through the agent pipeline.
Each agent node reads the full state and returns a partial update dict.
LangGraph applies reducer functions to merge updates into the canonical state.
"""

from __future__ import annotations

from operator import add
from typing import Any, Optional

from typing_extensions import Annotated, TypedDict


# ---- Reducer helpers ----

def _merge_dicts(a: dict, b: dict) -> dict:
    """Reducer: shallow-merge two dicts, with b taking precedence for same keys."""
    return {**a, **b}


def _append_list(a: list, b: list | None) -> list:
    """Reducer: append items from b to a. If b is None/empty, return a unchanged."""
    if b:
        return a + b
    return a


def _last_write(_a: Any, b: Any) -> Any:
    """Reducer: last writer wins (default for unannotated keys)."""
    return b


# ---- AgentLab State ----

class AgentLabState(TypedDict, total=False):
    """Shared state for one AgentLab task run.

    Each node receives this state as input and returns a `dict` subset of these
    keys.  LangGraph merges the returned dict into the canonical state using the
    reducer annotations below.
    """

    # -- Task identity (set once at graph start) --
    project: str
    task_id: str
    agentlab_root: str
    project_root: str
    repo_path: str
    run_dir: str
    execution_backend: str  # "codex" | "qwen" | "langgraph"

    # -- Workflow plan (loaded once) --
    workflow_plan: dict  # serialized WorkflowPlan

    # -- Agent reports (each agent appends one entry) --
    # Key: agent name, Value: report file path (relative to run_dir)
    reports: Annotated[dict, _merge_dicts]

    # -- Brain decisions (appended per decision) --
    brain_decisions: Annotated[list, add]

    # -- Token / cost tracking (merged per agent) --
    # Key: agent name, Value: {"input": N, "output": N, "total": N}
    token_usage: Annotated[dict, _merge_dicts]

    # -- File changes (appended per Coder edit) --
    files_changed: Annotated[list, add]

    # -- Commands run (appended per agent) --
    commands_run: Annotated[list, add]

    # -- Validation status --
    validation_passed: Optional[bool]

    # -- Human-in-the-loop (set by BrainGovernor node) --
    user_decision_pending: bool
    user_decision: str  # "" | "continue" | "stop" | "narrow"

    # -- Execution phase (purely informational, set by each node) --
    current_phase: str  # "planning" | "scouting" | "research" | "mapping" | "coding" | "testing" | "verifying" | "archiving" | "complete"

    # -- Errors (appended per non-fatal error) --
    errors: Annotated[list, add]

    # -- Raw LLM outputs for archiving (appended) --
    raw_outputs: Annotated[list, add]