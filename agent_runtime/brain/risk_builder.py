"""Deterministic risk builder for AgentLab S1-C/D/E/F."""

from __future__ import annotations

import re

from .domain_workflows import DomainWorkflowTemplate


PROMPT_RISK_SIGNALS: tuple[tuple[re.Pattern[str], tuple[str, ...]], ...] = (
    (re.compile(r"\b(ci|github actions|pytest|test|bug|repo|repository|patch|code)\b", re.I), ("regression_risk",)),
    (re.compile(r"\b(latest|current|today|market|company|competitor|source|citation)\b", re.I), ("stale_source_risk", "fake_citation_risk")),
    (re.compile(r"\b(pdf|ocr|image|scan|table)\b", re.I), ("OCR_quality_risk",)),
    (re.compile(r"\b(screenshot|image|video|photo|visual|diagram|frame)\b", re.I), ("visual_hallucination_risk", "missing_frame_or_page_reference_risk")),
    (re.compile(r"\b(audio|music|hrtf|spatial|binaural|loudness|mix|master)\b", re.I), ("subjective_evaluation_risk", "playback_environment_mismatch_risk")),
    (re.compile(r"\b(delete|remove|cleanup|clean up|move|overwrite|filesystem|local file|folder)\b", re.I), ("destructive_change_risk", "rollback_failure_risk", "path_scope_risk")),
)

RISKS_BY_TASK_TYPE: dict[str, tuple[str, ...]] = {
    "coding": (
        "regression_risk",
        "insufficient_test_coverage",
        "local_path_or_secret_leak_risk",
    ),
    "debugging": (
        "regression_risk",
        "insufficient_test_coverage",
        "local_path_or_secret_leak_risk",
    ),
    "research": (
        "stale_source_risk",
        "fake_citation_risk",
        "source_quality_risk",
    ),
    "business": (
        "stale_source_risk",
        "fake_citation_risk",
        "source_quality_risk",
    ),
    "creative_longform": (
        "continuity_drift_risk",
        "tone_mismatch_risk",
        "premature_draft_without_outline_risk",
    ),
    "document_processing": (
        "extraction_error_risk",
        "table_structure_loss_risk",
    ),
    "data_analysis": (
        "dirty_data_risk",
        "schema_mismatch_risk",
        "misleading_chart_risk",
    ),
    "audio_music": (
        "subjective_evaluation_risk",
        "playback_environment_mismatch_risk",
        "artifact_loudness_or_clipping_risk",
    ),
    "multimodal": (
        "visual_hallucination_risk",
        "OCR_error_risk",
        "missing_frame_or_page_reference_risk",
    ),
    "local_ops": (
        "destructive_change_risk",
        "rollback_failure_risk",
        "path_scope_risk",
    ),
    "unknown": (
        "ambiguous_goal_risk",
        "capability_gap_risk",
    ),
}

CAPABILITY_GAP_RISK_CAPABILITIES = {
    "web_search",
    "source_citation",
    "audio_analysis",
    "image_understanding",
    "video_understanding",
    "skill_discovery",
}


def _normalize_task_type(task_type: str) -> str:
    """Normalize enum-like task type values."""

    value = getattr(task_type, "value", task_type)
    return str(value or "unknown").strip().lower() or "unknown"


def _dedupe(items: list[str]) -> list[str]:
    """Deduplicate risk names while preserving stable order."""

    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _prompt_risks(prompt: str) -> list[str]:
    """Add prompt-specific risks from deterministic keyword signals."""

    risks: list[str] = []
    for pattern, names in PROMPT_RISK_SIGNALS:
        if pattern.search(prompt):
            risks.extend(names)
    return risks


def _capability_risks(required_capabilities: list[str]) -> list[str]:
    """Add capability-gap risk when compile-time requirements exceed S1 runtime."""

    if any(capability in CAPABILITY_GAP_RISK_CAPABILITIES for capability in required_capabilities):
        return ["capability_gap_risk"]
    return []


def build_risks(
    user_prompt: str,
    task_type: str,
    required_capabilities: list[str],
    domain_template: DomainWorkflowTemplate | None = None,
) -> list[str]:
    """Build deterministic risk names for a compiled mission.

    Risks are strings at this layer. The Task Compiler maps them to
    ``MissionRisk`` entries when storing them in a MissionContract.
    """

    normalized = _normalize_task_type(task_type)
    risks: list[str] = []
    risks.extend(RISKS_BY_TASK_TYPE.get(normalized, RISKS_BY_TASK_TYPE["unknown"]))
    if domain_template is not None:
        risks.extend(domain_template.risk_defaults)
    risks.extend(_prompt_risks(str(user_prompt or "")))
    risks.extend(_capability_risks(required_capabilities))
    if normalized in {"research", "business"}:
        risks.extend(["stale_source_risk", "fake_citation_risk", "source_quality_risk"])
    if normalized == "creative_longform":
        risks.append("premature_draft_without_outline_risk")
    if normalized == "document_processing" and re.search(r"\b(ocr|image|scan|pdf)\b", user_prompt, re.I):
        risks.append("OCR_quality_risk")
    if normalized == "audio_music":
        risks.append("subjective_evaluation_risk")
    if normalized == "multimodal":
        risks.extend(["visual_hallucination_risk", "missing_frame_or_page_reference_risk"])
    if normalized == "local_ops":
        risks.extend(["destructive_change_risk", "rollback_failure_risk", "path_scope_risk"])
    if normalized == "unknown":
        risks.extend(["ambiguous_goal_risk", "capability_gap_risk"])
    return _dedupe(risks)


def risk_level_for_name(risk_name: str) -> str:
    """Map a risk string to a simple MissionRisk level."""

    high_risks = {
        "destructive_change_risk",
        "rollback_failure_risk",
        "fake_citation_risk",
        "visual_hallucination_risk",
        "capability_gap_risk",
    }
    medium_risks = {
        "regression_risk",
        "insufficient_test_coverage",
        "stale_source_risk",
        "source_quality_risk",
        "OCR_quality_risk",
        "schema_mismatch_risk",
        "subjective_evaluation_risk",
        "playback_environment_mismatch_risk",
        "path_scope_risk",
        "ambiguous_goal_risk",
    }
    if risk_name in high_risks:
        return "high"
    if risk_name in medium_risks:
        return "medium"
    return "low"


def risk_description_for_name(risk_name: str) -> str:
    """Create a readable MissionRisk description from a stable risk id."""

    return risk_name.replace("_", " ").rstrip(" risk") + " risk"


def risk_mitigation_for_name(risk_name: str) -> str:
    """Create a simple mitigation string for a risk id."""

    mitigations = {
        "regression_risk": "Run relevant tests and summarize changed files before acceptance.",
        "insufficient_test_coverage": "Record test coverage limits and require manual review for untested paths.",
        "local_path_or_secret_leak_risk": "Review diff and artifacts for secrets or local absolute paths.",
        "stale_source_risk": "Collect fresh sources and record access dates before final claims.",
        "fake_citation_risk": "Verify every citation against a real source ledger.",
        "source_quality_risk": "Label source quality, bias, and limitations.",
        "continuity_drift_risk": "Use outline and continuity ledger before longform drafting.",
        "tone_mismatch_risk": "Check output against requested tone, audience, and style.",
        "premature_draft_without_outline_risk": "Require outline or structure before final draft.",
        "extraction_error_risk": "Keep extracted content separate from interpretation and run quality checks.",
        "table_structure_loss_risk": "Validate table outputs against source page or section references.",
        "OCR_quality_risk": "Mark OCR uncertainty and preserve page/image provenance.",
        "dirty_data_risk": "Profile data quality and record cleaning decisions.",
        "schema_mismatch_risk": "Confirm schema and columns before analysis.",
        "misleading_chart_risk": "Add chart caveats and distinguish evidence from interpretation.",
        "subjective_evaluation_risk": "Separate listening notes from objective measurements.",
        "playback_environment_mismatch_risk": "Document playback target and evaluation environment.",
        "artifact_loudness_or_clipping_risk": "Record loudness or clipping caveats before acceptance.",
        "visual_hallucination_risk": "Tie every visual claim to an input artifact and uncertainty label.",
        "OCR_error_risk": "Separate OCR text from interpretation and mark uncertain text.",
        "missing_frame_or_page_reference_risk": "Record screenshot, frame, page, or artifact reference.",
        "destructive_change_risk": "Require dry-run, explicit approval, and rollback plan.",
        "rollback_failure_risk": "Create rollback notes before filesystem changes.",
        "path_scope_risk": "Constrain and confirm path scope before local operations.",
        "ambiguous_goal_risk": "Ask for clarification or use a safe minimal plan.",
        "capability_gap_risk": "Represent unsupported capability as a decision card and require approval.",
    }
    return mitigations.get(risk_name, "Record the risk and require review before execution.")
