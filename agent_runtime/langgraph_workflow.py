"""AgentLab pipeline expressed as a LangGraph StateGraph (MVP).

Reuses the existing `agent_runner` LLM-call plumbing but replaces the
file-system-based agent dispatch with a compiled StateGraph.

Usage:
  from langgraph_workflow import build_agentlab_graph, run_agentlab_graph

  app = build_agentlab_graph(agentlab_root, plan)
  final_state = run_agentlab_graph(app, plan)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# ---- try importing langgraph; if missing, provide clear error ----
try:
    from langgraph.graph import StateGraph, END
    from langgraph.checkpoint.memory import InMemorySaver
except ImportError as exc:
    StateGraph = None
    END = None
    InMemorySaver = None
    _LANGGRAPH_IMPORT_ERROR = exc
else:
    _LANGGRAPH_IMPORT_ERROR = None

from langgraph_schema import AgentLabState

# Reuse existing AgentLab components
from agent_runner import (
    report_path_for_agent,
    run_agent_model,
    is_placeholder_report,
)
from brain_governor import (
    evaluate_harness_status,
    evaluate_token_status,
    append_brain_decision,
)
from schemas import BrainDecision, WorkflowPlan
from state_store import utc_now


# ---------------------------------------------------------------------------
# Graph node functions
# ---------------------------------------------------------------------------

def _make_agent_node(agent_name: str, phase_label: str):
    """Factory: return a node function for one AgentLab agent role.

    Each node:
    1. Resolves the report output path (file system side effect).
    2. Calls the LLM via `run_agent_model` (reuses existing provider/retry logic).
    3. Records the report path in state['reports'].
    4. Tracks token usage in state['token_usage'].
    5. Tracks files_changed and commands_run if reported.
    """

    def node_fn(state: AgentLabState, config: dict = None) -> dict:
        agentlab_root = Path(state["agentlab_root"])
        run_dir = Path(state["run_dir"])

        # Rebuild WorkflowPlan from serialized dict
        plan = WorkflowPlan(**state["workflow_plan"])

        # Determine report path (file system side effect)
        output_path = report_path_for_agent(plan, agent_name, output=None)

        # Run the agent (LLM call via existing provider)
        print(f"  [{agent_name}] Running LLM model...")
        result = run_agent_model(
            agentlab_root=agentlab_root,
            plan=plan,
            agent_name=agent_name,
            output_path=output_path,
            apply_patches=(agent_name == "Coder"),
        )

        # Build state update
        update: dict[str, Any] = {
            "current_phase": phase_label,
        }

        # Record report
        update["reports"] = {agent_name: str(output_path.relative_to(run_dir))}

        # Track token usage
        if result.total_tokens:
            update["token_usage"] = {
                agent_name: {
                    "input": result.input_tokens or 0,
                    "output": result.output_tokens or 0,
                    "total": result.total_tokens,
                }
            }

        # Track file changes (from patch applicator)
        patch_details = (result.raw_usage or {}).get("patch_details", [])
        if patch_details:
            changed = [
                f"{d.get('path')} (L{d.get('line_start')}-{d.get('line_end')})"
                for d in patch_details
                if d.get("success")
            ]
            if changed:
                update["files_changed"] = changed

        # If the agent produced actual content, store the summary
        if result.status == "completed" and result.content:
            summary_snippet = result.content[:200] + "..." if len(result.content) > 200 else result.content
            update["raw_outputs"] = [f"[{agent_name}] {summary_snippet}"]

        # If blocked, record as error
        if result.status == "blocked_user_decision":
            update["errors"] = [f"{agent_name}: {result.error}"]
            update["user_decision_pending"] = True

        # Phase-specific extras
        if agent_name == "Supervisor":
            # Record a brain decision for the plan
            decision = BrainDecision(
                timestamp=utc_now(),
                project=state["project"],
                task_id=state["task_id"],
                agent_name="Supervisor",
                decision_type="traversal",
                decision="approve",
                reason=f"Workflow plan built for task {state['task_id']} via LangGraph backend.",
                requested_scope="full_pipeline",
                approved_scope="full_pipeline",
            )
            append_brain_decision(run_dir, decision)
            update["brain_decisions"] = [decision.model_dump(mode="json")]

        if agent_name == "Verifier":
            # Mark validation as complete
            report_text = output_path.read_text(encoding="utf-8") if output_path.exists() else ""
            passed = "PASS" in report_text or "passed" in report_text.lower()
            update["validation_passed"] = passed

        return update

    # Attach metadata for debugging
    node_fn.__name__ = f"agentlab_{agent_name.lower()}"
    return node_fn


# ---------------------------------------------------------------------------
# Pre-built node functions for each agent role
# ---------------------------------------------------------------------------

supervisor_node = _make_agent_node("Supervisor", "planning")
reposcout_node = _make_agent_node("RepoScout", "scouting")
researcher_node = _make_agent_node("Researcher", "research")
interface_mapper_node = _make_agent_node("InterfaceMapper", "mapping")
coder_node = _make_agent_node("Coder", "coding")
tester_node = _make_agent_node("TesterAuditor", "testing")
verifier_node = _make_agent_node("Verifier", "verifying")
archivist_node = _make_agent_node("Archivist", "archiving")


# ---------------------------------------------------------------------------
# Conditional routing (MVP: always continue)
# ---------------------------------------------------------------------------

def _should_continue(state: AgentLabState) -> str:
    """After each agent, decide whether to continue or pause for user input."""
    if state.get("user_decision_pending"):
        return "pause"
    if state.get("errors") and len(state["errors"]) >= 3:
        return "stop"
    return "continue"


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_agentlab_graph(
    agentlab_root: Path,
    plan: WorkflowPlan,
) -> StateGraph:
    """Build a compiled LangGraph StateGraph for one AgentLab task.

    The graph topology mirrors the plan's route.agents list (linear pipeline).
    MVP: fixed edges, no conditional branching, InMemorySaver checkpoint.
    """
    if StateGraph is None:
        raise RuntimeError(
            "LangGraph is not installed. Install optional dependencies or run "
            "`./agentlab.sh run-pipeline --execution-backend codex`."
        ) from _LANGGRAPH_IMPORT_ERROR

    # Determine which agents to include
    agent_names = plan.route.agents
    available_nodes = {
        "Supervisor": supervisor_node,
        "RepoScout": reposcout_node,
        "Researcher": researcher_node,
        "InterfaceMapper": interface_mapper_node,
        "Coder": coder_node,
        "TesterAuditor": tester_node,
        "Verifier": verifier_node,
        "Archivist": archivist_node,
    }

    # Build graph
    builder = StateGraph(AgentLabState)

    # Add nodes only for agents in the route
    for name in agent_names:
        if name in available_nodes:
            builder.add_node(name, available_nodes[name])
        else:
            print(f"  [WARN] Unknown agent '{name}' — skipping.")

    # Add edges in order: first agent gets START, last gets END, rest are chained
    included = [n for n in agent_names if n in available_nodes]
    if not included:
        raise ValueError("No valid agents in plan route.")

    builder.set_entry_point(included[0])

    for i in range(len(included) - 1):
        builder.add_edge(included[i], included[i + 1])

    builder.add_edge(included[-1], END)

    # Compile with in-memory checkpoint (MVP)
    checkpointer = InMemorySaver()
    compiled = builder.compile(checkpointer=checkpointer)
    return compiled


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_agentlab_graph(app, plan: WorkflowPlan) -> dict:
    """Execute the compiled graph and return the final state dict.

    Also writes all agent reports to the file system (shadow mode compatibility).
    """

    initial_state: dict[str, Any] = {
        "project": plan.project,
        "task_id": plan.task_id,
        "agentlab_root": plan.agentlab_root,
        "project_root": plan.project_root,
        "repo_path": plan.repo_path,
        "run_dir": plan.run_dir,
        "execution_backend": "langgraph",
        "workflow_plan": plan.model_dump(mode="json"),
        "reports": {},
        "brain_decisions": [],
        "token_usage": {},
        "files_changed": [],
        "commands_run": [],
        "validation_passed": None,
        "user_decision_pending": False,
        "user_decision": "",
        "current_phase": "init",
        "errors": [],
        "raw_outputs": [],
    }

    # Pre-flight harness check (same as brain_governor)
    harness = evaluate_harness_status(plan, Path(plan.agentlab_root))
    if harness["state"] in ("warn", "ask_user"):
        print(f"  [Brain] Harness status: {harness['state']}")
        for rec in harness.get("recommendations", []):
            print(f"    -> {rec}")

    print(f"\n  [LangGraph] Starting pipeline: {' → '.join(plan.route.agents)}")
    print(f"  [LangGraph] Run dir: {plan.run_dir}\n")

    # Run the graph (synchronous invoke)
    config = {"configurable": {"thread_id": f"{plan.project}_{plan.task_id}"}}
    final_state = app.invoke(initial_state, config)

    # Print summary
    print(f"\n  [LangGraph] Pipeline complete.")
    print(f"  [LangGraph] Phase: {final_state.get('current_phase', 'unknown')}")
    print(f"  [LangGraph] Reports generated: {len(final_state.get('reports', {}))}")
    print(f"  [LangGraph] Files changed: {len(final_state.get('files_changed', []))}")
    print(f"  [LangGraph] Validation passed: {final_state.get('validation_passed', 'N/A')}")

    total_tokens = sum(
        u.get("total", 0) for u in final_state.get("token_usage", {}).values()
    )
    print(f"  [LangGraph] Total tokens used: {total_tokens}")

    errors = final_state.get("errors", [])
    if errors:
        print(f"  [LangGraph] Errors ({len(errors)}):")
        for e in errors:
            print(f"    - {e}")

    return dict(final_state)
