"""Local OpenClaw integration protocol helpers.

This module is not an OpenClaw SDK. It only builds local protocol data for a
same-host or private Docker-network integration.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import re
import sys

RUNTIME_DIR = Path(__file__).resolve().parent
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from atomic_io import atomic_write_json, safe_read_yaml
from webhook_dispatcher import redact_payload


DEFAULT_ALLOWED_EVENTS = [
    "ACTION_REQUIRED",
    "BLOCKED",
    "STALE_RUNNING",
    "FAILED_RECOVERABLE",
    "COMPLETED",
    "SKILL_REQUEST_PENDING",
    "SKILL_CANDIDATE_READY",
    "SKILL_PROMOTED",
]

DEFAULT_REPLY_MAPPING = {
    "approve": ["A", "approve", "批准", "同意"],
    "reject": ["B", "reject", "拒绝"],
    "stop": ["C", "stop", "停止"],
    "resume": ["resume", "继续"],
    "skip": ["skip", "跳过"],
}


def _default_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_openclaw_local_policy(agentlab_root: Path | None = None) -> dict[str, Any]:
    """Load the local OpenClaw adapter policy with conservative defaults."""
    root = agentlab_root or _default_root()
    policy = safe_read_yaml(root / "config" / "openclaw_local_adapter.yml", default={}) or {}
    policy.setdefault("enabled", False)
    policy.setdefault("mode", "local")
    policy.setdefault("agentlab_invocation", {})
    policy["agentlab_invocation"].setdefault("preferred", "cli")
    policy["agentlab_invocation"].setdefault("cli_path", "./agentlab.sh")
    policy["agentlab_invocation"].setdefault("working_dir", ".")
    policy["agentlab_invocation"].setdefault("allow_mcp_stdio", True)
    policy.setdefault("feedback", {})
    policy["feedback"].setdefault("preferred", "localhost_webhook")
    policy["feedback"].setdefault("localhost_webhook_url_env", "AGENTLAB_OPENCLAW_LOCAL_WEBHOOK_URL")
    policy["feedback"].setdefault("fallback_event_queue", "shared/agentlab_events")
    policy["feedback"].setdefault("allowed_events", list(DEFAULT_ALLOWED_EVENTS))
    policy.setdefault("security", {})
    policy["security"].setdefault("expose_agentlab_publicly", False)
    policy["security"].setdefault("require_localhost_or_private_network", True)
    policy["security"].setdefault("redact_secrets", True)
    policy["security"].setdefault("allow_public_agentlab_api", False)
    policy.setdefault("chat_reply_mapping", dict(DEFAULT_REPLY_MAPPING))
    return policy


def _label_for(option: dict[str, Any]) -> str:
    return str(option.get("label") or option.get("id") or "Option")


def _option_id_for(option: dict[str, Any]) -> str:
    return str(option.get("id") or option.get("option_id") or "")


def _decision_options(decision_card: dict[str, Any]) -> list[dict[str, str]]:
    options = decision_card.get("options") or []
    mapped: list[dict[str, str]] = []
    for index, option in enumerate(options[:3]):
        key = chr(65 + index)
        mapped.append({"key": key, "label": _label_for(option), "option_id": _option_id_for(option)})

    ids = {item["option_id"] for item in mapped}
    if not mapped:
        mapped.append({"key": "A", "label": "Acknowledge", "option_id": "acknowledge"})
    if "reject" not in ids and "stop_task" not in ids and len(mapped) < 3:
        mapped.append({"key": chr(65 + len(mapped)), "label": "Reject", "option_id": "reject"})
    if "stop_task" not in ids and len(mapped) < 3:
        mapped.append({"key": chr(65 + len(mapped)), "label": "Stop task", "option_id": "stop_task"})
    return mapped


def build_openclaw_event_message(payload: dict[str, Any]) -> dict[str, Any]:
    """Convert an AgentLab webhook payload into a chat-display message."""
    event = str(payload.get("event") or "NOTIFICATION")
    task_id = payload.get("task_id")
    decision_card = payload.get("decision_card") or {}
    has_decision = bool(decision_card.get("id"))
    title_event = event.lower().replace("_", " ")
    message = {
        "title": f"AgentLab {title_event}",
        "project": payload.get("project"),
        "task_id": task_id,
        "event": event,
        "summary": payload.get("summary") or payload.get("reason") or title_event,
        "reason": payload.get("reason") or "",
        "decision_id": decision_card.get("id"),
        "options": _decision_options(decision_card) if has_decision else [],
        "raw_payload": redact_payload(payload),
    }
    if not has_decision:
        message["notification"] = True
    return message


def _normalized_reply(reply: str) -> str:
    return re.sub(r"\s+", " ", reply.strip()).casefold()


def _mapping_contains(mapping: dict[str, Any], action: str, reply: str) -> bool:
    normalized = _normalized_reply(reply)
    return any(_normalized_reply(str(item)) == normalized for item in mapping.get(action, []))


def _option_by_key(message: dict[str, Any], key: str) -> dict[str, Any] | None:
    normalized = _normalized_reply(key)
    for option in message.get("options") or []:
        if _normalized_reply(str(option.get("key", ""))) == normalized:
            return option
    return None


def _approval_option(message: dict[str, Any]) -> dict[str, Any] | None:
    options = message.get("options") or []
    for option in options:
        option_id = str(option.get("option_id", ""))
        if option_id.startswith("approve"):
            return option
    return options[0] if options else None


def _reject_option(message: dict[str, Any]) -> dict[str, Any] | None:
    options = message.get("options") or []
    for wanted in ("reject", "stop_task", "skip_action", "skip_skill"):
        for option in options:
            if option.get("option_id") == wanted:
                return option
    return _option_by_key(message, "B")


def parse_openclaw_user_reply(reply: str, message: dict[str, Any]) -> dict[str, Any]:
    """Map an OpenClaw user reply into a local AgentLab action."""
    policy = load_openclaw_local_policy()
    mapping = policy.get("chat_reply_mapping", DEFAULT_REPLY_MAPPING)
    task_id = message.get("task_id")
    decision_id = message.get("decision_id")

    if _mapping_contains(mapping, "resume", reply):
        return {"action": "resume_task", "task_id": task_id}
    if _mapping_contains(mapping, "stop", reply):
        return {"action": "stop_task", "task_id": task_id, "decision_id": decision_id}
    if _mapping_contains(mapping, "skip", reply):
        return {"action": "skip_action", "task_id": task_id, "decision_id": decision_id, "option_id": "skip_action"}

    if _mapping_contains(mapping, "approve", reply):
        option = _approval_option(message)
        if not option or not decision_id:
            return {"action": "error", "error": "No decision option is available to approve.", "reply": reply}
        return {
            "action": "approve_decision",
            "task_id": task_id,
            "decision_id": decision_id,
            "option_id": option.get("option_id"),
        }

    if _mapping_contains(mapping, "reject", reply):
        option = _reject_option(message)
        if not decision_id:
            return {"action": "error", "error": "No decision is available to reject.", "reply": reply}
        return {
            "action": "reject_decision",
            "task_id": task_id,
            "decision_id": decision_id,
            "option_id": (option or {}).get("option_id") or "reject",
        }

    option = _option_by_key(message, reply)
    if option and decision_id:
        option_id = str(option.get("option_id") or "")
        action_name = "reject_decision" if option_id in {"reject", "stop_task"} else "approve_decision"
        return {"action": action_name, "task_id": task_id, "decision_id": decision_id, "option_id": option_id}

    return {"action": "error", "error": f"Unknown OpenClaw reply: {reply}", "reply": reply}


def build_agentlab_cli_command(action: dict[str, Any], project: str) -> list[str]:
    """Build, but do not execute, the AgentLab CLI command for an action."""
    cli_path = load_openclaw_local_policy().get("agentlab_invocation", {}).get("cli_path", "./agentlab.sh")
    name = action.get("action")
    task_id = str(action.get("task_id") or "")
    decision_id = str(action.get("decision_id") or "")
    option_id = str(action.get("option_id") or "")
    if name == "approve_decision":
        return [cli_path, "decision-approve", decision_id, "--project", project, "--task-id", task_id, "--option", option_id]
    if name == "reject_decision":
        return [cli_path, "decision-reject", decision_id, "--project", project, "--task-id", task_id, "--option", option_id or "stop_task"]
    if name == "resume_task":
        return [cli_path, "decision-resume", task_id, "--project", project]
    if name == "stop_task":
        if decision_id:
            return [cli_path, "decision-reject", decision_id, "--project", project, "--task-id", task_id, "--option", "stop_task"]
        return [cli_path, "pause", task_id, "--project", project]
    raise ValueError(f"Unsupported AgentLab CLI action: {name}")


def build_local_event_queue_record(payload: dict[str, Any]) -> dict[str, Any]:
    """Build a redacted local event queue record for OpenClaw polling."""
    redacted_payload = redact_payload(payload)
    message = build_openclaw_event_message(redacted_payload)
    return {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": "agentlab",
        "target": "openclaw",
        "transport": "local_event_queue",
        "event": redacted_payload.get("event"),
        "project": redacted_payload.get("project"),
        "task_id": redacted_payload.get("task_id"),
        "payload": redacted_payload,
        "message": message,
    }


def write_local_event_queue_record(payload: dict[str, Any], queue_dir: Path) -> Path:
    """Write a redacted event queue JSON file and return its path."""
    record = build_local_event_queue_record(payload)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    task_id = str(record.get("task_id") or "project")
    event = str(record.get("event") or "event").lower()
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", f"{timestamp}-{task_id}-{event}.json")
    path = queue_dir / safe_name
    atomic_write_json(path, record)
    return path
