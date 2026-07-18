"""AgentLab Lifecycle State Machine.

Implements a canonical lifecycle graph with nodes, state transitions,
checkpoint tracking, and resume support.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

from atomic_io import atomic_write_yaml

# ─── Canonical Lifecycle Nodes ────────────────────────────────────────────

LIFECYCLE_NODES = [
    "INIT_TASK",
    "CONTEXT_PROFILE",
    "CONTEXT_BUDGET",
    "CONTEXT_PACK",
    "PREPARE_PLAN",
    "SUPERVISOR_PLAN",
    "REPO_CONTEXT",
    "RESEARCH_OPTIONAL",
    "OBSERVATION_OPTIONAL",
    "INTERFACE_OPTIONAL",
    "NARRATIVE_REWRITE_PLAN",
    "WRITER_DRAFT",
    "FICTION_REVIEW",
    "SCRIBE_LEDGER",
    "CODER_IMPLEMENTATION",
    "ARTIFACT_PRODUCTION",
    "VISUAL_OBSERVATION",
    "VISUAL_REVIEW",
    "VALIDATION",
    "AUDIT",
    "VERIFY",
    "ARCHIVE",
    "SELF_CHECK",
    "SYNC_OPTIONAL",
    "FINALIZE",
]

# Node dependency: which artifacts each node requires to be marked completed
NODE_REQUIRED_OUTPUTS = {
    "INIT_TASK": ["user_request.md", "state.yml"],
    "CONTEXT_PROFILE": ["context_profile.yml"],
    "CONTEXT_BUDGET": ["context_budget.yml"],
    "CONTEXT_PACK": ["context_pack.yml", "compression_trace.yml"],
    "PREPARE_PLAN": ["workflow_plan.yml"],
    "SUPERVISOR_PLAN": ["01_supervisor_plan.md"],
    "REPO_CONTEXT": ["02_reposcout_report.md"],
    "RESEARCH_OPTIONAL": ["03_research_notes.md"],
    "OBSERVATION_OPTIONAL": ["observation_report.yml"],
    "INTERFACE_OPTIONAL": ["04_interface_map.md"],
    "NARRATIVE_REWRITE_PLAN": ["chapter_state_plan.yml"],
    "WRITER_DRAFT": ["fiction_draft.md"],
    "FICTION_REVIEW": ["fiction_review.yml"],
    "SCRIBE_LEDGER": ["continuity_ledger.yml"],
    "CODER_IMPLEMENTATION": ["06_implementation_report.md"],
    "ARTIFACT_PRODUCTION": ["artifact_producer_report.md"],
    "VISUAL_OBSERVATION": ["visual_observation_report.yml"],
    "VISUAL_REVIEW": ["visual_review_report.yml", "media_qc_report.yml"],
    "VALIDATION": ["07_validation_report.md"],
    "AUDIT": ["08_audit_report.md"],
    "VERIFY": ["verification_report.md"],
    "ARCHIVE": [
        "09_archive_update.md",
        "artifact_lineage.yml",
        "artifact_promotion_plan.yml",
        "archive_receipt.yml",
    ],
    "SELF_CHECK": ["self_check_report.yml"],
    "SYNC_OPTIONAL": ["sync_report.yml"],
    "FINALIZE": ["task_card.yml", "artifact_manifest.yml"],
}

OPTIONAL_NODES = {
    "RESEARCH_OPTIONAL",
    "OBSERVATION_OPTIONAL",
    "INTERFACE_OPTIONAL",
    "NARRATIVE_REWRITE_PLAN",
    "WRITER_DRAFT",
    "FICTION_REVIEW",
    "SCRIBE_LEDGER",
    "CODER_IMPLEMENTATION",
    "ARTIFACT_PRODUCTION",
    "VISUAL_OBSERVATION",
    "VISUAL_REVIEW",
    "VALIDATION",
    "AUDIT",
    "VERIFY",
    "ARCHIVE",
    "SYNC_OPTIONAL",
}

TASK_STATES = {
    "new", "planned", "in_progress", "paused", "blocked",
    "recoverable", "validating", "auditing", "archiving",
    "syncing", "completed", "failed",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def lifecycle_path(run_dir: Path) -> Path:
    return run_dir / "lifecycle.yml"


def create_lifecycle(run_dir: Path, workflow_plan: dict) -> dict:
    """Create a new lifecycle.yml for a task.

    Determines which optional nodes are required based on the route.
    """
    route = workflow_plan.get("route", {}).get("agents", [])
    if not route and isinstance(workflow_plan.get("route"), list):
        route = workflow_plan["route"]
    active_nodes, pack_id = _production_pack_nodes(workflow_plan)

    nodes = {}
    for node_id in LIFECYCLE_NODES:
        is_optional = node_id in OPTIONAL_NODES
        # Determine if optional node is needed based on route
        skip_reason = _skip_reason_for_node(node_id, route, active_nodes, pack_id)

        nodes[node_id] = {
            "status": "skipped" if skip_reason else "waiting",
            "started_at": None,
            "completed_at": None,
            "checkpoint_id": None,
            "report_path": None,
            "error": None,
            "optional": is_optional,
            "skip_reason": skip_reason,
        }

    lifecycle = {
        "version": 1,
        "created_at": _utc_now(),
        "updated_at": _utc_now(),
        "nodes": nodes,
    }

    # Mark INIT_TASK as eligible to start
    lifecycle["nodes"]["INIT_TASK"]["status"] = "waiting"

    save_lifecycle(run_dir, lifecycle)
    return lifecycle


def _skip_reason_for_node(
    node_id: str,
    route: list[str],
    active_nodes: set[str] | None = None,
    pack_id: str = "unknown",
) -> str | None:
    if node_id == "OBSERVATION_OPTIONAL":
        if pack_id in {"media_generation", "media_series_production"}:
            return "Media packs use post-production VISUAL_OBSERVATION"
        if "Observer" not in route:
            return "Route does not include Observer"
        # Observer is a cross-cutting, read-only perception stage.  Existing
        # production packs predate this node, so an explicit route selection
        # activates it without requiring every historical pack to be edited.
        return None
    if active_nodes is not None and node_id not in active_nodes:
        return f"Production pack {pack_id} excludes {node_id}"
    if node_id == "RESEARCH_OPTIONAL" and "Researcher" not in route:
        return "Route does not include Researcher"
    if node_id == "INTERFACE_OPTIONAL" and "InterfaceMapper" not in route:
        return "Route does not include InterfaceMapper"
    if node_id == "NARRATIVE_REWRITE_PLAN" and "NarrativePlanner" not in route:
        return "Route does not include NarrativePlanner"
    if node_id == "WRITER_DRAFT" and "Writer" not in route:
        return "Route does not include Writer"
    if node_id == "FICTION_REVIEW" and "Reviewer" not in route:
        return "Route does not include Reviewer"
    if node_id == "SCRIBE_LEDGER" and "Scribe" not in route:
        return "Route does not include Scribe"
    if node_id == "CODER_IMPLEMENTATION" and "Coder" not in route:
        return "Route does not include Coder"
    if node_id == "ARTIFACT_PRODUCTION" and "ArtifactProducer" not in route:
        return "Route does not include ArtifactProducer"
    if node_id == "VISUAL_OBSERVATION" and "Observer" not in route:
        return "Route does not include Observer"
    if node_id == "VISUAL_REVIEW" and "Reviewer" not in route:
        return "Route does not include Reviewer"
    if node_id in {"VALIDATION", "AUDIT"} and "TesterAuditor" not in route:
        return "Route does not include TesterAuditor"
    if node_id == "VERIFY" and "Verifier" not in route:
        return "Route does not include Verifier"
    if node_id == "ARCHIVE" and "Archivist" not in route:
        return "Route does not include Archivist"
    return None


def _production_pack_nodes(workflow_plan: dict) -> tuple[set[str] | None, str]:
    pack = workflow_plan.get("production_pack")
    if not isinstance(pack, dict):
        return None, "unknown"
    nodes = pack.get("lifecycle_nodes")
    if not isinstance(nodes, list) or not nodes:
        return None, str(pack.get("pack_id") or "unknown")
    return {str(node) for node in nodes}, str(pack.get("pack_id") or "unknown")


def load_lifecycle(run_dir: Path) -> Optional[dict]:
    """Load lifecycle.yml or return None."""
    path = lifecycle_path(run_dir)
    if not path.exists():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def save_lifecycle(run_dir: Path, lifecycle: dict) -> Path:
    """Write lifecycle.yml atomically."""
    lifecycle["updated_at"] = _utc_now()
    path = lifecycle_path(run_dir)
    atomic_write_yaml(path, lifecycle)
    try:
        from task_snapshot import safe_write_task_snapshot
        safe_write_task_snapshot(run_dir)
    except Exception:
        pass
    return path


def next_node(run_dir: Path) -> Optional[str]:
    """Find the next node that should be executed.

    Returns node_id or None if all are completed.
    """
    lifecycle = load_lifecycle(run_dir)
    if not lifecycle:
        return "INIT_TASK"

    nodes = lifecycle.get("nodes", {})

    # Resume the failed/paused checkpoint before advancing to later work.
    for node_id in LIFECYCLE_NODES:
        n = nodes.get(node_id, {})
        if n.get("status") in ("paused", "failed"):
            return node_id

    # Otherwise advance to the first waiting node.
    for node_id in LIFECYCLE_NODES:
        n = nodes.get(node_id, {})
        if n.get("status") == "waiting":
            return node_id

    return None


def mark_node_started(run_dir: Path, node_id: str) -> None:
    """Mark a lifecycle node as started."""
    lifecycle = load_lifecycle(run_dir)
    if not lifecycle:
        return
    nodes = lifecycle.setdefault("nodes", {})
    if node_id not in nodes:
        nodes[node_id] = {"status": "waiting"}
    nodes[node_id]["status"] = "running"
    nodes[node_id]["started_at"] = _utc_now()
    save_lifecycle(run_dir, lifecycle)


def mark_node_completed(run_dir: Path, node_id: str, report_path: Optional[str] = None) -> None:
    """Mark a lifecycle node as completed."""
    lifecycle = load_lifecycle(run_dir)
    if not lifecycle:
        return
    nodes = lifecycle.setdefault("nodes", {})
    if node_id not in nodes:
        nodes[node_id] = {}
    nodes[node_id]["status"] = "completed"
    nodes[node_id]["completed_at"] = _utc_now()
    nodes[node_id]["error"] = None
    if report_path:
        nodes[node_id]["report_path"] = report_path
    # Mark next node as waiting if it's waiting/skipped
    idx = LIFECYCLE_NODES.index(node_id) if node_id in LIFECYCLE_NODES else -1
    if idx >= 0 and idx + 1 < len(LIFECYCLE_NODES):
        next_nid = LIFECYCLE_NODES[idx + 1]
        n = nodes.get(next_nid, {})
        if n.get("status") in ("waiting", None):
            nodes[next_nid]["status"] = "waiting"
    save_lifecycle(run_dir, lifecycle)


def mark_node_skipped(run_dir: Path, node_id: str, reason: str) -> None:
    """Mark an optional lifecycle node as skipped."""
    lifecycle = load_lifecycle(run_dir)
    if not lifecycle:
        return
    nodes = lifecycle.setdefault("nodes", {})
    if node_id not in nodes:
        nodes[node_id] = {}
    nodes[node_id]["status"] = "skipped"
    nodes[node_id]["completed_at"] = _utc_now()
    nodes[node_id]["skip_reason"] = reason
    # Mark next as waiting
    idx = LIFECYCLE_NODES.index(node_id) if node_id in LIFECYCLE_NODES else -1
    if idx >= 0 and idx + 1 < len(LIFECYCLE_NODES):
        next_nid = LIFECYCLE_NODES[idx + 1]
        n = nodes.get(next_nid, {})
        if n.get("status") in ("waiting", None, "skipped"):
            nodes[next_nid]["status"] = "waiting"
    save_lifecycle(run_dir, lifecycle)


def mark_node_failed(run_dir: Path, node_id: str, error: str) -> None:
    """Mark a lifecycle node as failed."""
    lifecycle = load_lifecycle(run_dir)
    if not lifecycle:
        return
    nodes = lifecycle.setdefault("nodes", {})
    if node_id not in nodes:
        nodes[node_id] = {}
    nodes[node_id]["status"] = "failed"
    nodes[node_id]["error"] = error
    save_lifecycle(run_dir, lifecycle)


def validate_lifecycle(run_dir: Path) -> dict:
    """Validate the lifecycle completeness."""
    lifecycle = load_lifecycle(run_dir)
    if not lifecycle:
        return {"valid": False, "errors": ["lifecycle.yml not found"]}

    nodes = lifecycle.get("nodes", {})
    errors = []
    valid_statuses = {"completed", "skipped", "failed", "paused"}

    for node_id in LIFECYCLE_NODES:
        n = nodes.get(node_id, {})
        status = n.get("status")

        # Must have a valid terminal status or be waiting
        if status is None or status == "waiting":
            if node_id != LIFECYCLE_NODES[0]:
                # Check that all previous nodes are terminal
                idx = LIFECYCLE_NODES.index(node_id)
                for prev in LIFECYCLE_NODES[:idx]:
                    ps = nodes.get(prev, {}).get("status")
                    if ps not in valid_statuses:
                        errors.append(f"Node {prev} has status {ps}, expected terminal before {node_id}")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "node_count": len(LIFECYCLE_NODES),
        "completed_count": sum(1 for nid in LIFECYCLE_NODES if nodes.get(nid, {}).get("status") == "completed"),
        "skipped_count": sum(1 for nid in LIFECYCLE_NODES if nodes.get(nid, {}).get("status") == "skipped"),
    }


def lifecycle_summary(run_dir: Path) -> str:
    """Get human-readable lifecycle status."""
    lifecycle = load_lifecycle(run_dir)
    if not lifecycle:
        return "No lifecycle"

    nodes = lifecycle.get("nodes", {})
    lines = []
    for node_id in LIFECYCLE_NODES:
        n = nodes.get(node_id, {})
        status = n.get("status", "?")
        icon = {
            "completed": "✅", "skipped": "⏭️", "running": "🔄",
            "waiting": "⏳", "paused": "⏸️", "failed": "❌",
        }.get(status, "❓")
        reason = n.get("skip_reason", "")
        lines.append(f"  {icon} {node_id}: {status}")
        if reason:
            lines[-1] += f" ({reason})"
    return "\n".join(lines)
