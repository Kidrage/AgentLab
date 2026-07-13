"""Task-packet router and evidence writer."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from agent_runtime.routing.role_assignment import RoleAssignmentEngine


def _safe_segment(value: str, fallback: str) -> str:
    cleaned = "".join(ch for ch in str(value) if ch.isalnum() or ch in "_-.").strip(".")
    return cleaned or fallback


def route_task_packet(task_packet_path: Path, agentlab_root: Path) -> dict[str, Any]:
    path = Path(task_packet_path)
    if not path.exists():
        raise FileNotFoundError(f"Task packet not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    packet = data.get("task_packet", data)
    project_id = _safe_segment(packet.get("project_id", "AgentLab"), "AgentLab")
    phase_id = _safe_segment(packet.get("phase_id", "unknown"), "unknown")
    task_id = _safe_segment(packet.get("task_id") or packet.get("packet_id") or "ad_hoc_route", "ad_hoc_route")
    roles = packet.get("roles") or [packet.get("role") or "Coder"]
    if isinstance(roles, str):
        roles = [roles]
    constraints = {
        "allowed_files": list(packet.get("allowed_files", []) or []),
        "forbidden_files": list(packet.get("forbidden_files", []) or []),
        "commands_allowed": list(packet.get("commands_allowed", []) or []),
        "commands_forbidden": list(packet.get("commands_forbidden", []) or []),
    }
    mode = packet.get("assignment_mode") or packet.get("mode") or "hybrid_local_company"
    tier = packet.get("tier") or "performance"
    available = packet.get("available_workers")
    approved = packet.get("approved_workers") or []
    extra_caps = packet.get("required_capabilities") or []
    artifact_type = packet.get("artifact_type")
    artifact_task = packet.get("artifact_task")
    if not artifact_type and isinstance(artifact_task, dict):
        artifact_type = artifact_task.get("artifact_type")
    engine = RoleAssignmentEngine(Path(agentlab_root))
    out_dir = Path(agentlab_root) / "projects" / project_id / "runs" / task_id / "routing"
    decisions = []
    for role in roles:
        decision = engine.assign(
            role,
            artifact_type=(
                str(artifact_type)
                if str(role).lower().replace("_", "").replace("-", "")
                == "artifactproducer"
                and artifact_type
                else None
            ),
            project_id=project_id,
            phase_id=phase_id,
            task_id=task_id,
            mode=mode,
            tier=tier,
            available_workers=available,
            approved_workers=approved,
            constraints=constraints,
            extra_required_capabilities=extra_caps,
        )
        file_name = f"route_decision_{_safe_segment(str(role).lower(), 'role')}.yml"
        evidence_path = out_dir / file_name
        decision.evidence_paths.append(str(evidence_path))
        decision.write(evidence_path)
        decisions.append(decision.to_dict()["route_decision"])

    manifest = {
        "route_plan": {
            "project_id": project_id,
            "phase_id": phase_id,
            "task_id": task_id,
            "mode": mode,
            "tier": tier,
            "decisions": decisions,
        }
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "route_plan.yml"
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True), encoding="utf-8")
    manifest["route_plan"]["evidence_path"] = str(manifest_path)
    return manifest
