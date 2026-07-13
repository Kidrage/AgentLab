"""Frontdesk handoff for live AgentLab acceptance work.

This report is intentionally read-only. It translates live unblock items into
frontdesk-safe submit/observe actions so the chat operator does not become the
Writer or ArtifactProducer.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

try:
    from agent_runtime.report_sanitizer import write_report_yaml
except ModuleNotFoundError:  # pragma: no cover - direct script path
    from report_sanitizer import write_report_yaml


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _contains_secret_text(data: dict[str, Any]) -> bool:
    rendered = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    return "sk-" in rendered or "test-key" in rendered


def _item_by_id(items: list[dict[str, Any]], item_id: str) -> dict[str, Any]:
    return next((item for item in items if item.get("id") == item_id), {})


def _item_by_any_id(items: list[dict[str, Any]], *item_ids: str) -> dict[str, Any]:
    for item_id in item_ids:
        item = _item_by_id(items, item_id)
        if item:
            return item
    return {}


def _command_for(item: dict[str, Any]) -> str:
    if item.get("agentlab_command"):
        return str(item["agentlab_command"])
    if item.get("safe_command_after_approval"):
        return str(item["safe_command_after_approval"])
    commands = item.get("agentlab_commands") or []
    if len(commands) > 1:
        return str(commands[1])
    if commands:
        return str(commands[0])
    commands = item.get("safe_commands_after_approval") or []
    if len(commands) > 1:
        return str(commands[1])
    if commands:
        return str(commands[0])
    return ""


def _current_writer_item(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize a retained legacy handoff to the current Writer worker."""
    current = dict(item)
    for field in ("agentlab_command", "safe_command_after_approval"):
        command = str(current.get(field) or "")
        if command:
            current[field] = command.replace(
                "--writer-worker agy",
                "--writer-worker claude_code",
            )
    return current


def _handoff_item(
    item: dict[str, Any],
    *,
    role: str,
    worker: str,
    observe_artifacts: list[str],
) -> dict[str, Any]:
    command = _command_for(item)
    return {
        "id": item.get("id"),
        "status": item.get("status"),
        "frontdesk_action": "submit_agentlab_role_session_and_monitor_artifacts",
        "frontdesk_must_not": [
            "generate or edit the production content directly",
            "claim provider output without AgentLab role-session evidence",
            "promote generated candidates without the configured acceptance gate",
        ],
        "agentlab_execution_owner": role,
        "assigned_worker": worker,
        "role_session_required": True,
        "role_session_evidence": "agentlab_role_session",
        "operator_action_required": item.get("required_operator_action") or item.get("required_user_action"),
        "user_approval_required": bool(item.get("required_user_action")),
        "agentlab_command": command,
        "agentlab_command_after_approval": command,
        "observe_artifacts": observe_artifacts,
    }


def build_frontdesk_live_handoff(root: Path, frontdesk_agent: str = "hermes") -> dict[str, Any]:
    """Build a frontdesk-safe handoff from the current live unblock plan."""
    root = root.resolve()
    unblock_path = root / "acceptance_runs" / "agentlab_capability_acceptance" / "live_unblock_plan.yml"
    policy_path = root / "config" / "frontdesk_policy.yml"
    unblock = _read_yaml(unblock_path)
    policy = _read_yaml(policy_path)
    items = [item for item in unblock.get("items", []) if isinstance(item, dict)]
    crown = _current_writer_item(
        _item_by_any_id(
            items,
            "run_crown_internal_writer_eval",
            "approve_crown_external_writer_context",
        )
    )
    media = _item_by_any_id(items, "run_crown_internal_media_smoke", "approve_crown_media_grok_oauth_context")
    runtime_boundary = policy.get("external_runtime_boundary") or {}
    default_frontdesk = policy.get("default_frontdesk") or {}
    direct_closed_loop = (policy.get("execution_paths") or {}).get("direct_closed_loop") or {}

    handoff_items = [
        _handoff_item(
            crown,
            role="Writer",
            worker="claude_code",
            observe_artifacts=[
                "acceptance_runs/narrative_eval/Crown_of_Ash/*/longform_eval_report.yml",
                "projects/Crown_of_Ash/runs/task_narrative_eval_*/fiction_draft.md",
                "projects/Crown_of_Ash/runs/task_narrative_eval_*/narrative_delivery_receipt.yml",
                "projects/Crown_of_Ash/runs/task_narrative_eval_*/live_generation_error.yml",
            ],
        ),
        _handoff_item(
            media,
            role="ArtifactProducer",
            worker="grok",
            observe_artifacts=[
                "projects/Crown_of_Ash/runs/task_probe_crown_comic_video_poster_series_scaffold_20260707/artifacts/*/generation_ledger.yml",
                "projects/Crown_of_Ash/runs/task_probe_crown_comic_video_poster_series_scaffold_20260707/artifacts/*/media_backend_preflight.yml",
                "projects/Crown_of_Ash/runs/task_probe_crown_comic_video_poster_series_scaffold_20260707/media_qc_report.yml",
                "projects/Crown_of_Ash/runs/task_probe_crown_comic_video_poster_series_scaffold_20260707/narrative_media_delivery_receipt.yml",
            ],
        ),
    ]

    checks = [
        {
            "id": "frontdesk_is_not_execution_worker",
            "status": "pass"
            if "implement_task_itself" in (policy.get("forbidden_actions") or [])
            else "fail",
            "summary": "frontdesk policy forbids implementing task content itself",
        },
        {
            "id": "canonical_frontdesk_is_hermes_deepseek_v4_pro",
            "status": "pass"
            if frontdesk_agent == "hermes"
            and default_frontdesk.get("agent_id") == "hermes"
            and default_frontdesk.get("model_key") == "deepseek_v4_pro"
            else "fail",
            "summary": "routed task intake uses Hermes CLI with DeepSeek V4 Pro",
        },
        {
            "id": "direct_closed_loop_can_skip_frontdesk",
            "status": "pass" if direct_closed_loop.get("frontdesk_required") is False else "fail",
            "summary": "declared AgentLab pipelines can run and be accepted without a FrontDesk session",
        },
        {
            "id": "sandbox_approval_kept_outside_agentlab_chain",
            "status": "pass"
            if runtime_boundary.get("sandbox_approvals_are_agentlab_roles") is False
            and runtime_boundary.get("sandbox_approvals_are_agentlab_workflow_nodes") is False
            else "fail",
            "summary": "host sandbox approval is recorded as external runtime policy",
        },
        {
            "id": "writer_command_has_role_session_worker",
            "status": "pass"
            if "--writer-worker claude_code"
            in handoff_items[0].get("agentlab_command", "")
            else "fail",
            "summary": "Crown Writer live command creates Writer role-session evidence",
        },
        {
            "id": "media_command_has_artifact_producer_worker",
            "status": "pass"
            if "--role ArtifactProducer --worker grok" in handoff_items[1].get("agentlab_command", "")
            else "fail",
            "summary": "Crown media live command creates ArtifactProducer role-session evidence through the Grok CLI worker",
        },
        {
            "id": "secret_values_not_rendered",
            "status": "pass" if not _contains_secret_text({"unblock": unblock, "handoff": handoff_items}) else "fail",
            "summary": "handoff contains no rendered API keys or test secrets",
        },
    ]
    issues = [check for check in checks if check["status"] != "pass"]
    return {
        "schema_version": 1,
        "report_type": "agentlab_frontdesk_live_handoff",
        "root": str(root),
        "frontdesk_agent": frontdesk_agent,
        "status": "ready_for_agentlab_submission" if not issues else "fail",
        "source_reports": {"live_unblock_plan": str(unblock_path), "frontdesk_policy": str(policy_path)},
        "boundary": {
            "frontdesk_role": "optional_submit_and_observe_only",
            "canonical_frontdesk": default_frontdesk,
            "direct_closed_loop_supported": direct_closed_loop.get("frontdesk_required") is False,
            "agentlab_owns_execution": True,
            "sandbox_approval_is_external_runtime_boundary": True,
            "current_live_items_are_internal_role_sessions": unblock.get("workflow_boundary") == "internal_agentlab_role_sessions",
        },
        "items": handoff_items,
        "checks": checks,
        "issues": issues,
        "notes": [
            "This handoff does not call external providers.",
            "Commands execute as AgentLab role-session work; Hermes FrontDesk may submit and observe but is optional for direct closed-loop validation.",
        ],
    }


def write_frontdesk_live_handoff(
    root: Path,
    out: Path,
    frontdesk_agent: str = "hermes",
) -> dict[str, Any]:
    report = build_frontdesk_live_handoff(root, frontdesk_agent=frontdesk_agent)
    write_report_yaml(out, report, root)
    return report
