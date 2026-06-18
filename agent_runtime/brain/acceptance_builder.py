"""Acceptance gate builder for AgentLab S1-B Task Compiler.

Acceptance gates are deliberately conservative.  They do not execute anything;
they describe what future execution layers, reviewers, or humans must verify
before accepting a compiled task result.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from .assumption_builder import SUPPORTED_CAPABILITIES
from .domain_workflows import DomainWorkflowTemplate
from .mission_contract import MissionAcceptanceGate, MissionTaskType


@dataclass(frozen=True)
class AcceptanceGateSpec:
    """Declarative acceptance gate specification."""

    suffix: str
    description: str
    verification_method: str
    required: bool = True


GATE_SPECS: dict[MissionTaskType, tuple[AcceptanceGateSpec, ...]] = {
    MissionTaskType.CODING: (
        AcceptanceGateSpec("static_checks", "Code compiles or relevant static checks pass.", "test"),
        AcceptanceGateSpec("tests", "Relevant tests pass and failures are reported honestly.", "test"),
        AcceptanceGateSpec("changed_files", "Changed files are summarized with reasons.", "review"),
        AcceptanceGateSpec("no_secret_leak", "No secrets, credentials, or local absolute paths are leaked.", "review"),
        AcceptanceGateSpec("rollback", "Rollback notes or safe revert path exist.", "artifact_exists"),
    ),
    MissionTaskType.DEBUGGING: (
        AcceptanceGateSpec("reproduce", "Original failure or closest reproducible signal is identified.", "test"),
        AcceptanceGateSpec("tests", "Relevant failing and regression tests pass after the fix.", "test"),
        AcceptanceGateSpec("changed_files", "Changed files are summarized with root-cause rationale.", "review"),
        AcceptanceGateSpec("no_secret_leak", "No secrets, credentials, or local absolute paths are leaked.", "review"),
        AcceptanceGateSpec("rollback", "Rollback notes exist for the repair.", "artifact_exists"),
    ),
    MissionTaskType.RESEARCH: (
        AcceptanceGateSpec("claim_sources", "Every nontrivial factual claim has a source.", "citation_check"),
        AcceptanceGateSpec("source_dates", "Sources include timestamps or access dates where applicable.", "citation_check"),
        AcceptanceGateSpec("uncertainty", "Uncertainty and confidence are explicitly stated.", "review"),
        AcceptanceGateSpec("no_fake_citations", "No fake citations or invented sources are present.", "citation_check"),
        AcceptanceGateSpec("source_quality", "Source quality and limitations are noted.", "review"),
    ),
    MissionTaskType.BUSINESS: (
        AcceptanceGateSpec("claim_sources", "Every nontrivial market or company claim has a source.", "citation_check"),
        AcceptanceGateSpec("source_dates", "Sources include timestamps or access dates where applicable.", "citation_check"),
        AcceptanceGateSpec("uncertainty", "Business uncertainty and assumptions are explicitly stated.", "review"),
        AcceptanceGateSpec("no_fake_citations", "No fake citations or invented business facts are present.", "citation_check"),
        AcceptanceGateSpec("source_quality", "Source quality and possible bias are noted.", "review"),
    ),
    MissionTaskType.CREATIVE_LONGFORM: (
        AcceptanceGateSpec("genre_tone", "Output follows requested genre, tone, audience, and constraints.", "review"),
        AcceptanceGateSpec("coherent_structure", "Structure is coherent and supports the requested form.", "review"),
        AcceptanceGateSpec("continuity", "Continuity issues are tracked instead of silently ignored.", "artifact_exists"),
        AcceptanceGateSpec("revision_notes", "Revision notes are provided for longform changes.", "artifact_exists"),
        AcceptanceGateSpec("outline_first", "No direct final longform execution occurs without outline or structure first.", "review"),
    ),
    MissionTaskType.DOCUMENT_PROCESSING: (
        AcceptanceGateSpec("input_manifest", "Input documents and page or section scope are listed.", "artifact_exists"),
        AcceptanceGateSpec("separate_extraction", "Extracted content is separated from interpretation.", "review"),
        AcceptanceGateSpec("tables_checked", "Tables or structured outputs receive quality checks.", "review"),
        AcceptanceGateSpec("ocr_uncertainty", "OCR or parsing uncertainty is marked clearly.", "review"),
        AcceptanceGateSpec("summary_trace", "Summary claims trace back to parsed content.", "review"),
    ),
    MissionTaskType.DATA_ANALYSIS: (
        AcceptanceGateSpec("data_profile", "Dataset shape, fields, and quality issues are profiled.", "artifact_exists"),
        AcceptanceGateSpec("cleaning_log", "Cleaning and transformation steps are reproducible.", "artifact_exists"),
        AcceptanceGateSpec("analysis_repro", "Analysis script or notebook-equivalent artifact is present.", "artifact_exists"),
        AcceptanceGateSpec("chart_caveats", "Charts and statistics include caveats where needed.", "review"),
        AcceptanceGateSpec("findings_limits", "Findings distinguish evidence from interpretation.", "review"),
    ),
    MissionTaskType.AUDIO_MUSIC: (
        AcceptanceGateSpec("asset_manifest", "Input assets are listed before analysis or processing.", "artifact_exists"),
        AcceptanceGateSpec("method", "Analysis or processing method is described.", "review"),
        AcceptanceGateSpec("subjective_vs_measured", "Subjective claims are separated from measurable observations.", "review"),
        AcceptanceGateSpec("validation_notes", "Validation or listening notes are recorded.", "artifact_exists"),
        AcceptanceGateSpec("capability_gap", "Capability gap is declared if required audio tooling is unavailable.", "manual_review"),
    ),
    MissionTaskType.MULTIMODAL: (
        AcceptanceGateSpec("artifact_refs", "Every visual observation references an input artifact.", "review"),
        AcceptanceGateSpec("uncertain_visuals", "Uncertain visual claims are marked clearly.", "review"),
        AcceptanceGateSpec("text_vs_interpretation", "Extracted text is separated from visual interpretation.", "review"),
        AcceptanceGateSpec("capability_gap", "Capability gap is declared if no vision tool exists.", "manual_review"),
        AcceptanceGateSpec("input_manifest", "Input artifacts are listed before analysis.", "artifact_exists"),
    ),
    MissionTaskType.LOCAL_OPS: (
        AcceptanceGateSpec("dry_run", "Dry-run occurs before destructive action.", "manual_review"),
        AcceptanceGateSpec("rollback_plan", "Rollback plan is present before changes.", "artifact_exists"),
        AcceptanceGateSpec("path_scope", "Path scope is confirmed and constrained.", "manual_review"),
        AcceptanceGateSpec("human_approval", "Human approval is required for destructive changes.", "manual_review"),
        AcceptanceGateSpec("completion_manifest", "Changed files or operations are recorded.", "artifact_exists"),
    ),
    MissionTaskType.EDUCATION: (
        AcceptanceGateSpec("learning_goal", "Learning goal and learner assumptions are explicit.", "review"),
        AcceptanceGateSpec("lesson_sequence", "Lesson sequence is coherent and scaffolded.", "review"),
        AcceptanceGateSpec("practice", "Practice questions or checks are provided.", "artifact_exists"),
        AcceptanceGateSpec("answer_key", "Answer key or rubric is present when exercises are included.", "artifact_exists"),
        AcceptanceGateSpec("clarity", "Explanation is clear and avoids unsupported claims.", "review"),
    ),
    MissionTaskType.UNKNOWN: (
        AcceptanceGateSpec("clarify", "Clarifying questions or assumptions are present.", "artifact_exists"),
        AcceptanceGateSpec("human_approval", "Human approval is required before execution.", "manual_review"),
        AcceptanceGateSpec("scope", "Execution scope is not expanded beyond the prompt.", "review"),
    ),
}


PROMPT_GATE_RULES: tuple[tuple[re.Pattern[str], tuple[tuple[str, str, str], ...]], ...] = (
    (
        re.compile(r"\b(ci|github actions?)\b", re.IGNORECASE),
        (("ci_evidence", "CI status or local equivalent evidence is recorded.", "review"),),
    ),
    (
        re.compile(r"\b(test|tests|pytest|unit test|integration test)\b", re.IGNORECASE),
        (("test_output", "Test command output or explicit test limitation is recorded.", "test"),),
    ),
    (
        re.compile(r"\b(web|current|latest|company|market|competitor|today)\b", re.IGNORECASE),
        (("fresh_sources", "Source citations and freshness evidence are required.", "citation_check"),),
    ),
    (
        re.compile(r"\b(screenshot|image|video|photo|visual)\b", re.IGNORECASE),
        (("visual_provenance", "Observation provenance and uncertainty labels are required.", "review"),),
    ),
    (
        re.compile(r"\b(audio|music|mix|master|hrtf|spatial|binaural)\b", re.IGNORECASE),
        (("audio_objective_subjective", "Objective measurements are separated from subjective listening notes.", "review"),),
    ),
    (
        re.compile(r"\b(local file|delete|cleanup|clean up|remove|filesystem|folder)\b", re.IGNORECASE),
        (("dry_run_and_rollback", "Dry-run evidence and rollback plan are required.", "manual_review"),),
    ),
    (
        re.compile(r"\b(external agent|external agents|tool|tools|handoff|connector)\b", re.IGNORECASE),
        (("handoff_ledger", "External agent/tool handoff and evidence ledger are required.", "artifact_exists"),),
    ),
)


def _normalize_task_type(task_type: MissionTaskType | str) -> MissionTaskType:
    """Normalize strings to MissionTaskType without raising on unknown values."""

    if isinstance(task_type, MissionTaskType):
        return task_type
    try:
        return MissionTaskType(str(task_type))
    except ValueError:
        return MissionTaskType.UNKNOWN


def _gate_id_prefix(task_type: MissionTaskType, template: DomainWorkflowTemplate | None) -> str:
    """Build a stable gate id prefix."""

    if template is None:
        return task_type.value
    return f"{task_type.value}_{template.template_id}"


def _add_gate(
    gates: dict[str, MissionAcceptanceGate],
    gate_id: str,
    description: str,
    verification_method: str,
    required: bool = True,
) -> None:
    """Add a gate by description to dedupe semantically stable outputs."""

    key = description.strip().lower()
    if key in gates:
        return
    gates[key] = MissionAcceptanceGate(
        gate_id=gate_id,
        description=description,
        verification_method=verification_method,
        required=required,
    )


def _prompt_specific_gate_specs(prompt: str) -> list[tuple[str, str, str]]:
    """Return prompt-specific gate specs in stable declaration order."""

    specs: list[tuple[str, str, str]] = []
    for pattern, gate_specs in PROMPT_GATE_RULES:
        if pattern.search(prompt or ""):
            specs.extend(gate_specs)
    return specs


def _capability_gap_gate_specs(required_capabilities: list[str]) -> list[tuple[str, str, str]]:
    """Return capability gap gates for capabilities not implemented locally."""

    gaps = [capability for capability in required_capabilities if capability not in SUPPORTED_CAPABILITIES]
    if not gaps:
        return []
    return [
        (
            "capability_gap",
            "Capability gap is declared for unavailable required capabilities: " + ", ".join(sorted(set(gaps))) + ".",
            "manual_review",
        )
    ]


def build_acceptance_gates(
    task_type: MissionTaskType | str,
    prompt: str = "",
    domain_template: DomainWorkflowTemplate | None = None,
    required_capabilities: list[str] | None = None,
) -> list[MissionAcceptanceGate]:
    """Build base + template + prompt-specific acceptance gates."""

    normalized = _normalize_task_type(task_type)
    specs = GATE_SPECS.get(normalized, GATE_SPECS[MissionTaskType.UNKNOWN])
    gates: dict[str, MissionAcceptanceGate] = {}
    for index, spec in enumerate(specs, start=1):
        _add_gate(
            gates,
            f"{normalized.value}_{index:02d}_{spec.suffix}",
            spec.description,
            spec.verification_method,
            spec.required,
        )
    prefix = _gate_id_prefix(normalized, domain_template)
    if domain_template is not None:
        for index, description in enumerate(domain_template.acceptance_gates, start=1):
            _add_gate(gates, f"{prefix}_template_{index:02d}", description, "review", True)
    prompt_specs = _prompt_specific_gate_specs(prompt)
    prompt_specs.extend(_capability_gap_gate_specs(required_capabilities or []))
    for index, (suffix, description, method) in enumerate(prompt_specs, start=1):
        _add_gate(gates, f"{prefix}_prompt_{index:02d}_{suffix}", description, method, True)
    return list(gates.values())


def gate_descriptions_for_task_type(task_type: MissionTaskType | str) -> list[str]:
    """Return only gate descriptions for tests, docs, and summaries."""

    return [gate.description for gate in build_acceptance_gates(task_type)]
