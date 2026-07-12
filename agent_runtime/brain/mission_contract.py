"""Mission contract builder — compiles a rough prompt into mission_contract.yml.

This is the top-level entry point for M1-2 Mission Compiler v2. The default
path is deterministic and rule-based. An optional Hermes/LLM draft can assist
classification, but deterministic validation owns the final contract and falls
back to rules on any failure.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def build_mission_contract(
    prompt: str,
    project_id: str | None = None,
    task_id: str | None = None,
    *,
    agentlab_root: Path | None = None,
    use_llm_assist: bool = False,
    llm_generate: Any | None = None,
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

    # Step 0: optionally ask Hermes for a structured draft. This never becomes
    # authoritative until validated and normalized below.
    llm_draft = (
        _try_compile_llm_mission_draft(prompt, root, llm_generate)
        if use_llm_assist
        else None
    )

    # Step 1: Classify domain
    from agent_runtime.brain.domain_classifier import classify_domain, load_domain_keywords
    from agent_runtime.narrative_intent import classify_narrative_intent

    narrative_intent = classify_narrative_intent(
        prompt,
        active_longform_project=_is_active_longform_content_project(project_id, root),
    )
    domain_keywords = load_domain_keywords(root / "config" / "mission_compiler_v2.yml")
    domain = _validated_legacy_domain(llm_draft) or classify_domain(prompt, domain_keywords)
    explicit_pack_synthesis = _explicit_pack_synthesis_request(prompt)
    explicit_media_domain = _explicit_media_output_domain(prompt)
    if explicit_pack_synthesis:
        domain = "pack_synthesis"
    elif explicit_media_domain:
        domain = explicit_media_domain
    if narrative_intent.kind == "article" and domain == "creative_longform":
        domain = "unknown"

    # Step 2: Classify project type
    from agent_runtime.brain.project_type_classifier import (
        classify_project_type,
        get_project_type_definition,
        load_project_type_keywords,
        load_project_types,
    )

    pt_keywords = load_project_type_keywords(root / "config" / "mission_compiler_v2.yml")
    project_type = _validated_project_type(llm_draft) or classify_project_type(prompt, domain, pt_keywords)
    if explicit_media_domain in {"video_generation", "video_editing"}:
        project_type = "video_generation_project"
    elif explicit_media_domain in {"image_generation", "image_editing"}:
        project_type = "media_generation_project"
    media_domains = {"image_generation", "image_editing", "video_generation", "video_editing", "multimodal"}
    media_project_types = {"video_generation_project", "media_generation_project", "multimodal_content_project"}
    if (
        narrative_intent.is_narrative
        and domain not in media_domains
        and project_type not in media_project_types
    ):
        domain = "creative_longform"
        project_type = "longform_text_project"
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

    domain_pack = _select_domain_pack(domain, project_type, root)
    mission_domain = _mission_domain(domain, domain_pack)
    artifact_type = _artifact_type(domain, project_type, domain_pack, llm_draft)
    route_decision = _build_route_decision(prompt, mission_domain, domain_pack, root)
    media_generation_contract = _media_generation_contract(
        prompt=prompt,
        mission_domain=mission_domain,
        project_id=project_id,
        task_id=task_id,
        root=root,
    )

    contract: dict[str, Any] = {
        "schema_version": 2,
        "mission_flow": [
            "MISSION_INTAKE",
            "DOMAIN_CLASSIFICATION",
            "TASK_CONTRACT_COMPILE",
            "ROUTE_SELECTION_OR_SYNTHESIS",
            "PIPELINE_EXECUTION",
        ],
        "task_id": task_id,
        "project_id": project_id,
        "user_goal": _extract_first_sentence(prompt),
        "intent_summary": _summarize_prompt(prompt),
        "task_type": domain,
        "task_domain": mission_domain,
        "artifact_type": artifact_type,
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
        "memory_contract": _memory_contract(domain_pack),
        "quality_gates": _quality_gates(domain_pack),
        "route_decision": route_decision,
        "route_proposal": route_decision.get("route_proposal", {}),
        "compiler_source": "llm_assisted" if llm_draft else "rule_based",
    }
    if media_generation_contract:
        contract["media_generation_contract"] = media_generation_contract
    return contract


_KNOWN_LEGACY_DOMAINS = {
    "coding",
    "creative_longform",
    "image_generation",
    "image_editing",
    "video_generation",
    "video_editing",
    "research",
    "document_processing",
    "audio_music",
    "multimodal",
    "local_ops",
    "pack_synthesis",
    "unknown",
}

_TASK_DOMAIN_TO_LEGACY_DOMAIN = {
    "creative_writing": "creative_longform",
    "coding": "coding",
    "research_reading": "research",
    "image_generation": "image_generation",
    "image_editing": "image_editing",
    "video_generation": "video_generation",
    "video_editing": "video_editing",
    "multimodal_asset_generation": "multimodal",
    "audio_dsp_experiment": "audio_music",
    "automation_ops": "local_ops",
    "production_pack_synthesis": "pack_synthesis",
    "unknown": "unknown",
}


def _is_active_longform_content_project(project_id: str | None, root: Path) -> bool:
    if not project_id:
        return False
    try:
        from agent_runtime.config_loader import load_yaml

        content_policy = load_yaml(root / "config" / "content_project_governance.yml")
        active = content_policy.get("active_projects", []) if isinstance(content_policy, dict) else []
        if project_id in active:
            return True
        project_contract = load_yaml(root / "projects" / project_id / ".agentlab" / "mission_contract.yml")
        return project_contract.get("task_type") == "creative_longform"
    except Exception:
        return False


def _explicit_media_output_domain(prompt: str) -> str | None:
    lowered = prompt.lower()
    production_verbs = [
        "generate",
        "create",
        "make",
        "produce",
        "render",
        "turn into",
        "制作",
        "生成",
        "做成",
        "做",
        "拍成",
        "转成",
        "产出",
    ]
    # Media prompts in Chinese often omit explicit English-style verbs. Accept
    # concise forms like "做" to avoid false-positive narrative routing.
    if not any(verb in lowered for verb in production_verbs):
        return None
    video_terms = [
        "video",
        "short video",
        "film",
        "animation",
        "storyboard",
        "视频",
        "短视频",
        "连续剧",
        "剧集",
        "动画",
        "影片",
        "分镜",
    ]
    image_terms = [
        "image",
        "poster",
        "comic",
        "illustration",
        "concept art",
        "图片",
        "图像",
        "海报",
        "漫画",
        "图册",
        "插画",
        "设定图",
    ]
    if any(term in lowered for term in video_terms):
        return "video_generation"
    if any(term in lowered for term in image_terms):
        return "image_generation"
    return None


def _explicit_pack_synthesis_request(prompt: str) -> bool:
    lowered = prompt.lower()
    pack_terms = [
        "production pack",
        "task pack",
        "domain pack",
        "生产包",
        "任务包",
        "领域包",
    ]
    governance_terms = [
        "lifecycle",
        "life cycle",
        "memory contract",
        "memory policy",
        "state governance",
        "生命周期",
        "记忆合约",
        "记忆系统",
        "记忆策略",
        "状态治理",
    ]
    creation_terms = [
        "create",
        "build",
        "design",
        "prepare",
        "synthesize",
        "scaffold",
        "创建",
        "构建",
        "设计",
        "准备",
        "生成",
        "合成",
        "封装",
    ]
    return (
        any(term in lowered for term in pack_terms)
        and any(term in lowered for term in governance_terms)
        and any(term in lowered for term in creation_terms)
    )


def _try_compile_llm_mission_draft(
    prompt: str,
    root: Path,
    llm_generate: Any | None = None,
) -> dict[str, Any] | None:
    """Ask Hermes/brain for a structured draft; return None on any failure."""
    messages = _mission_draft_messages(prompt)
    try:
        if llm_generate is not None:
            raw = llm_generate(messages)
            content = raw.content if hasattr(raw, "content") else str(raw)
        else:
            from agent_runtime.config_loader import load_agentlab_configs
            from agent_runtime.llm_provider import generate_text, resolve_llm_settings

            configs = load_agentlab_configs(root)
            settings = resolve_llm_settings(
                agent_name="Supervisor",
                agent_registry=configs.get("agent_registry", {}).get("agents", {}),
                model_providers=configs.get("model_providers", {}),
                model_profiles=configs.get("model_profiles", {}),
                model_catalog=configs.get("model_catalog", {}),
            )
            if not settings.api_key_configured:
                return None
            result = generate_text(settings, configs.get("model_providers", {}), messages)
            content = result.content
        parsed = _parse_json_object(content)
    except Exception:
        return None
    return _validate_llm_mission_draft(parsed)


def _mission_draft_messages(prompt: str) -> list[dict[str, str]]:
    schema = {
        "task_domain": "creative_writing|coding|research_reading|image_generation|image_editing|video_generation|video_editing|multimodal_asset_generation|audio_dsp_experiment|business_delivery|automation_ops|unknown",
        "legacy_domain": "creative_longform|coding|research|image_generation|image_editing|video_generation|video_editing|document_processing|audio_music|multimodal|local_ops|unknown",
        "project_type": "longform_text_project|codebase_build_project|research_archive_project|video_generation_project|media_generation_project|document_knowledgebase_project|multimodal_content_project|local_automation_project|unknown_project",
        "artifact_type": "longform_text|code_patch|cited_report|video_plan|media_generation_contract|audio_experiment_report|business_document|operational_runbook|unknown",
        "quality_gates": ["string"],
        "memory_contract": ["string"],
        "route_proposal": {"route_key": "string", "agents": ["string"]},
    }
    return [
        {
            "role": "system",
            "content": (
                "You are Hermes mission intake. Return only compact JSON. "
                "Classify the user's requested work into the provided schema. "
                "Do not invent executable route keys beyond a route_proposal."
            ),
        },
        {
            "role": "user",
            "content": f"Schema:\n{json.dumps(schema, ensure_ascii=True)}\n\nPrompt:\n{prompt}",
        },
    ]


def _parse_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("mission draft must be a JSON object")
    return data


def _validate_llm_mission_draft(data: dict[str, Any]) -> dict[str, Any] | None:
    legacy = data.get("legacy_domain")
    project_type = data.get("project_type")
    if legacy is not None and legacy not in _KNOWN_LEGACY_DOMAINS:
        return None
    if project_type is not None and not isinstance(project_type, str):
        return None
    draft: dict[str, Any] = {}
    for key in ("task_domain", "legacy_domain", "project_type", "artifact_type"):
        if isinstance(data.get(key), str):
            draft[key] = data[key]
    for key in ("quality_gates", "memory_contract"):
        if isinstance(data.get(key), list) and all(isinstance(item, str) for item in data[key]):
            draft[key] = data[key]
    route = data.get("route_proposal")
    if isinstance(route, dict):
        agents = route.get("agents", [])
        if isinstance(route.get("route_key"), str) and isinstance(agents, list) and all(isinstance(a, str) for a in agents):
            draft["route_proposal"] = {"route_key": route["route_key"], "agents": agents}
    return draft


def _validated_legacy_domain(draft: dict[str, Any] | None) -> str | None:
    if not draft:
        return None
    domain = draft.get("legacy_domain")
    if domain in _KNOWN_LEGACY_DOMAINS:
        return domain
    task_domain = draft.get("task_domain")
    mapped = _TASK_DOMAIN_TO_LEGACY_DOMAIN.get(str(task_domain))
    return mapped if mapped in _KNOWN_LEGACY_DOMAINS else None


def _validated_project_type(draft: dict[str, Any] | None) -> str | None:
    if not draft:
        return None
    project_type = draft.get("project_type")
    return project_type if isinstance(project_type, str) and project_type.endswith("_project") else None


def _load_domain_packs(root: Path) -> dict[str, Any]:
    path = root / "config" / "domain_route_packs.yml"
    from agent_runtime.config_loader import load_yaml

    data = load_yaml(path)
    packs = data.get("domain_packs", {}) if isinstance(data, dict) else {}
    return packs if isinstance(packs, dict) else {}


def _select_domain_pack(domain: str, project_type: str, root: Path) -> dict[str, Any]:
    packs = _load_domain_packs(root)
    for name, pack in packs.items():
        if not isinstance(pack, dict):
            continue
        if domain == name or domain in pack.get("legacy_domains", []):
            return {"name": name, **pack}
    if project_type == "longform_text_project":
        return {"name": "creative_writing", **packs.get("creative_writing", {})}
    return {}


def _mission_domain(domain: str, domain_pack: dict[str, Any]) -> str:
    if domain_pack.get("name"):
        return str(domain_pack["name"])
    aliases = {
        "creative_longform": "creative_writing",
        "research": "research_reading",
        "audio_music": "audio_dsp_experiment",
        "local_ops": "automation_ops",
        "multimodal": "multimodal_asset_generation",
    }
    return aliases.get(domain, domain)


def _artifact_type(
    domain: str,
    project_type: str,
    domain_pack: dict[str, Any],
    draft: dict[str, Any] | None,
) -> str:
    if draft and isinstance(draft.get("artifact_type"), str):
        return draft["artifact_type"]
    if isinstance(domain_pack.get("artifact_type"), str):
        return domain_pack["artifact_type"]
    defaults = {
        "coding": "code_patch",
        "creative_longform": "longform_text",
        "image_generation": "media_generation_contract",
        "image_editing": "media_generation_contract",
        "video_generation": "media_generation_contract",
        "video_editing": "media_generation_contract",
        "multimodal": "media_generation_contract",
        "research": "cited_report",
        "document_processing": "knowledge_base",
        "audio_music": "audio_experiment_report",
        "local_ops": "operational_runbook",
    }
    return defaults.get(domain, project_type.replace("_project", "") or "unknown")


def _memory_contract(domain_pack: dict[str, Any]) -> list[str]:
    values = domain_pack.get("memory_contract", [])
    return [str(item) for item in values] if isinstance(values, list) else []


def _quality_gates(domain_pack: dict[str, Any]) -> list[str]:
    values = domain_pack.get("quality_gates", [])
    return [str(item) for item in values] if isinstance(values, list) else []


def _creative_route_key_for_prompt(prompt: str, domain_pack: dict[str, Any], root: Path) -> tuple[str, str, dict[str, Any]]:
    from agent_runtime.narrative_intent import classify_narrative_intent

    intent = classify_narrative_intent(prompt, active_longform_project=True)
    if intent.kind == "audit":
        return (
            str(domain_pack.get("audit_route") or "narrative_heavy_audit"),
            intent.reason,
            domain_pack.get("audit_route_proposal") or {
                "route_key": "narrative_heavy_audit",
                "agents": ["Supervisor", "Reviewer", "Scribe", "Verifier"],
            },
        )
    if intent.kind == "chapter_batch":
        return (
            str(domain_pack.get("batch_route") or "narrative_batch_chapters"),
            intent.reason,
            domain_pack.get("batch_route_proposal") or {
                "route_key": "narrative_batch_chapters",
                "agents": ["Supervisor", "Writer"],
            },
        )
    return (
        str(domain_pack.get("recommended_route") or "narrative_light_chapter"),
        intent.reason if intent.kind == "chapter" else "creative_writing_light_chapter_default",
        domain_pack.get("route_proposal") or {
            "route_key": "narrative_light_chapter",
            "agents": ["Supervisor", "Writer"],
        },
    )


def _build_route_decision(
    prompt: str,
    mission_domain: str,
    domain_pack: dict[str, Any],
    root: Path,
) -> dict[str, Any]:
    route_key = str(domain_pack.get("recommended_route") or "")
    if mission_domain != "creative_writing":
        decision = {
            "action": "select_existing_route" if route_key else "propose_new_route",
            "selected_route": route_key or None,
            "reason": "domain_pack_recommendation" if route_key else "no_domain_route_available",
        }
        if route_key == "media_generation_task":
            decision["route_proposal"] = domain_pack.get("route_proposal", {})
            decision["reason"] = "media_generation_requires_backend_contract_and_harness"
        return decision

    selected_route, reason, proposal = _creative_route_key_for_prompt(prompt, domain_pack, root)
    if selected_route and _route_exists(root, selected_route):
        return {
            "action": "select_existing_route",
            "selected_route": selected_route,
            "forbidden_routes": domain_pack.get("forbidden_fallback_routes", []),
            "route_proposal": proposal,
            "reason": reason,
        }
    return {
        "action": "refuse_current_route",
        "selected_route": None,
        "refused_routes": domain_pack.get("forbidden_fallback_routes", []),
        "route_proposal": proposal,
        "reason": "creative_writing_route_missing",
    }


def _route_exists(root: Path, route_key: str) -> bool:
    from agent_runtime.routing.route_catalog import RouteCatalog

    return RouteCatalog.from_file(root / "config" / "routing_rules.yml").has_configured_route(route_key)


def _media_generation_contract(
    *,
    prompt: str,
    mission_domain: str,
    project_id: str | None,
    task_id: str | None,
    root: Path,
) -> dict[str, Any] | None:
    from agent_runtime.brain.media_generation_router import (
        build_media_generation_contract,
        is_media_generation_domain,
    )

    if not is_media_generation_domain(mission_domain):
        return None
    return build_media_generation_contract(
        prompt=prompt,
        mission_domain=mission_domain,
        project_id=project_id,
        task_id=task_id,
        root=root,
    )


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
