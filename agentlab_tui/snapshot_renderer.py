"""M3-3 TUI snapshot renderer — driven by Operator State read model."""

from __future__ import annotations

from typing import Optional
from pathlib import Path

try:
    from agent_runtime.operator_os.state_model import build_operator_state
except ImportError:
    def build_operator_state(root, project):
        return {"stage": "unavailable", "project": {"status": "operator_os_unavailable"}}


def render_tui_snapshot(project: Optional[str] = None, view: str = "overview", root: Optional[Path] = None) -> str:
    """Render a text snapshot of the requested view from Operator State."""
    if not project:
        return f"=== AgentLab TUI Headless Snapshot ===\nView: {view}\nProject: [None selected]\n"

    if root is None:
        root = Path.cwd()

    state = build_operator_state(root, project)
    warnings: list[str] = []

    output = [
        f"=== AgentLab TUI Headless Snapshot ===",
        f"Project: {project}",
        f"View: {view}",
        f"Status: {state.get('project', {}).get('status', 'unknown')}",
    ]

    pp = state.get("phase_progress", {})
    na = state.get("next_action", {}).get("data", {})
    cs = state.get("cost_state", {})
    approvals = state.get("approvals", [])
    recovery = state.get("recovery_plans", [])
    exec_results = state.get("executor_results", [])
    artifacts = state.get("artifacts", {})
    brain = state.get("project_brain", {})
    gaps = state.get("capability_gaps", [])

    if view == "overview":
        output.append(f"Phase: {na.get('next_phase_id', 'N/A')}")
        output.append(f"Next Action: {na.get('next_action', 'N/A')}")
        output.append(f"Accepted Phases: {pp.get('accepted_phase_ids', [])}")
        output.append(f"Phase Statuses: {pp.get('phase_statuses', {})}")
        cost = cs.get("total_estimated_cost_usd")
        output.append(f"Total Cost: ${cost:.4f}" if cost is not None else "Total Cost: N/A")
        output.append(f"Cost Data Available: {cs.get('has_cost_data', False)}")
        output.append(f"Brain Healthy: {brain.get('healthy', False)}")

    elif view == "phases":
        for phase_id, status in pp.get("phase_statuses", {}).items():
            output.append(f"  {phase_id}: {status}")
        if not pp.get("phase_statuses"):
            output.append("  No phases tracked.")

    elif view == "tasks":
        for er in exec_results:
            output.append(f"  {er.get('task_id')}: status={er.get('status')}, executor={er.get('executor_id')}")
        if not exec_results:
            output.append("  No executor results found.")

    elif view == "evidence":
        for ev in state.get("evidence_ledgers", []):
            output.append(f"  {ev.get('task_id')}: {ev.get('evidence_count')} evidence files")
        if not state.get("evidence_ledgers"):
            output.append("  No evidence ledgers found.")

    elif view == "costs":
        cost = cs.get("total_estimated_cost_usd")
        output.append(f"Total Estimated Cost: ${cost:.4f}" if cost is not None else "Total Estimated Cost: N/A")
        output.append(f"Global Cost Ledger: {cs.get('global_cost_ledger_present', False)}")
        for tl in cs.get("per_task_ledgers", []):
            output.append(f"  {tl.get('task_id')}: ${tl.get('estimated_cost_usd', 0):.4f} ({tl.get('call_count')} calls)")

    elif view == "approvals":
        pending = [a for a in approvals if a.get("status") == "pending"]
        resolved = [a for a in approvals if a.get("status") != "pending"]
        output.append(f"Pending: {len(pending)}")
        for a in pending:
            output.append(f"  [{a.get('type')}] {a.get('phase_id') or a.get('task_id')}: {a.get('question', 'N/A')}")
        output.append(f"Resolved: {len(resolved)}")

    elif view == "recovery":
        for rp in recovery:
            output.append(f"  {rp.get('task_id')}: category={rp.get('failure_category')}, action={rp.get('recommended_action')}")
        if not recovery:
            output.append("  No recovery plans.")

    elif view == "artifacts":
        output.append(f"Artifact Index Present: {artifacts.get('index_present', False)}")
        output.append(f"Source: {artifacts.get('source', 'N/A')}")

    elif view == "config":
        safety = state.get("safety", {})
        sp = state.get("source_policy", {})
        output.append(f"Single Read Model: {sp.get('single_read_model', False)}")
        output.append(f"Progress Source: {sp.get('progress_source', 'N/A')}")
        output.append(f"Mutations Require Contract: {safety.get('mutations_require_operator_action_contract', False)}")

    else:
        output.append(f"Unknown view: {view}")

    # collect warnings from state
    if not brain.get("healthy"):
        warnings.append(f"Project Brain unhealthy: missing {brain.get('missing_files', [])}")
    if gaps:
        unresolved = [g for g in gaps if g.get("status") == "unresolved"]
        if unresolved:
            warnings.append(f"{len(unresolved)} unresolved capability gaps")
    for a in approvals:
        if a.get("status") == "pending":
            warnings.append(f"Pending approval: {a.get('type')} for {a.get('phase_id') or a.get('task_id')}")

    if warnings:
        output.append("\nWarnings:")
        for w in warnings:
            output.append(f" - {w}")

    return "\n".join(output)
