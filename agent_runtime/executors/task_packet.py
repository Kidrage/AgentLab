from __future__ import annotations

from pathlib import Path

import yaml

from agent_runtime.atomic_io import atomic_write_yaml
from agent_runtime.executors.connector_contract import build_connector_contract


REQUIRED_PROJECT_BRAIN_FILES = (
    "project_brief.yml",
    "roadmap.yml",
    "acceptance_history.yml",
    "next_actions.yml",
)


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
    project_brain_consumption = _build_project_brain_consumption(phase, phase_plan_path)
    
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
            "artifact_intent": phase.get("artifact_intent") or {},
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
            "project_brain_dir": phase.get("project_brain_dir"),
            "project_brain_consumption": project_brain_consumption,
            "state_contract": phase.get("state_contract") or {},
            "state_outputs_required": phase.get("state_outputs_required") or [],
            "commands_allowed": phase.get("commands_allowed") or ["compileall", "pytest", "agentlab_help"],
            "commands_forbidden": phase.get("commands_forbidden") or ["rm -rf", "git push", "curl", "wget"],
            "evidence_required": phase.get("evidence_required") or [],
            "rollback_required": phase.get("rollback_required", True),
            "cost_policy": phase.get("cost_policy") or "low_cost_only",
            "safety_notes": phase.get("safety_notes") or ["Do not expose credentials.", "Only edit files in the allowed_files list."],
            "repository_handoff": {
                "policy": "config/repository_handoff_policy.yml",
                "project_root_visible_path": "PROJECT_HANDOFF.md",
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


def _build_project_brain_consumption(phase: dict, phase_plan_path: Path) -> dict:
    project_brain_raw = phase.get("project_brain_dir")
    requires_brain = _requires_project_brain(phase)
    if not project_brain_raw:
        if requires_brain:
            raise ValueError("Long-running project dispatch requires project_brain_dir.")
        return {"required": False, "consumed_files": [], "missing_files": []}

    project_brain_dir = Path(str(project_brain_raw))
    if not project_brain_dir.is_absolute():
        project_brain_dir = (phase_plan_path.parent / project_brain_dir).resolve()
    if not project_brain_dir.exists():
        raise ValueError(f"project_brain_dir does not exist: {project_brain_dir}")

    required = list(REQUIRED_PROJECT_BRAIN_FILES)
    if (project_brain_dir / "project_fact_snapshot.yml").exists():
        required.append("project_fact_snapshot.yml")
    if (project_brain_dir / "project_state_contract.yml").exists():
        required.append("project_state_contract.yml")

    consumed_files: list[str] = []
    missing_files: list[str] = []
    for relative in required:
        path = project_brain_dir / relative
        if path.exists():
            consumed_files.append(str(path))
        else:
            missing_files.append(relative)

    if missing_files:
        raise ValueError(f"Project Brain is incomplete; missing: {', '.join(missing_files)}")

    return {
        "required": True,
        "project_brain_dir": str(project_brain_dir),
        "consumed_files": consumed_files,
        "missing_files": [],
    }


def _requires_project_brain(phase: dict) -> bool:
    if phase.get("long_project_governance_required"):
        return True
    if phase.get("project_type") in {"longform_text_project", "codebase_build_project", "video_generation_project"}:
        return True
    if phase.get("plan_status") and phase.get("plan_status") != "legacy_ready":
        return True
    if phase.get("must_read_artifacts") or phase.get("missing_facts"):
        return True
    return bool(phase.get("state_contract", {}).get("transition_proposal_required"))
