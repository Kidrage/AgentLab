from __future__ import annotations


def build_connector_contract(executor_type: str, task_packet: dict) -> dict:
    external = executor_type in {"codex", "cline", "claude_code", "human_contractor", "generic_patch_submitter"}
    return {
        "executor_type": executor_type,
        "phase_id": task_packet.get("phase_id"),
        "auto_execute": False if external else executor_type == "mock_executor",
        "requires_human_approval": external,
        "result_contract": "execution_result_envelope.yml",
        "evidence_required": task_packet.get("evidence_required") or [],
        "policy": {
            "network_allowed": False,
            "shell_allowed": False,
            "external_agent_dispatch_allowed": False,
        },
    }
