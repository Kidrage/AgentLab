"""Lightweight agent packet contract."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

import yaml

from .models import AgentPacket


def packet_from_dict(data: dict[str, Any]) -> AgentPacket:
    packet = AgentPacket(
        packet_id=str(data.get("packet_id", "")),
        project_id=str(data.get("project_id", "")),
        task_id=str(data.get("task_id", "")),
        sender=str(data.get("sender", "")),
        receiver=str(data.get("receiver", "")),
        purpose=str(data.get("purpose", "")),
        max_context_budget_tokens=int(data.get("max_context_budget_tokens", 1200)),
        must_read=list(data.get("must_read", [])),
        summary=dict(data.get("summary", {})),
        requested_action=dict(data.get("requested_action", {})),
        forbidden=list(data.get("forbidden", [])),
    )
    packet.validate()
    return packet


def write_agent_packet(packet: AgentPacket, path: Path) -> None:
    packet.validate()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(asdict(packet), sort_keys=False, allow_unicode=True), encoding="utf-8")


def load_agent_packet(path: Path) -> AgentPacket:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return packet_from_dict(data)


def render_agent_packet_markdown(packet: AgentPacket) -> str:
    packet.validate()
    lines = [
        "# Agent Packet",
        "",
        f"- Packet: `{packet.packet_id}`",
        f"- Project: `{packet.project_id}`",
        f"- Task: `{packet.task_id}`",
        f"- Sender: `{packet.sender}`",
        f"- Receiver: `{packet.receiver}`",
        f"- Purpose: `{packet.purpose}`",
        f"- Context budget: {packet.max_context_budget_tokens} tokens",
        "",
        "## Must Read",
        "",
    ]
    lines.extend(f"- `{item}`" for item in packet.must_read)
    lines.extend(["", "## Summary", ""])
    for key, value in packet.summary.items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Requested Action", ""])
    for key, value in packet.requested_action.items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Forbidden", ""])
    lines.extend(f"- {item}" for item in packet.forbidden)
    lines.append("")
    return "\n".join(lines)
