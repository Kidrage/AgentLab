"""Mission contract builder — compiles a rough prompt into mission_contract.yml.

This is the top-level entry point for M1-2 Mission Compiler v2.
All components are deterministic, rule-based, no LLM calls.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def build_mission_contract(
    prompt: str,
    project_id: str | None = None,
    task_id: str | None = None,
    *,
    agentlab_root: Path | None = None,
) -> dict[str, Any]:
    """Compile a rough user prompt into a structured mission contract v2.

    Args:
        prompt: The raw user prompt / project request text.
        project_id: Optional project identifier.
        task_id: Optional task identifier.
        agentlab_root: Path to AgentLab root dir (for config loading).

    Returns:
        A dict conforming to the mission_contract v2 schema.
    """
    root = agentlab_root or Path(__file__).resolve().parents[2]

    # Step 1: Classify domain
    from agent_runtime.brain.domain_classifier import classify_domain, load_domain_keywords

    domain_keywords = load_domain_keywords(root / "config" / "mission_compiler_v2.yml")
    domain = classify_domain(prompt, domain_keywords)

    # Step 2: Classify project type
    from agent_runtime.brain.project_type_classifier import (
        classify_project_type,
        get_project_type_definition,
        load_project_type_keywords,
        load_project_types,
    )

    pt_keywords = load_project_type_keywords(root / "config" / "mission_compiler_v2.yml")
    project_type = classify_project_type(prompt, domain, pt_keywords)
    project_types = load_project_types(root / "config" / "project_type_classifier.yml")
    typedef = get_project_type_definition(project_type, project_types)

    # Step 3: Estimate scale (use heuristic for "unknown")
    raw_scale = typedef.get("estimated_scale", "unknown")
    scale = raw_scale if raw_scale not in ("unknown", "", None) else _estimate_scale(prompt)

    # Step 4: Build capability requirements
    from agent_runtime.brain.capability_requirement_builder import build_capability_requirements

    cap_reqs = build_capability_requirements(project_type, project_types)

    # Step 5: Build artifact targets
    from agent_runtime.brain.artifact_contract_builder import build_artifact_target_summary

    artifact_targets = build_artifact_target_summary(project_type, project_types)

    # Step 6: Build phase list
    phases = _build_phase_list(typedef)

    # Step 7: Classify risks
    from agent_runtime.brain.risk_classifier import classify_risks

    risks = classify_risks(prompt, project_type, project_types)

    # Step 8: Build acceptance gates
    from agent_runtime.brain.acceptance_gate_builder import build_acceptance_gates

    acceptance_gates = build_acceptance_gates(project_type)

    # Step 9: Build decision cards
    from agent_runtime.brain.decision_card_builder import build_decision_cards

    decision_cards = build_decision_cards(
        project_type=project_type,
        risk_flags=risks["risk_flags"],
        non_goal_hits=risks["non_goal_hits"],
        capability_gaps=cap_reqs["gaps"],
        project_types=project_types,
    )

    # Step 10: Assemble mission contract
    is_long = bool(typedef.get("is_long_project", False))
    from agent_runtime.long_project_governance import build_project_governance_pack

    long_governance = (
        build_project_governance_pack(root, project_type)
        if is_long
        else {"enabled": False, "project_type": project_type}
    )

    contract: dict[str, Any] = {
        "schema_version": 2,
        "task_id": task_id,
        "project_id": project_id,
        "user_goal": _extract_first_sentence(prompt),
        "intent_summary": _summarize_prompt(prompt),
        "task_type": domain,
        "project_type": project_type,
        "is_long_project": is_long,
        "estimated_scale": scale,
        "non_goals": risks["non_goal_hits"],
        "hard_constraints": risks["constraint_hits"],
        "soft_preferences": [],
        "unknowns": _detect_unknowns(prompt, project_type),
        "assumptions": _build_assumptions(project_type, typedef),
        "required_capabilities": cap_reqs["required"],
        "required_artifacts": artifact_targets,
        "long_project_governance": long_governance,
        "acceptance_gates": [gate.get("gate_id", "") for gate in acceptance_gates],
        "risk_flags": risks["risk_flags"],
        "external_executor_needed": bool(typedef.get("external_executor_recommended", False)),
        "asset_registry_recommended": bool(typedef.get("asset_registry_recommended", False)),
        "human_approval_required": True,
        "decision_cards": [card.get("decision_id", "") for card in decision_cards],
    }
    return contract


def _estimate_scale(prompt: str) -> str:
    """Heuristic scale estimation based on word count and phase count signals."""
    words = len(prompt.split())
    if words < 80:
        return "small"
    if words < 300:
        return "medium"
    return "large"


def _extract_first_sentence(text: str) -> str:
    """Extract first sentence as the user goal summary."""
    text = text.strip()
    for end in (". ", ".\n", "?\n", "!\n", "? ", "! "):
        idx = text.find(end)
        if idx > 10:
            return text[: idx + 1].strip()
    # If multiline, take first non-empty line
    for line in text.splitlines():
        line = line.strip()
        if len(line) > 10:
            return line[:200]
    return text[:200]


def _summarize_prompt(prompt: str) -> str:
    """Create a brief intent summary from the prompt."""
    prompt = prompt.strip()
    # Take first ~150 chars for summary
    if len(prompt) <= 150:
        return prompt
    return prompt[:147].rsplit(" ", 1)[0] + "..."


def _build_phase_list(typedef: dict[str, Any]) -> list[dict[str, Any]]:
    """Build structured phase list from project type definition."""
    phase_names = typedef.get("canonical_phases", [])
    return [
        {
            "phase_id": f"phase_{i + 1:02d}",
            "title": name,
            "goal": f"Complete {name.replace('_', ' ')}",
        }
        for i, name in enumerate(phase_names)
    ]


def _detect_unknowns(prompt: str, project_type: str) -> list[str]:
    """Detect what's unknown or underspecified in the prompt."""
    unknowns: list[str] = []
    lowered = prompt.lower()
    if project_type == "unknown_project":
        unknowns.append("project_type_could_not_be_determined")
    if "?" not in prompt:
        unknowns.append("no_explicit_questions_in_prompt")
    if len(prompt.split()) < 20:
        unknowns.append("very_short_prompt_may_be_underspecified")
    # Check for common missing info
    if "deadline" not in lowered and "timeline" not in lowered and "date" not in lowered:
        unknowns.append("no_timeline_or_deadline_specified")
    return unknowns


def _build_assumptions(project_type: str, typedef: dict[str, Any]) -> list[str]:
    """Build list of reasonable assumptions based on project type."""
    assumptions: list[str] = []
    if project_type == "codebase_build_project":
        assumptions.extend([
            "project_uses_git_for_version_control",
            "tests_are_expected",
            "code_review_is_part_of_workflow",
        ])
    elif project_type == "longform_text_project":
        assumptions.extend([
            "content_is_original_not_plagiarized",
            "multiple_revisions_expected",
            "human_review_before_final",
        ])
    elif project_type == "video_generation_project":
        assumptions.extend([
            "external_video_tools_may_be_needed",
            "storyboard_review_before_production",
            "script_approval_required",
        ])
    elif project_type == "research_archive_project":
        assumptions.extend([
            "sources_must_be_cited",
            "peer_review_or_quality_check_needed",
            "copyright_compliance_required",
        ])
    elif project_type == "document_knowledgebase_project":
        assumptions.extend([
            "documents_are_legally_accessible",
            "extraction_quality_varies_by_format",
            "index_needs_human_review",
        ])
    elif project_type == "local_automation_project":
        assumptions.extend([
            "dry_run_before_live_execution",
            "rollback_plan_exists",
            "scope_is_limited_to_local_filesystem",
        ])
    if typedef.get("external_executor_recommended", False):
        assumptions.append("external_executor_requires_approval")
    return assumptions
