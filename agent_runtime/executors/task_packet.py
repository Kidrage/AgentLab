from __future__ import annotations

from pathlib import Path

import yaml

from agent_runtime.atomic_io import atomic_write_yaml
from agent_runtime.executors.connector_contract import build_connector_contract


def create_task_packet(phase_plan_path: Path, executor_type: str, out_dir: Path) -> dict:
    phase = yaml.safe_load(phase_plan_path.read_text(encoding="utf-8")) or {}
    packet = {
        "task_packet": {
            "project": phase.get("project", "AgentLab"),
            "phase_id": phase.get("phase_id"),
            "executor_type": executor_type,
            "objective": phase.get("goal"),
            "allowed_files": phase.get("allowed_files") or ["agent_runtime/**", "tests/**", "docs/**"],
            "forbidden_files": phase.get("forbidden_files") or [".env", "agent_runtime/.env", ".git/**"],
            "required_outputs": phase.get("outputs") or [],
            "acceptance_criteria": phase.get("acceptance_criteria") or [],
            "commands_allowed": ["compileall", "pytest", "agentlab_help"],
            "evidence_required": phase.get("evidence_required") or [],
            "rollback_required": True,
        }
    }
    packet["connector_contract"] = build_connector_contract(executor_type, packet["task_packet"])
    out_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_yaml(out_dir / "task_packet.yml", packet)
    return packet
