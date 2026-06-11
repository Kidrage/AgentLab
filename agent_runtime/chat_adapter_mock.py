"""Chat Adapter Mock — proves webhook + MCP bidirectional closure without real OpenClaw/Hermes.

This is a test mock, not a production adapter. It demonstrates the protocol:

    AgentLab → Webhook → Chat Agent Mock → User reply → MCP approve/resume → AgentLab
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def receive_webhook_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Simulate receiving a webhook payload from AgentLab.

    Returns a parsed "chat message" with decision options listed.
    """
    event = payload.get("event", "unknown")
    summary = payload.get("summary", "")
    reason = payload.get("reason", summary)
    decision_card = payload.get("decision_card") or {}
    options = decision_card.get("options", [])

    # Mock: format as chat message
    message_lines = [
        f"[AgentLab] {event}: {reason}",
        "",
        "Decision options:",
    ]
    option_map: dict[str, str] = {}
    for i, opt in enumerate(options):
        label = opt.get("label", f"Option {i}")
        opt_id = opt.get("id", "")
        letter = chr(65 + i)  # A, B, C, ...
        option_map[letter] = opt_id
        message_lines.append(f"  [{letter}] {label} ({opt_id})")

    return {
        "event": event,
        "task_id": payload.get("task_id"),
        "project": payload.get("project"),
        "message": "\n".join(message_lines),
        "options": options,
        "option_map": option_map,
        "decision_card": decision_card,
        "raw_payload": payload,
    }


def simulate_user_reply(payload: dict[str, Any], choice: str = "A") -> str:
    """Simulate a user replying with a single letter choice.

    Maps A → first option's id, B → second, etc.
    """
    option_map = payload.get("option_map", {})
    return option_map.get(choice.upper(), "approve_resume")


def call_mcp_handler(
    agentlab_root: Path,
    *,
    tool: str,
    decision_id: str,
    project: str,
    task_id: str,
    option_id: str | None = None,
) -> dict[str, Any]:
    """Simulate calling an MCP-style handler to approve a decision.

    Directly invokes the feedback_manager functions (not via JSON-RPC).
    """
    from feedback_manager import load_decision_card, resolve_decision_card

    run_dir = agentlab_root / "projects" / project / "runs" / task_id
    if not run_dir.exists():
        return {"ok": False, "error": f"Run dir not found: {run_dir}"}

    if tool in ("agentlab_approve_decision", "agentlab_resume_task"):
        try:
            card = resolve_decision_card(
                run_dir,
                decision_id,
                option_id=option_id or "approve_resume",
                resolution="approved",
                actor="chat_adapter_mock",
            )
            return {"ok": True, "decision_id": decision_id, "resolution": "approved", "card": card}
        except (FileNotFoundError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}

    return {"ok": False, "error": f"Unknown tool: {tool}"}


def mock_full_chat_closure(
    agentlab_root: Path,
    *,
    project: str,
    task_id: str,
    webhook_payload: dict[str, Any],
    user_choice: str = "A",
) -> dict[str, Any]:
    """Simulate the full webhook → chat → MCP closure loop.

    1. Receive webhook payload
    2. Parse into chat message
    3. User replies with choice
    4. Map choice to option id
    5. Call MCP handler to approve decision
    6. Verify decision approved
    """
    # Step 1-3: Receive & parse
    chat_msg = receive_webhook_payload(webhook_payload)

    # Step 4: User replies
    option_id = simulate_user_reply(chat_msg, choice=user_choice)

    # Step 5: Call MCP handler
    decision_id = chat_msg.get("decision_card", {}).get("id", "")
    if not decision_id:
        return {"ok": False, "error": "No decision_id in webhook payload", "chat_msg": chat_msg}

    result = call_mcp_handler(
        agentlab_root,
        tool="agentlab_approve_decision",
        decision_id=decision_id,
        project=project,
        task_id=task_id,
        option_id=option_id,
    )

    # Step 6: Verify
    return {
        "ok": result.get("ok", False),
        "chat_message": chat_msg,
        "user_choice": user_choice,
        "resolved_option": option_id,
        "mcp_result": result,
        "steps": [
            "webhook_received",
            "parsed_to_chat",
            f"user_chose_{user_choice}",
            f"mapped_to_option_{option_id}",
            "mcp_approve_called",
            "decision_approved" if result.get("ok") else "mcp_failed",
        ],
    }