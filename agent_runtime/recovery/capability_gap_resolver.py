"""S6 capability gap resolver."""

from __future__ import annotations

from typing import Any


CAPABILITY_ALIASES: dict[str, str] = {
    "web": "web_intelligence",
    "search": "web_intelligence",
    "local_search": "local_search",
    "vision": "vision",
    "image": "vision",
    "video": "vision",
    "audio": "audio",
    "music": "audio",
    "shell": "shell",
    "cli": "shell",
    "external_agent": "external_executor",
    "executor": "external_executor",
    "mcp": "mcp_tooling",
}

DEFAULT_AVAILABLE_CAPABILITIES = {
    "file_read",
    "local_search",
    "web_intelligence_mock",
    "skill_discovery_plan",
    "skill_trust_validation",
    "shell_dry_run",
}


def _capability_name(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("capability") or item.get("name") or "").strip().lower()
    return str(item or "").strip().lower()


def normalize_capability_name(value: str) -> str:
    """Normalize a capability label into a stable family name."""

    lowered = value.strip().lower().replace("-", "_")
    return CAPABILITY_ALIASES.get(lowered, lowered)


def required_capabilities_from_mission(mission: dict[str, Any]) -> list[str]:
    """Extract normalized required capability names from a mission contract."""

    names: list[str] = []
    for item in mission.get("required_capabilities", []) or []:
        raw = _capability_name(item)
        if not raw:
            continue
        normalized = normalize_capability_name(raw)
        if normalized not in names:
            names.append(normalized)
    return names


def build_capability_gap_decision_card(
    mission: dict[str, Any] | None,
    available_capabilities: list[str] | None = None,
) -> dict[str, Any]:
    """Build a decision card for missing mission capabilities."""

    mission = mission or {}
    required = required_capabilities_from_mission(mission)
    available_raw = available_capabilities or sorted(DEFAULT_AVAILABLE_CAPABILITIES)
    available = {normalize_capability_name(item) for item in available_raw}
    missing = [item for item in required if item not in available]

    approval_actions: list[str] = []
    for capability in missing:
        if capability == "vision":
            approval_actions.append("ask_user_for_image_or_vision_capability_install")
        elif capability == "audio":
            approval_actions.append("ask_user_for_audio_file_or_transcription_capability")
        elif capability == "web_intelligence":
            approval_actions.append("ask_user_to_approve_live_web_or_provide_sources")
        elif capability == "shell":
            approval_actions.append("ask_user_to_approve_specific_shell_commands")
        elif capability == "external_executor":
            approval_actions.append("ask_user_to_approve_external_agent_handoff")
        elif capability == "mcp_tooling":
            approval_actions.append("ask_user_to_configure_or_approve_mcp_tool")
        else:
            approval_actions.append(f"ask_user_to_approve_capability:{capability}")

    return {
        "schema_version": 1,
        "status": "blocked" if missing else "ready",
        "required_capabilities": required,
        "available_capabilities": sorted(available),
        "missing_capabilities": missing,
        "human_decision_required": bool(missing),
        "recommended_actions": approval_actions or ["continue_with_current_capabilities"],
        "safety": {
            "no_install_without_approval": True,
            "no_external_execution_without_approval": True,
            "mock_first": True,
        },
    }