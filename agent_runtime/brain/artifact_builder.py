"""Required artifact builder for AgentLab S1-B Task Compiler.

The artifact layer converts a lightweight task type into concrete output
expectations.  These are not full workflow templates; they are stable artifact
contracts that let the MissionContract say what evidence and deliverables should
exist before a task can be accepted.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from pathlib import PurePosixPath

from .domain_workflows import DomainWorkflowTemplate
from .mission_contract import MissionArtifactContract, MissionTaskType


@dataclass(frozen=True)
class ArtifactSpec:
    """Declarative artifact specification used by the deterministic builder."""

    name: str
    artifact_type: str
    description: str
    required: bool = True


ARTIFACT_SPECS: dict[MissionTaskType, tuple[ArtifactSpec, ...]] = {
    MissionTaskType.CODING: (
        ArtifactSpec("intent_summary.md", "document", "Brief restatement of the user goal and coding scope."),
        ArtifactSpec("repo_findings.md", "report", "Repository facts, relevant files, and constraints discovered before editing."),
        ArtifactSpec("patch_plan.md", "document", "Smallest safe implementation plan before code changes."),
        ArtifactSpec("changed_files_summary.md", "report", "Summary of every changed file and why it changed."),
        ArtifactSpec("test_results.md", "report", "Commands run and real test or compile results."),
        ArtifactSpec("acceptance_report.md", "report", "Final acceptance verdict and remaining risks."),
    ),
    MissionTaskType.DEBUGGING: (
        ArtifactSpec("intent_summary.md", "document", "Brief restatement of the bug or failure to repair."),
        ArtifactSpec("repo_findings.md", "report", "Failure reproduction notes and relevant code paths."),
        ArtifactSpec("patch_plan.md", "document", "Minimal repair plan tied to the observed failure."),
        ArtifactSpec("changed_files_summary.md", "report", "Summary of repaired files and regression risk."),
        ArtifactSpec("test_results.md", "report", "Original failing check and post-fix verification results."),
        ArtifactSpec("acceptance_report.md", "report", "Final debug acceptance verdict and rollback notes."),
    ),
    MissionTaskType.RESEARCH: (
        ArtifactSpec("research_plan.md", "document", "Questions, scope, and source collection plan."),
        ArtifactSpec("source_table.yml", "dataset", "Structured table of sources, dates, and relevance."),
        ArtifactSpec("evidence_notes.md", "report", "Extracted evidence mapped to claims."),
        ArtifactSpec("analysis_report.md", "report", "Synthesized research answer with caveats."),
        ArtifactSpec("citation_ledger.yml", "dataset", "Claim-to-source citation ledger."),
        ArtifactSpec("uncertainty_notes.md", "report", "Known gaps, stale facts, and confidence notes."),
    ),
    MissionTaskType.BUSINESS: (
        ArtifactSpec("research_plan.md", "document", "Business question, market scope, and source strategy."),
        ArtifactSpec("source_table.yml", "dataset", "Company, competitor, market, and industry sources."),
        ArtifactSpec("evidence_notes.md", "report", "Evidence grouped by business claim."),
        ArtifactSpec("analysis_report.md", "report", "Business analysis and recommended interpretation."),
        ArtifactSpec("citation_ledger.yml", "dataset", "Citation ledger for nontrivial factual claims."),
        ArtifactSpec("uncertainty_notes.md", "report", "Uncertainty, stale information, and assumptions."),
    ),
    MissionTaskType.CREATIVE_LONGFORM: (
        ArtifactSpec("creative_brief.md", "document", "Genre, tone, audience, and creative constraints."),
        ArtifactSpec("world_or_context_bible.md", "document", "World, context, setting, or canon references."),
        ArtifactSpec("character_or_structure_notes.md", "document", "Character, arc, structure, or scene planning notes."),
        ArtifactSpec("outline.md", "document", "Outline that precedes longform drafting."),
        ArtifactSpec("draft.md", "document", "Draft text produced after outline approval or constraints."),
        ArtifactSpec("continuity_ledger.md", "report", "Continuity issues and decisions tracked during drafting."),
        ArtifactSpec("revision_notes.md", "report", "Revision summary and unresolved creative choices."),
    ),
    MissionTaskType.DOCUMENT_PROCESSING: (
        ArtifactSpec("extraction_plan.md", "document", "Document scope, parsing strategy, and quality risks."),
        ArtifactSpec("parsed_content.md", "document", "Extracted prose or OCR output separated from interpretation."),
        ArtifactSpec("table_outputs/", "dataset", "Extracted tables or structured document outputs."),
        ArtifactSpec("quality_check.md", "report", "Parsing quality, missing pages, and formatting caveats."),
        ArtifactSpec("summary.md", "report", "Concise summary of document content when requested."),
    ),
    MissionTaskType.DATA_ANALYSIS: (
        ArtifactSpec("data_profile.md", "report", "Dataset shape, fields, missing values, and quality profile."),
        ArtifactSpec("cleaning_log.md", "report", "Data cleaning steps and transformations."),
        ArtifactSpec("analysis_notebook_or_script.py", "other", "Reproducible analysis script or notebook-equivalent code."),
        ArtifactSpec("charts/", "media", "Generated charts or chart specifications."),
        ArtifactSpec("findings_report.md", "report", "Findings, caveats, and interpretation."),
    ),
    MissionTaskType.AUDIO_MUSIC: (
        ArtifactSpec("audio_task_brief.md", "document", "Audio/music objective and constraints."),
        ArtifactSpec("input_asset_manifest.yml", "dataset", "Input stems, mixes, references, or audio assets."),
        ArtifactSpec("analysis_report.md", "report", "Measurable and subjective audio observations."),
        ArtifactSpec("processing_plan.md", "document", "Proposed audio processing or analysis plan."),
        ArtifactSpec("listening_or_validation_notes.md", "report", "Listening notes or validation evidence."),
    ),
    MissionTaskType.MULTIMODAL: (
        ArtifactSpec("input_artifact_manifest.yml", "dataset", "Images, screenshots, videos, or visual inputs."),
        ArtifactSpec("vision_observations.yml", "dataset", "Structured visual observations tied to input artifacts."),
        ArtifactSpec("extracted_text.md", "document", "OCR or transcribed text separated from interpretation."),
        ArtifactSpec("annotated_artifacts/", "media", "Optional annotated visual artifacts."),
        ArtifactSpec("visual_summary.md", "report", "Visual summary, uncertainties, and capability gaps."),
    ),
    MissionTaskType.LOCAL_OPS: (
        ArtifactSpec("operation_plan.md", "document", "Scoped local operation plan and affected paths."),
        ArtifactSpec("dry_run_report.md", "report", "Dry-run output before any destructive action."),
        ArtifactSpec("changed_files_manifest.yml", "dataset", "Files changed, moved, deleted, or generated."),
        ArtifactSpec("rollback_plan.md", "document", "Rollback or restore plan."),
        ArtifactSpec("completion_report.md", "report", "Completion evidence and remaining local risks."),
    ),
    MissionTaskType.EDUCATION: (
        ArtifactSpec("learning_goal.md", "document", "Learning objective and learner assumptions."),
        ArtifactSpec("lesson_plan.md", "document", "Teaching sequence and checkpoints."),
        ArtifactSpec("explanation.md", "document", "Core explanation tailored to the learner."),
        ArtifactSpec("practice_questions.md", "document", "Practice prompts or exercises."),
        ArtifactSpec("answer_key.md", "document", "Answer key or rubric for practice items."),
    ),
    MissionTaskType.UNKNOWN: (
        ArtifactSpec("intent_summary.md", "document", "Best-effort summary of the ambiguous request."),
        ArtifactSpec("clarifying_questions.md", "document", "Questions needed before safe execution."),
        ArtifactSpec("assumptions.yml", "dataset", "Conservative assumptions made by the compiler."),
        ArtifactSpec("proposed_plan.md", "document", "Proposed plan requiring human approval."),
    ),
}


PROMPT_ARTIFACT_RULES: tuple[tuple[re.Pattern[str], tuple[str, ...]], ...] = (
    (re.compile(r"\b(ci|github actions?)\b", re.IGNORECASE), ("ci_results.md",)),
    (re.compile(r"\b(readme|docs?|documentation)\b", re.IGNORECASE), ("documentation_update.md",)),
    (re.compile(r"\b(benchmark|eval|evaluation)\b", re.IGNORECASE), ("evaluation_report.md",)),
    (re.compile(r"\b(pdf|table|tables)\b", re.IGNORECASE), ("table_extraction_report.md",)),
    (re.compile(r"\b(screenshot|image|photo|video|visual)\b", re.IGNORECASE), ("vision_observations.yml",)),
    (re.compile(r"\b(audio|music|spatial|hrtf|binaural|loudness)\b", re.IGNORECASE), ("audio_analysis_report.md",)),
    (re.compile(r"\b(cleanup|clean up|delete|remove|filesystem|local file|folder)\b", re.IGNORECASE), ("dry_run_report.md", "rollback_plan.md")),
)

PROMPT_ARTIFACT_DESCRIPTIONS = {
    "ci_results.md": "CI or GitHub Actions status and local equivalent evidence.",
    "documentation_update.md": "Documentation or README update summary and verification notes.",
    "evaluation_report.md": "Benchmark, evaluation, or measurement results and caveats.",
    "table_extraction_report.md": "Table extraction result, structure checks, and parsing caveats.",
    "vision_observations.yml": "Structured screenshot, image, or video observations with provenance.",
    "audio_analysis_report.md": "Audio/music analysis notes separating objective and subjective observations.",
    "dry_run_report.md": "Dry-run evidence before local cleanup, delete, or filesystem changes.",
    "rollback_plan.md": "Rollback plan for local or destructive operations.",
}


def artifact_type_for_name(name: str) -> str:
    """Infer a valid MissionArtifactContract artifact_type for a path name."""

    path = PurePosixPath(name.rstrip("/"))
    if name.endswith("/"):
        if "chart" in name or "artifact" in name:
            return "media"
        return "dataset"
    if path.suffix in {".yml", ".yaml", ".csv", ".json"}:
        return "dataset"
    if path.suffix in {".md", ".txt"}:
        lowered = path.name.lower()
        if "report" in lowered or "notes" in lowered or "results" in lowered:
            return "report"
        return "document"
    if path.suffix in {".py", ".ipynb"}:
        return "other"
    return "other"


def _normalize_task_type(task_type: MissionTaskType | str) -> MissionTaskType:
    """Normalize strings to MissionTaskType without crashing on unknown values."""

    if isinstance(task_type, MissionTaskType):
        return task_type
    try:
        return MissionTaskType(str(task_type))
    except ValueError:
        return MissionTaskType.UNKNOWN


def _add_artifact(
    artifacts: dict[str, MissionArtifactContract],
    name: str,
    description: str,
    artifact_type: str | None = None,
    required: bool = True,
) -> None:
    """Add one artifact while preserving first description and stable order."""

    if name in artifacts:
        return
    artifacts[name] = MissionArtifactContract(
        artifact_type=artifact_type or artifact_type_for_name(name),
        name=name,
        description=description,
        required=required,
    )


def prompt_specific_artifact_names(prompt: str) -> list[str]:
    """Return prompt-specific artifact names without adding unrelated outputs."""

    names: list[str] = []
    for pattern, artifacts in PROMPT_ARTIFACT_RULES:
        if pattern.search(prompt or ""):
            names.extend(artifacts)
    seen: set[str] = set()
    result: list[str] = []
    for name in names:
        if name not in seen:
            seen.add(name)
            result.append(name)
    return result


def build_required_artifacts(
    task_type: MissionTaskType | str,
    prompt: str = "",
    domain_template: DomainWorkflowTemplate | None = None,
) -> list[MissionArtifactContract]:
    """Build base + domain-template + prompt-specific artifacts.

    The merge order is stable: task-type defaults first, selected domain template
    artifacts second, and prompt-specific artifacts last. Duplicate names are
    removed without reordering existing entries.
    """

    normalized = _normalize_task_type(task_type)
    specs = ARTIFACT_SPECS.get(normalized, ARTIFACT_SPECS[MissionTaskType.UNKNOWN])
    artifacts: dict[str, MissionArtifactContract] = {}
    for spec in specs:
        _add_artifact(artifacts, spec.name, spec.description, spec.artifact_type, spec.required)
    if domain_template is not None:
        for name in domain_template.required_artifacts:
            _add_artifact(
                artifacts,
                name,
                f"Required by domain workflow template {domain_template.template_id}.",
            )
    for name in prompt_specific_artifact_names(prompt):
        _add_artifact(
            artifacts,
            name,
            PROMPT_ARTIFACT_DESCRIPTIONS.get(name, "Prompt-specific planning artifact."),
        )
    return list(artifacts.values())


def artifact_names_for_task_type(task_type: MissionTaskType | str) -> list[str]:
    """Return only artifact names for tests, docs, and summaries."""

    return [artifact.name for artifact in build_required_artifacts(task_type)]
