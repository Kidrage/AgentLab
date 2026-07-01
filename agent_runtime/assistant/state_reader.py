"""M3-8 Assistant state reader — driven by Operator State read model."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from agent_runtime.assistant.models import AssistantStateSnapshot
from agent_runtime.operator_os.state_model import build_operator_state


def read_project_state(project: str, root: Optional[Path] = None) -> AssistantStateSnapshot:
    """Read project state using the M3 Operator State single read model.

    This replaces direct filesystem traversal with build_operator_state(),
    ensuring the assistant sees the same normalized view as the WebUI/TUI/CLI.
    """
    if root is None:
        root = Path.cwd()

    project_root = root / 'projects' / project
    if not project_root.exists():
        return AssistantStateSnapshot(
            project_id=project,
            known=False,
            current_phase='not_found',
            phase_statuses={},
            blocked_items=[],
            pending_approvals=[],
            cost_summary=0.0,
            recent_events=[],
            acceptance_reports=[],
            recovery_events=[],
            route_decisions=[],
            worker_status=[],
            source_files=[],
            warnings=['project directory not found'],
        )

    try:
        state = build_operator_state(root, project)
    except Exception:
        return AssistantStateSnapshot(
            project_id=project,
            known=False,
            current_phase="error",
            phase_statuses={},
            blocked_items=[],
            pending_approvals=[],
            cost_summary=0.0,
            recent_events=[],
            acceptance_reports=[],
            recovery_events=[],
            route_decisions=[],
            worker_status=[],
            source_files=[],
            warnings=["operator_state_read_failed"],
        )

    pp = state.get("phase_progress", {})
    na = state.get("next_action", {}).get("data", {})
    cs = state.get("cost_state", {})
    timeline = state.get("timeline", [])
    approvals = state.get("approvals", [])
    recovery = state.get("recovery_plans", [])
    brain = state.get("project_brain", {})

    # derive blocked items from phase_statuses
    blocked_items: list[str] = []
    phase_statuses: dict[str, str] = {}
    for pid, pstatus in pp.get("phase_statuses", {}).items():
        phase_statuses[pid] = pstatus
        if pstatus in ("blocked", "needs_evidence", "needs_human_review"):
            blocked_items.append(f"{pid}: {pstatus}")

    # pending approvals
    pending_approvals: list[str] = [
        f"{a.get('type')}: {a.get('phase_id') or a.get('task_id')}"
        for a in approvals
        if a.get("status") == "pending"
    ]

    # cost summary
    cost = cs.get("total_estimated_cost_usd")
    cost_summary = float(cost) if cost is not None else 0.0

    # derive current phase
    accepted_ids = pp.get("accepted_phase_ids") or []
    current_phase = na.get("next_phase_id") or (accepted_ids[-1] if accepted_ids else "")

    # recent events from timeline (last 10)
    recent_events: list[str] = []
    for evt in timeline[-10:]:
        et = evt.get("event_type", "")
        d = evt.get("data", {})
        pid = d.get("phase_id") or d.get("task_id") or ""
        recent_events.append(f"{et}: {pid}")

    # acceptance reports from latest acceptance
    latest = pp.get("latest_acceptance")
    acceptance_reports = [f"{latest.get('phase_id')}: {latest.get('verdict')}"] if latest else []

    # recovery events
    recovery_events = [
        f"{rp.get('task_id')}: {rp.get('failure_category')} → {rp.get('recommended_action')}"
        for rp in recovery
    ]

    # source files
    source_files: list[str] = []
    sources = {
        "acceptance_history": f"projects/{project}/project_brain/acceptance_history.yml",
        "next_actions": f"projects/{project}/project_brain/next_actions.yml",
        "fact_snapshot": f"projects/{project}/project_brain/project_fact_snapshot.yml",
        "artifact_index": f"projects/{project}/project_artifact_index.yml",
    }
    for label, path in sources.items():
        if (root / path).exists():
            source_files.append(path)
        else:
            source_files.append(f"{path} (missing)")

    # warnings
    warnings: list[str] = []
    if not brain.get("healthy"):
        warnings.append(f"Project Brain unhealthy: missing {brain.get('missing_files', [])}")
    if cs.get("has_cost_data") is False:
        warnings.append("No cost data available")
    if state.get("capability_gaps"):
        unresolved = [g for g in state["capability_gaps"] if g.get("status") == "unresolved"]
        if unresolved:
            warnings.append(f"{len(unresolved)} unresolved capability gaps")

    return AssistantStateSnapshot(
        project_id=project,
        known=True,
        current_phase=current_phase,
        phase_statuses=phase_statuses,
        blocked_items=blocked_items,
        pending_approvals=pending_approvals,
        cost_summary=cost_summary,
        recent_events=recent_events,
        acceptance_reports=acceptance_reports,
        recovery_events=recovery_events,
        route_decisions=[],
        worker_status=[],
        source_files=source_files,
        warnings=warnings,
    )
