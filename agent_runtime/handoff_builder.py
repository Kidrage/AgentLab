"""Build a task handoff packet from AgentLab's durable run state.

Responsibilities:
1. Read state/progress/reports.
2. Build handoff_packet.yml.
3. Mark next_agent.
4. Mark continuation mode options.

The ``codex-handoff`` CLI name is retained for compatibility; the packet does
not grant Codex or any other worker authority over the workflow route.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

from state_store import load_state
from progress_tracker import load_progress


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_next_agent(completed_agents: list[str], route_agents: list[str]) -> Optional[str]:
    """Determine the next agent to run based on completed agents and route.

    Args:
        completed_agents: List of agent names already completed.
        route_agents: Full ordered list of agents in the route.

    Returns:
        The next agent name, or None if all agents are completed.
    """
    for agent in route_agents:
        if agent not in completed_agents:
            return agent
    return None


def build_handoff_packet(
    project_root: Path,
    task_id: str,
    route_agents: Optional[list[str]] = None,
    branch: str = "main",
    base_commit: Optional[str] = None,
) -> dict:
    """Build a handoff_packet.yml dict from local task state.

    Args:
        project_root: Path to the project directory (projects/<ProjectName>/).
        task_id: Task run identifier.
        route_agents: Optional full agent route list. If None, reads from workflow_plan.yml.
        branch: Git branch name.
        base_commit: Git commit SHA at start of task.

    Returns:
        A dict conforming to the handoff_packet.yml schema.
    """
    run_dir = project_root / "runs" / task_id

    # Load state
    state = load_state(run_dir, project_root.name, task_id)

    # Load progress
    progress_data = load_progress(run_dir)
    if progress_data:
        percent = progress_data.get("percent", 0)
    else:
        percent = 0

    # Load route and artifact intent from workflow_plan.
    plan_data = {}
    plan_path = run_dir / "workflow_plan.yml"
    if plan_path.exists():
        plan_data = yaml.safe_load(plan_path.read_text(encoding="utf-8")) or {}
    if route_agents is None:
        if plan_data:
            route_agents = plan_data.get("route", {}).get("agents", [])
        else:
            route_agents = []

    # Determine status
    if state.status in ("complete", "completed"):
        status = "completed"
    elif state.status == "blocked":
        status = "blocked"
    elif state.status == "paused":
        status = "paused"
    else:
        status = "running"

    # Determine next agent. A completed task is terminal even when legacy
    # state.completed_agents was not populated by the lifecycle runner.
    completed = list(state.completed_agents) if state.completed_agents else []
    next_agent = None if status == "completed" else _resolve_next_agent(completed, route_agents)

    # Collect artifact paths
    artifacts = {}
    artifact_map = {
        "user_request": "user_request.md",
        "workflow_plan": "workflow_plan.yml",
        "supervisor_plan": "01_supervisor_plan.md",
        "reposcout_report": "02_reposcout_report.md",
        "research_notes": "03_research_notes.md",
        "interface_map": "04_interface_map.md",
        "codex_prompt": "05_codex_prompt.md",
        "implementation_report": "06_implementation_report.md",
        "validation_report": "07_validation_report.md",
        "audit_report": "08_audit_report.md",
        "archive_update": "09_archive_update.md",
        "artifact_lineage": "artifact_lineage.yml",
        "artifact_promotion_plan": "artifact_promotion_plan.yml",
        "archive_receipt": "archive_receipt.yml",
    }
    for key, filename in artifact_map.items():
        p = run_dir / filename
        if p.exists():
            artifacts[key] = filename

    # Count changed files (from git status if available, otherwise placeholder)
    changed_files = []
    try:
        import subprocess
        result = subprocess.run(
            ["git", "diff", "--name-only"],
            capture_output=True, text=True, cwd=project_root.parent,
        )
        if result.returncode == 0:
            changed_files = [f for f in result.stdout.strip().split("\n") if f]
    except Exception:
        pass

    # Build packet
    packet = {
        "task_id": task_id,
        "project": project_root.name,
        "execution_mode": state.execution_mode or "agentlab_orchestrated_cli",
        "status": status,
        "last_completed_agent": completed[-1] if completed else None,
        "next_agent": next_agent,
        "resume_available": status != "completed",
        "artifacts": artifacts,
        "artifact_intent": plan_data.get("artifact_intent") or {},
        "code_state": {
            "branch": branch,
            "base_commit": base_commit or "unknown",
            "final_commit": None,
            "dirty": len(changed_files) > 0,
            "changed_files": changed_files,
        },
        "validation": {
            "status": "not_run" if "TesterAuditor" not in completed else "passed",
            "commands_run": [],
            "known_risks": [],
        },
        "resume_instructions": {
            "for_assigned_worker": f"Read the scoped role packet, then continue from {next_agent or 'start'}.",
            "for_codex": f"Compatibility only: continue only if assigned the {next_agent or 'next'} role.",
            "for_api_agents": f"Run ./agentlab.sh continue-with-api --project {project_root.name} --task-id {task_id} --from handoff_packet.yml",
            "for_human": "Read 09_archive_update.md and 08_audit_report.md first.",
        },
        "backup": {
            "github_pushed": False,
            "truenas_synced": False,
            "local_checkpoint": f"checkpoint_003_final" if status == "completed" else f"checkpoint_{completed[-1].lower() if completed else '000_preflight'}",
        },
        "built_at": _utc_now(),
    }

    return packet


def write_handoff_packet(project_root: Path, task_id: str, packet: Optional[dict] = None) -> Path:
    """Write handoff_packet.yml to the task run directory.

    Args:
        project_root: Path to the project directory.
        task_id: Task run identifier.
        packet: Pre-built packet dict. If None, builds from local state.

    Returns:
        Path to the written handoff_packet.yml.
    """
    if packet is None:
        packet = build_handoff_packet(project_root, task_id)

    run_dir = project_root / "runs" / task_id
    handoff_path = run_dir / "handoff_packet.yml"
    handoff_path.parent.mkdir(parents=True, exist_ok=True)
    handoff_path.write_text(
        yaml.safe_dump(packet, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return handoff_path
