from __future__ import annotations

from pathlib import Path

import yaml

from agent_runtime.atomic_io import atomic_write_yaml
from agent_runtime.executors.connector_contract import build_connector_contract


def create_task_packet(phase_plan_path: Path, executor_type: str, out_dir: Path) -> dict:
    # 1. Enforce executor permission policy
    from agent_runtime.executors.policy import load_executor_router_policy
    # Load connectors config or use standard set of allowed executors
    allowed_list = {
        "mock_executor",
        "codex",
        "cline",
        "claude_code",
        "human_contractor",
        "local_cli_generic",
        "claude_code_handoff",
        "hermes_handoff",
        "codex_handoff",
        "manual_patch_submitter",
        "generic_patch_submitter",
    }
    # Try loading from config if exists
    config_path = Path(__file__).resolve().parents[2] / "config" / "executor_connectors.yml"
    if config_path.exists():
        try:
            data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            connectors = data.get("connectors") or {}
            if connectors:
                allowed_list.update(connectors.keys())
        except Exception:
            pass

    if executor_type not in allowed_list:
        raise ValueError(f"Unauthorized executor type: {executor_type}")

    phase = yaml.safe_load(phase_plan_path.read_text(encoding="utf-8")) or {}
    from agent_runtime.long_project_governance import assert_dispatch_allowed, plan_self_check

    assert_dispatch_allowed(phase)
    project_name = phase.get("project", "AgentLab")
    phase_id = phase.get("phase_id", "unknown")
    self_check = plan_self_check(phase)
    
    packet = {
        "task_packet": {
            "packet_id": f"{project_name}_{phase_id}_task",
            "project_id": project_name,
            "phase_id": phase_id,
            "executor_type": executor_type,
            "objective": phase.get("goal"),
            "context_summary": phase.get("context_summary") or phase.get("goal") or "No context summary provided.",
            "allowed_files": phase.get("allowed_files") or ["agent_runtime/**", "tests/**", "docs/**"],
            "forbidden_files": phase.get("forbidden_files") or [".env", "agent_runtime/.env", ".git/**"],
            "required_outputs": phase.get("outputs") or [],
            "acceptance_criteria": phase.get("acceptance_criteria") or [],
            "plan_status": phase.get("plan_status", "legacy_ready"),
            "missing_facts": phase.get("missing_facts") or [],
            "must_read_artifacts": phase.get("must_read_artifacts") or [],
            "dispatch_units": phase.get("dispatch_units") or [
                {
                    "phase_id": phase_id,
                    "objective": phase.get("goal"),
                    "executor_type": executor_type,
                }
            ],
            "self_check": self_check,
            "revision_log": phase.get("revision_log") or [],
            "commands_allowed": phase.get("commands_allowed") or ["compileall", "pytest", "agentlab_help"],
            "commands_forbidden": phase.get("commands_forbidden") or ["rm -rf", "git push", "curl", "wget"],
            "evidence_required": phase.get("evidence_required") or [],
            "rollback_required": phase.get("rollback_required", True),
            "cost_policy": phase.get("cost_policy") or "low_cost_only",
            "safety_notes": phase.get("safety_notes") or ["Do not expose credentials.", "Only edit files in the allowed_files list."],
            "repository_handoff": {
                "policy": "config/repository_handoff_policy.yml",
                "must_discover_before_repository_read": True,
                "create_or_request_if_missing": True,
                "safe_inventory_only": True,
                "refresh_after_material_change": True,
                "refresh_before_final_report": True,
            },
        }
    }
    packet["connector_contract"] = build_connector_contract(executor_type, packet["task_packet"])
    
    out_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_yaml(out_dir / "task_packet.yml", packet)
    
    # 2. Generate executor-specific handoff markdown
    from agent_runtime.executors.handoff_renderer import render_handoff
    render_handoff(packet, out_dir)
    
    return packet
