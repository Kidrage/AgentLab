"""S1-B deterministic Task Compiler MVP for AgentLab.

The compiler turns a raw user request into a structured MissionContract without
executing tools, browsing the web, calling external providers, or mutating the
runtime task lifecycle.  It is a local-first bridge between free-form user intent
and the S1-A MissionContract schema.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import re
from pathlib import Path
from typing import Any

from .acceptance_builder import build_acceptance_gates
from .assumption_builder import build_assumptions_and_unknowns
from .artifact_builder import build_required_artifacts
from .domain_signals import classify_task_type
from .domain_workflows import (
    DomainWorkflowTemplate,
    load_domain_workflow_templates,
    select_domain_workflow,
    template_note,
)
from .mission_contract import (
    MissionAssumption,
    MissionCapabilityRequirement,
    MissionContract,
    MissionHumanApproval,
    MissionRisk,
    MissionTaskType,
    validate_mission_contract,
    write_mission_contract,
)
from .risk_builder import (
    build_risks as build_domain_risks,
    risk_description_for_name,
    risk_level_for_name,
    risk_mitigation_for_name,
)


SUPPORTED_CAPABILITIES = {
    "file_read",
    "file_write",
    "code_edit",
    "repo_inspection",
    "test_execution",
    "long_document_reading",
    "spreadsheet_processing",
    "data_analysis",
    "local_shell",
    "human_approval",
}

UNIMPLEMENTED_CAPABILITY_NOTE = (
    "Capability is represented in the contract even if no AgentLab runtime "
    "implementation is available in S1-B."
)

CAPABILITIES_BY_TYPE: dict[MissionTaskType, tuple[tuple[str, str], ...]] = {
    MissionTaskType.CODING: (
        ("file_read", "Inspect repository files relevant to the requested code change."),
        ("file_write", "Write deterministic local artifacts and patches."),
        ("repo_inspection", "Map repository structure, branch state, and affected modules."),
        ("code_edit", "Apply the smallest safe code change."),
        ("test_execution", "Run targeted compile, lint, or test checks after editing."),
    ),
    MissionTaskType.DEBUGGING: (
        ("file_read", "Inspect failing code, tests, logs, or traces."),
        ("file_write", "Write deterministic local artifacts and repair patches."),
        ("repo_inspection", "Find failure context and affected modules."),
        ("code_edit", "Patch the root cause without unrelated refactors."),
        ("test_execution", "Reproduce and verify the failing behavior."),
    ),
    MissionTaskType.RESEARCH: (
        ("web_search", "Collect current sources before making factual claims."),
        ("source_citation", "Cite and ledger sources for nontrivial factual claims."),
        ("long_document_reading", "Review source material and evidence notes."),
    ),
    MissionTaskType.BUSINESS: (
        ("web_search", "Collect current company, market, and industry sources."),
        ("source_citation", "Cite sources for business and market claims."),
        ("long_document_reading", "Read reports, pages, filings, or market notes."),
    ),
    MissionTaskType.CREATIVE_LONGFORM: (
        ("file_write", "Write outline, draft, continuity, and revision artifacts."),
        ("long_document_reading", "Track longform context and continuity."),
        ("human_approval", "Confirm outline or direction before longform finalization when needed."),
    ),
    MissionTaskType.DOCUMENT_PROCESSING: (
        ("file_read", "Read supplied document files or extracted text."),
        ("file_write", "Write parsed content, tables, quality checks, and summaries."),
        ("long_document_reading", "Process longer document inputs safely."),
    ),
    MissionTaskType.DATA_ANALYSIS: (
        ("file_read", "Read local datasets or spreadsheet exports."),
        ("file_write", "Write profiles, cleaning logs, scripts, charts, and findings."),
        ("spreadsheet_processing", "Handle spreadsheet inputs when present."),
        ("data_analysis", "Profile, clean, analyze, and report structured data."),
    ),
    MissionTaskType.AUDIO_MUSIC: (
        ("file_read", "Read provided audio asset manifests or local asset references."),
        ("file_write", "Write audio briefs, plans, reports, and validation notes."),
        ("audio_analysis", "Analyze audio, music, stems, loudness, HRTF, or spatial properties."),
    ),
    MissionTaskType.MULTIMODAL: (
        ("file_read", "Read supplied image, screenshot, or video artifacts."),
        ("file_write", "Write observations, extracted text, and visual summaries."),
        ("image_understanding", "Interpret images, screenshots, figures, diagrams, or photos."),
    ),
    MissionTaskType.LOCAL_OPS: (
        ("file_read", "Inspect scoped local paths before changes."),
        ("file_write", "Write operation plans, manifests, and reports."),
        ("local_shell", "Run local shell commands only after approval and dry-run gates."),
        ("human_approval", "Require approval for destructive or filesystem operations."),
    ),
    MissionTaskType.EDUCATION: (
        ("file_write", "Write lesson, explanation, practice, and answer-key artifacts."),
        ("human_approval", "Confirm learner assumptions when ambiguous."),
    ),
    MissionTaskType.UNKNOWN: (
        ("human_approval", "Ambiguous task requires approval before execution."),
    ),
}


PROMPT_CAPABILITY_SIGNALS: tuple[tuple[tuple[str, ...], tuple[str, str]], ...] = (
    (("video",), ("video_understanding", "Prompt references video input or video interpretation.")),
    (("image", "screenshot", "photo", "diagram", "figure"), ("image_understanding", "Prompt references visual input.")),
    (("csv", "xlsx", "spreadsheet", "dataframe"), ("spreadsheet_processing", "Prompt references tabular spreadsheet-style data.")),
    (("chart", "statistics", "dataset", "analyze data"), ("data_analysis", "Prompt asks for structured data analysis.")),
    (("audio", "music", "mix", "master", "hrtf", "stem", "binaural"), ("audio_analysis", "Prompt references audio or music analysis.")),
    (("skill", "capability", "tool discovery"), ("skill_discovery", "Prompt references skill or capability discovery.")),
    (("research", "latest", "source", "citation", "competitor", "industry"), ("web_search", "Prompt may need current external sources.")),
    (("citation", "source", "evidence"), ("source_citation", "Prompt asks for sourced evidence.")),
    (("shell", "deploy", "server", "backup", "folder", "filesystem"), ("local_shell", "Prompt references local operations or shell work.")),
)


TARGET_HINT_RE = re.compile(
    r"\b(repo|repository|github|file|folder|path|pdf|docx|csv|xlsx|spreadsheet|image|screenshot|video|audio|stems?)\b",
    re.IGNORECASE,
)
CURRENT_FACT_RE = re.compile(r"\b(latest|current|recent|today|202\d|market|competitor|industry|company)\b", re.IGNORECASE)
DESTRUCTIVE_RE = re.compile(r"\b(delete|remove|overwrite|move|deploy|backup|cleanup|clean up|organize|shell|filesystem)\b", re.IGNORECASE)


class TaskCompilationError(ValueError):
    """Structured validation failure raised by Task Compiler entrypoints."""

    def __init__(self, errors: list[dict[str, str]]):
        self.errors = errors
        message = "; ".join(f"{item['field']}: {item['message']}" for item in errors)
        super().__init__(message)


@dataclass
class TaskCompilationResult:
    """Public S1-C/D/E/F compile packet for deterministic planning previews."""

    contract: MissionContract
    intent_summary: str
    selected_template_id: str = "unknown_exploratory"
    domain_signals: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    decision_cards: list[dict[str, Any]] = field(default_factory=list)


def _utc_timestamp() -> str:
    """Return deterministic-format UTC timestamp for contract metadata."""

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _slugify(value: str) -> str:
    """Create a stable local slug from project or prompt text."""

    text = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower()).strip("_")
    return text or "task"


def _default_task_id(prompt: str, project: str | None) -> str:
    """Build a deterministic fallback task id without hashing secrets."""

    base = _slugify(project or "mission")
    prompt_slug = _slugify(prompt)[:32].strip("_") or "task"
    return f"{base}_{prompt_slug}"


def _structured_prompt_error(prompt: str) -> list[dict[str, str]]:
    """Return structured compile errors for invalid prompt input."""

    if prompt is None:
        return [{"field": "user_prompt", "message": "user_prompt is required", "code": "required"}]
    if not str(prompt).strip():
        return [{"field": "user_prompt", "message": "user_prompt cannot be empty", "code": "required"}]
    return []


def _compact_prompt(prompt: str) -> str:
    """Normalize whitespace while preserving the full user goal text."""

    return re.sub(r"\s+", " ", prompt.strip())


def build_intent_summary(prompt: str, task_type: MissionTaskType) -> str:
    """Build a concise deterministic intent summary without unsafe truncation."""

    compact = _compact_prompt(prompt)
    if len(compact) <= 420:
        return f"Compile a {task_type.value} mission for: {compact}"
    prefix = compact[:260].rstrip()
    suffix = compact[-140:].lstrip()
    omitted = len(compact) - len(prefix) - len(suffix)
    return f"Compile a {task_type.value} mission for: {prefix} … [preserved {omitted} chars in user_goal] … {suffix}"


def _contains_any(prompt: str, needles: tuple[str, ...]) -> bool:
    lowered = prompt.lower()
    return any(needle.lower() in lowered for needle in needles)


def _add_capability(
    capabilities: dict[str, MissionCapabilityRequirement],
    capability: str,
    reason: str,
    source: str = "inferred",
) -> None:
    if capability in capabilities:
        existing = capabilities[capability]
        if reason not in existing.reason:
            existing.reason = f"{existing.reason} {reason}"
        return
    capabilities[capability] = MissionCapabilityRequirement(
        capability=capability,
        reason=reason,
        required=True,
        source=source,
    )


def build_required_capabilities(
    task_type: MissionTaskType,
    prompt: str,
    domain_template: DomainWorkflowTemplate | None = None,
) -> list[MissionCapabilityRequirement]:
    """Generate required capabilities from task type, template, and prompt signals."""

    capabilities: dict[str, MissionCapabilityRequirement] = {}
    for capability, reason in CAPABILITIES_BY_TYPE.get(task_type, CAPABILITIES_BY_TYPE[MissionTaskType.UNKNOWN]):
        _add_capability(capabilities, capability, reason)
    if domain_template is not None:
        for capability in domain_template.required_capabilities:
            _add_capability(
                capabilities,
                capability,
                f"Required by domain workflow template {domain_template.template_id}.",
                "system_required",
            )
    for needles, capability_spec in PROMPT_CAPABILITY_SIGNALS:
        if _contains_any(prompt, needles):
            capability, reason = capability_spec
            _add_capability(capabilities, capability, reason)
    if task_type in {MissionTaskType.RESEARCH, MissionTaskType.BUSINESS}:
        _add_capability(capabilities, "web_search", "Research/business tasks require source collection.")
        _add_capability(capabilities, "source_citation", "Research/business tasks require citation tracking.")
    if task_type == MissionTaskType.UNKNOWN:
        _add_capability(capabilities, "human_approval", "Unknown task type requires a human approval decision.")
    ordered = sorted(capabilities.values(), key=lambda item: item.capability)
    return ordered


def build_unknowns(prompt: str, task_type: MissionTaskType) -> list[str]:
    """Generate conservative unknowns without blocking actionable prompts."""

    unknowns: list[str] = []
    compact = _compact_prompt(prompt)
    if not TARGET_HINT_RE.search(compact):
        unknowns.append("Target repository, file, data source, artifact, or operating scope is not specified.")
    if len(compact.split()) <= 4:
        unknowns.append("Prompt is very short; exact deliverable, constraints, and success criteria are unclear.")
    if task_type in {MissionTaskType.RESEARCH, MissionTaskType.BUSINESS}:
        unknowns.append("Authoritative sources and acceptable citation scope are not collected yet.")
    if task_type == MissionTaskType.LOCAL_OPS:
        unknowns.append("Exact local path scope and destructive-operation boundary require confirmation.")
    if task_type == MissionTaskType.UNKNOWN:
        unknowns.append("Primary task type could not be classified from deterministic keyword signals.")
    return _dedupe(unknowns)


def build_assumptions(prompt: str, task_type: MissionTaskType) -> list[MissionAssumption]:
    """Generate deterministic assumptions for a MissionContract."""

    assumptions: list[MissionAssumption] = []
    assumptions.append(
        MissionAssumption(
            id="assumption_001",
            text="The compiler must only create a MissionContract and must not execute tools or mutate runtime state.",
            confidence="high",
            requires_user_confirmation=False,
        )
    )
    if task_type in {MissionTaskType.CODING, MissionTaskType.DEBUGGING}:
        assumptions.append(
            MissionAssumption(
                id="assumption_002",
                text="Repository inspection and tests will happen in a later execution phase, not during compilation.",
                confidence="medium",
                requires_user_confirmation=False,
            )
        )
    elif task_type in {MissionTaskType.RESEARCH, MissionTaskType.BUSINESS} or CURRENT_FACT_RE.search(prompt):
        assumptions.append(
            MissionAssumption(
                id="assumption_002",
                text="Sources must be collected and cited before factual conclusions are accepted.",
                confidence="high",
                requires_user_confirmation=False,
            )
        )
    else:
        assumptions.append(
            MissionAssumption(
                id="assumption_002",
                text="Ambiguous details should be resolved by conservative planning or human clarification.",
                confidence="medium",
                requires_user_confirmation=True,
            )
        )
    return assumptions


def mission_assumptions_from_texts(texts: list[str]) -> list[MissionAssumption]:
    """Map deterministic assumption strings to MissionAssumption entries."""

    assumptions: list[MissionAssumption] = []
    for index, text in enumerate(texts, start=1):
        assumptions.append(
            MissionAssumption(
                id=f"assumption_{index:03d}",
                text=text,
                confidence="high" if index == 1 else "medium",
                requires_user_confirmation=False,
            )
        )
    return assumptions


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def unimplemented_capabilities(capabilities: list[MissionCapabilityRequirement]) -> list[str]:
    """Return required capabilities that S1-B records as gaps."""

    return [item.capability for item in capabilities if item.capability not in SUPPORTED_CAPABILITIES]


def build_decision_cards(
    task_type: MissionTaskType,
    prompt: str,
    capabilities: list[MissionCapabilityRequirement],
    unknowns: list[str],
) -> list[dict[str, Any]]:
    """Build decision cards for approval and capability gaps."""

    cards: list[dict[str, Any]] = []
    gaps = unimplemented_capabilities(capabilities)
    if gaps:
        cards.append(
            {
                "decision_id": "capability_gap_001",
                "kind": "capability_gap",
                "title": "Required capability is not implemented in the local S1-B runtime",
                "required_capabilities": gaps,
                "recommendation": "Require human approval or route to a future capable runtime before execution.",
                "note": UNIMPLEMENTED_CAPABILITY_NOTE,
            }
        )
    if task_type == MissionTaskType.UNKNOWN or unknowns:
        cards.append(
            {
                "decision_id": "clarification_001",
                "kind": "clarification",
                "title": "Clarify unknowns before high-risk execution",
                "unknowns": unknowns,
                "recommendation": "Proceed only with conservative assumptions or ask the user for missing scope.",
            }
        )
    if DESTRUCTIVE_RE.search(prompt) or task_type == MissionTaskType.LOCAL_OPS:
        cards.append(
            {
                "decision_id": "approval_001",
                "kind": "human_approval",
                "title": "Human approval required for local or destructive operations",
                "recommendation": "Require dry-run, rollback plan, and path-scope confirmation before execution.",
            }
        )
    return cards


def human_approval_policy(
    task_type: MissionTaskType,
    prompt: str,
    decision_cards: list[dict[str, Any]],
) -> MissionHumanApproval:
    """Build the MissionHumanApproval block from risk and gap signals."""

    reasons: list[str] = []
    if task_type == MissionTaskType.UNKNOWN:
        reasons.append("task type is unknown")
    if task_type == MissionTaskType.LOCAL_OPS or DESTRUCTIVE_RE.search(prompt):
        reasons.append("local or potentially destructive operation requires approval")
    if any(card.get("kind") == "capability_gap" for card in decision_cards):
        reasons.append("required capability gap must be acknowledged")
    if not reasons:
        return MissionHumanApproval(required=False, reason="No S1-B approval trigger detected.")
    return MissionHumanApproval(required=True, reason="; ".join(_dedupe(reasons)))


def build_risks(task_type: MissionTaskType, gaps: list[str]) -> list[MissionRisk]:
    """Generate a compact deterministic risk list."""

    risks = [
        MissionRisk(
            risk_id="risk_001",
            level="low" if task_type not in {MissionTaskType.LOCAL_OPS, MissionTaskType.UNKNOWN} else "medium",
            description="Compiler output is heuristic and may miss domain-specific constraints.",
            mitigation="Use assumptions, unknowns, decision cards, and acceptance gates before execution.",
        )
    ]
    if gaps:
        risks.append(
            MissionRisk(
                risk_id="risk_002",
                level="medium",
                description="Some required capabilities are not implemented in the local S1-B runtime.",
                mitigation="Represent capability gaps in decision cards and require approval before execution.",
            )
        )
    return risks


def mission_risks_from_names(risk_names: list[str]) -> list[MissionRisk]:
    """Map risk-name strings to simple MissionRisk schema entries."""

    risks: list[MissionRisk] = []
    for index, risk_name in enumerate(risk_names, start=1):
        risks.append(
            MissionRisk(
                risk_id=f"risk_{index:03d}_{risk_name}",
                level=risk_level_for_name(risk_name),
                description=risk_description_for_name(risk_name),
                mitigation=risk_mitigation_for_name(risk_name),
            )
        )
    return risks


def recommended_route_for(task_type: MissionTaskType) -> str:
    """Recommend a future route without invoking lifecycle integration."""

    routes = {
        MissionTaskType.CODING: "Supervisor -> RepoScout -> Coder -> Tester/Auditor -> Verifier",
        MissionTaskType.DEBUGGING: "Supervisor -> RepoScout -> Coder -> Tester/Auditor -> Verifier",
        MissionTaskType.RESEARCH: "Supervisor -> Researcher -> Verifier",
        MissionTaskType.BUSINESS: "Supervisor -> Researcher -> Verifier",
        MissionTaskType.CREATIVE_LONGFORM: "Supervisor -> Prompt Engineer -> Archivist/Doc Manager -> Verifier",
        MissionTaskType.DOCUMENT_PROCESSING: "Supervisor -> Researcher -> Doc Manager -> Verifier",
        MissionTaskType.DATA_ANALYSIS: "Supervisor -> Researcher -> Tester/Auditor -> Verifier",
        MissionTaskType.AUDIO_MUSIC: "Supervisor -> Researcher -> Tester/Auditor -> Verifier",
        MissionTaskType.MULTIMODAL: "Supervisor -> Researcher -> Verifier",
        MissionTaskType.LOCAL_OPS: "Supervisor -> Tester/Auditor -> Verifier with approval gate",
        MissionTaskType.EDUCATION: "Supervisor -> Prompt Engineer -> Verifier",
        MissionTaskType.UNKNOWN: "Supervisor -> Human clarification -> Verifier",
    }
    return routes[task_type]


def compile_task_packet(
    user_prompt: str,
    *,
    task_id: str | None = None,
    project: str | None = None,
) -> TaskCompilationResult:
    """Compile a raw prompt into a MissionContract plus compiler metadata."""

    prompt_errors = _structured_prompt_error(user_prompt)
    if prompt_errors:
        raise TaskCompilationError(prompt_errors)
    compact_prompt = _compact_prompt(user_prompt)
    classification = classify_task_type(compact_prompt)
    task_type = classification.task_type
    catalog = load_domain_workflow_templates()
    selected_template = select_domain_workflow(task_type.value, classification.domain_signals, catalog)
    mission_id = task_id or _default_task_id(compact_prompt, project)
    capabilities = build_required_capabilities(task_type, compact_prompt, selected_template)
    capability_names = [item.capability for item in capabilities]
    assumptions_text, refined_unknowns, refined_decision_cards = build_assumptions_and_unknowns(
        compact_prompt,
        task_type.value,
        classification.domain_signals,
        capability_names,
    )
    legacy_unknowns = build_unknowns(compact_prompt, task_type)
    unknowns = _dedupe(refined_unknowns + legacy_unknowns)
    assumptions = mission_assumptions_from_texts(assumptions_text)
    legacy_decision_cards = build_decision_cards(task_type, compact_prompt, capabilities, unknowns)
    decision_cards = refined_decision_cards + legacy_decision_cards
    gaps = unimplemented_capabilities(capabilities)
    warnings = build_warnings(compact_prompt, task_type, gaps, unknowns)
    warnings.extend(catalog.warnings)
    warnings = _dedupe(warnings)
    intent_summary = build_intent_summary(compact_prompt, task_type)
    risk_names = build_domain_risks(compact_prompt, task_type.value, capability_names, selected_template)
    contract = MissionContract(
        mission_id=mission_id,
        created_at=_utc_timestamp(),
        task_type=task_type,
        user_goal=compact_prompt,
        intent_summary=intent_summary,
        non_goals=[
            "Do not execute tools during task compilation.",
            "Do not browse the web or call external providers during compilation.",
            "Do not mutate AgentLab runtime lifecycle state in S1-B.",
        ],
        hard_constraints=[
            "Deterministic local-first rule-based compilation only.",
            "MissionContract YAML output must be UTF-8 and stable through schema IO.",
        ],
        soft_preferences=["Prefer conservative assumptions and explicit unknowns over crashing."],
        unknowns=unknowns,
        assumptions=assumptions,
        required_capabilities=capabilities,
        required_artifacts=build_required_artifacts(task_type, compact_prompt, selected_template),
        acceptance_gates=build_acceptance_gates(task_type, compact_prompt, selected_template, capability_names),
        risks=mission_risks_from_names(risk_names),
        human_approval=human_approval_policy(task_type, compact_prompt, decision_cards),
        recommended_route=recommended_route_for(task_type),
        notes=[
            "compiled_by: task_compiler_s1_cdef",
            template_note(selected_template),
            "deterministic_compiler: true",
            "S1-C/D/E/F Task Compiler refinement; classification is deterministic heuristic.",
            "Capability gaps are represented as contract requirements and decision cards, not failures.",
        ],
    )
    errors = validate_mission_contract(contract)
    if errors:
        raise TaskCompilationError(errors)
    return TaskCompilationResult(
        contract=contract,
        intent_summary=intent_summary,
        selected_template_id=selected_template.template_id,
        domain_signals=classification.domain_signals,
        warnings=warnings,
        decision_cards=decision_cards,
    )


def build_warnings(prompt: str, task_type: MissionTaskType, gaps: list[str], unknowns: list[str]) -> list[str]:
    """Build warning strings for the public compile packet."""

    warnings: list[str] = []
    if len(prompt.split()) <= 4:
        warnings.append("Prompt is very short; generated contract is intentionally conservative.")
    if task_type == MissionTaskType.UNKNOWN:
        warnings.append("No deterministic domain rule matched; human approval is required.")
    if CURRENT_FACT_RE.search(prompt):
        warnings.append("Prompt may need current facts; source collection is required before final claims.")
    if gaps:
        warnings.append("Capability gaps detected: " + ", ".join(gaps))
    if unknowns:
        warnings.append("Unknowns were added to the MissionContract.")
    return _dedupe(warnings)


def compile_task_to_contract(
    user_prompt: str,
    *,
    task_id: str | None = None,
    project: str | None = None,
    output_dir: Path | str | None = None,
    strict: bool = False,
) -> MissionContract:
    """Compile a raw prompt into a MissionContract and optionally write YAML.

    When output_dir is provided, the contract is written to
    ``output_dir / mission_contract.yml`` using the existing deterministic YAML
    writer.  Strict mode fails if the compiler emitted warnings; default mode
    keeps MVP behavior permissive and safe by encoding uncertainty in the
    contract instead of crashing.
    """

    result = compile_task_packet(user_prompt, task_id=task_id, project=project)
    if strict and result.warnings:
        raise TaskCompilationError(
            [
                {
                    "field": "warnings",
                    "message": "; ".join(result.warnings),
                    "code": "strict_warning",
                }
            ]
        )
    if output_dir is not None:
        output_path = Path(output_dir) / "mission_contract.yml"
        write_mission_contract(result.contract, output_path)
    return result.contract
