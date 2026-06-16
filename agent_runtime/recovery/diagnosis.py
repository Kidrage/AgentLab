"""Failure diagnosis: generates root cause hypothesis and evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from agent_runtime.recovery.failure_event import FailureEvent
from agent_runtime.recovery.failure_classifier import FailureClassification, FailureCategory


@dataclass
class CauseHypothesis:
    """A single root cause hypothesis with confidence."""

    description: str
    confidence: float
    evidence_references: list[str]

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "description": self.description,
            "confidence": self.confidence,
            "evidence_references": self.evidence_references,
        }


@dataclass
class EvidenceItem:
    """Single piece of evidence supporting a diagnosis."""

    kind: str  # e.g., "stderr_tail", "stdout_tail", "artifact_path"
    summary: str
    source: str  # e.g., "failure_event.stderr_tail"
    confidence: float

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "kind": self.kind,
            "summary": self.summary,
            "source": self.source,
            "confidence": self.confidence,
        }


@dataclass
class BlastRadius:
    """Assessment of failure impact scope."""

    likely_affected: list[str]
    safe_to_retry: bool
    safe_to_continue: bool

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "likely_affected": self.likely_affected,
            "safe_to_retry": self.safe_to_retry,
            "safe_to_continue": self.safe_to_continue,
        }


@dataclass
class FailureDiagnosis:
    """Complete diagnosis of a failure."""

    task_id: str
    project: str
    primary_category: FailureCategory
    secondary_categories: list[FailureCategory]
    confidence: float
    root_cause_hypothesis: list[CauseHypothesis]
    evidence: list[EvidenceItem]
    blast_radius: BlastRadius
    recommended_next_action: str
    requires_human_review: bool
    warnings: list[str]
    created_at: str

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "task_id": self.task_id,
            "project": self.project,
            "primary_category": self.primary_category.value,
            "secondary_categories": [c.value for c in self.secondary_categories],
            "confidence": self.confidence,
            "root_cause_hypothesis": [h.to_dict() for h in self.root_cause_hypothesis],
            "evidence": [e.to_dict() for e in self.evidence],
            "blast_radius": self.blast_radius.to_dict(),
            "recommended_next_action": self.recommended_next_action,
            "requires_human_review": self.requires_human_review,
            "warnings": self.warnings,
            "created_at": self.created_at,
        }


def diagnose_failure(
    failure_event: FailureEvent,
    context_pack: dict | None = None,
    config: dict | None = None,
) -> FailureDiagnosis:
    """Diagnose a failure and generate root cause hypothesis.

    Args:
        failure_event: The captured failure event
        context_pack: Optional context pack dictionary for additional context
        config: Optional configuration dict for diagnosis hints

    Returns:
        FailureDiagnosis with hypothesis, evidence, and recommendations
    """
    # Extract classification from failure_event if available
    # (In real implementation, this would come from classifier)
    # For now, we derive from error_type if present
    primary_category = _derive_category_from_event(failure_event)

    # Generate hypotheses based on category
    hypotheses = _generate_hypotheses(failure_event, primary_category)

    # Build evidence list
    evidence = _build_evidence(failure_event, context_pack)

    # Assess blast radius
    blast_radius = _assess_blast_radius(failure_event, primary_category)

    # Determine if human review is required
    requires_human_review = _requires_human_review(primary_category)

    # Generate warnings
    warnings = _generate_warnings(failure_event, primary_category)

    # Recommended next action
    recommended_action = _recommended_action(primary_category)

    return FailureDiagnosis(
        task_id=failure_event.task_id,
        project=failure_event.project,
        primary_category=primary_category,
        secondary_categories=[],
        confidence=0.8,  # Default confidence for deterministic diagnosis
        root_cause_hypothesis=hypotheses,
        evidence=evidence,
        blast_radius=blast_radius,
        recommended_next_action=recommended_action,
        requires_human_review=requires_human_review,
        warnings=warnings,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def _derive_category_from_event(event: FailureEvent) -> FailureCategory:
    """Derive primary category from failure event fields."""
    if event.error_type:
        try:
            return FailureCategory(event.error_type)
        except ValueError:
            pass

    # Try to infer from command or other fields
    if event.command:
        command_lower = event.command.lower()
        if "pytest" in command_lower or "test" in command_lower:
            return FailureCategory.TEST_FAILURE
        if "compileall" in command_lower or "compile" in command_lower:
            return FailureCategory.SYNTAX_ERROR

    return FailureCategory.UNKNOWN


def _generate_hypotheses(event: FailureEvent, category: FailureCategory) -> list[CauseHypothesis]:
    """Generate root cause hypothesis based on event and category."""
    hypotheses = []

    # Category-specific hypotheses
    if category == FailureCategory.TEST_FAILURE:
        hypotheses.append(CauseHypothesis(
            description="A regression test failed, likely due to recent code changes.",
            confidence=0.75,
            evidence_references=["stderr_tail", "command"],
        ))
    elif category == FailureCategory.SYNTAX_ERROR:
        hypotheses.append(CauseHypothesis(
            description="Python syntax error detected during compilation.",
            confidence=0.85,
            evidence_references=["stderr_tail", "command"],
        ))
    elif category == FailureCategory.IMPORT_ERROR:
        hypotheses.append(CauseHypothesis(
            description="Missing import or module dependency.",
            confidence=0.7,
            evidence_references=["stderr_tail"],
        ))
    elif category == FailureCategory.MISSING_ARTIFACT:
        hypotheses.append(CauseHypothesis(
            description="Expected artifact file was missing or not generated.",
            confidence=0.8,
            evidence_references=["artifact_paths", "stderr_tail"],
        ))
    elif category == FailureCategory.YAML_PARSE_FAILURE:
        hypotheses.append(CauseHypothesis(
            description="YAML file parsing error detected.",
            confidence=0.85,
            evidence_references=["stderr_tail"],
        ))
    elif category == FailureCategory.TEXT_INTEGRITY_FAILURE:
        hypotheses.append(CauseHypothesis(
            description="Text integrity check failed - file format may be corrupted.",
            confidence=0.7,
            evidence_references=["stderr_tail"],
        ))
    elif category == FailureCategory.REMOTE_RAW_FAILURE:
        hypotheses.append(CauseHypothesis(
            description="Remote raw integrity check failed - file may exceed line limit.",
            confidence=0.7,
            evidence_references=["stderr_tail"],
        ))
    elif category == FailureCategory.TIMEOUT:
        hypotheses.append(CauseHypothesis(
            description="Command execution timed out before completion.",
            confidence=0.8,
            evidence_references=["stderr_tail", "command"],
        ))
    elif category == FailureCategory.SECRET_LEAK_RISK:
        hypotheses.append(CauseHypothesis(
            description="Secret scanner detected potential credential exposure.",
            confidence=0.9,
            evidence_references=["stderr_tail"],
        ))
    elif category == FailureCategory.CONTEXT_MISSING:
        hypotheses.append(CauseHypothesis(
            description="Required context pack or artifacts are missing.",
            confidence=0.75,
            evidence_references=["context_pack_path", "artifact_paths"],
        ))
    elif category == FailureCategory.CONTEXT_BUDGET_EXCEEDED:
        hypotheses.append(CauseHypothesis(
            description="Context budget exceeded - too much information for model.",
            confidence=0.8,
            evidence_references=["stderr_tail"],
        ))
    elif category == FailureCategory.PERMISSION_ERROR:
        hypotheses.append(CauseHypothesis(
            description="Permission denied when accessing file or resource.",
            confidence=0.85,
            evidence_references=["stderr_tail"],
        ))
    elif category == FailureCategory.NETWORK_DISABLED_OR_UNAVAILABLE:
        hypotheses.append(CauseHypothesis(
            description="Network connectivity issue prevented external API call.",
            confidence=0.75,
            evidence_references=["stderr_tail"],
        ))
    else:
        hypotheses.append(CauseHypothesis(
            description="Unknown failure - requires manual investigation.",
            confidence=0.4,
            evidence_references=["stderr_tail", "stdout_tail"],
        ))

    return hypotheses


def _build_evidence(event: FailureEvent, context_pack: dict | None) -> list[EvidenceItem]:
    """Build evidence list from failure event."""
    evidence = []

    # Add stderr evidence if available
    if event.stderr_tail:
        evidence.append(EvidenceItem(
            kind="stderr_tail",
            summary="Error output captured from failed command",
            source="failure_event.stderr_tail",
            confidence=0.9,
        ))

    # Add stdout evidence if available
    if event.stdout_tail:
        evidence.append(EvidenceItem(
            kind="stdout_tail",
            summary="Standard output captured from failed command",
            source="failure_event.stdout_tail",
            confidence=0.85,
        ))

    # Add artifact evidence
    for path in event.artifact_paths:
        evidence.append(EvidenceItem(
            kind="artifact_path",
            summary=f"Artifact path involved in failure: {path[:50]}",
            source="failure_event.artifact_paths",
            confidence=0.9,
        ))

    # Add context pack evidence
    if event.context_pack_path:
        evidence.append(EvidenceItem(
            kind="context_path",
            summary=f"Context pack path: {event.context_pack_path}",
            source="failure_event.context_pack_path",
            confidence=0.9,
        ))

    return evidence


def _assess_blast_radius(event: FailureEvent, category: FailureCategory) -> BlastRadius:
    """Assess the blast radius of the failure."""
    safe_retry = False
    safe_continue = False

    # Category-specific blast radius
    if category == FailureCategory.TEST_FAILURE:
        safe_retry = True
        safe_continue = False
    elif category == FailureCategory.SYNTAX_ERROR:
        safe_retry = False
        safe_continue = False
    elif category == FailureCategory.IMPORT_ERROR:
        safe_retry = True
        safe_continue = False
    elif category == FailureCategory.MISSING_ARTIFACT:
        safe_retry = True
        safe_continue = True
    elif category == FailureCategory.YAML_PARSE_FAILURE:
        safe_retry = False
        safe_continue = False
    elif category == FailureCategory.TEXT_INTEGRITY_FAILURE:
        safe_retry = False
        safe_continue = False
    elif category == FailureCategory.REMOTE_RAW_FAILURE:
        safe_retry = False
        safe_continue = False
    elif category == FailureCategory.TIMEOUT:
        safe_retry = True
        safe_continue = False
    elif category == FailureCategory.SECRET_LEAK_RISK:
        safe_retry = False
        safe_continue = False
    elif category == FailureCategory.CONTEXT_MISSING:
        safe_retry = True
        safe_continue = False
    elif category == FailureCategory.PERMISSION_ERROR:
        safe_retry = False
        safe_continue = False
    else:
        safe_retry = False
        safe_continue = False

    # Likely affected areas based on stage
    likely_affected = ["agent_runtime"]
    if event.stage:
        stage_lower = event.stage.lower()
        if "test" in stage_lower:
            likely_affected.append("tests")
        elif "runtime" in stage_lower:
            likely_affected.append("runtime")
        elif "config" in stage_lower:
            likely_affected.append("config")

    return BlastRadius(
        likely_affected=likely_affected,
        safe_to_retry=safe_retry,
        safe_to_continue=safe_continue,
    )


def _requires_human_review(category: FailureCategory) -> bool:
    """Determine if human review is required for this category."""
    human_review_required = {
        FailureCategory.SECRET_LEAK_RISK,
        FailureCategory.PERMISSION_ERROR,
        FailureCategory.REMOTE_RAW_FAILURE,
        FailureCategory.TEXT_INTEGRITY_FAILURE,
        FailureCategory.YAML_PARSE_FAILURE,
        FailureCategory.SYNTAX_ERROR,
        FailureCategory.UNKNOWN,
    }
    return category in human_review_required


def _generate_warnings(event: FailureEvent, category: FailureCategory) -> list[str]:
    """Generate warnings for the diagnosis."""
    warnings = []

    if category == FailureCategory.SECRET_LEAK_RISK:
        warnings.append("SECURITY WARNING: Potential credential exposure detected")
    elif category == FailureCategory.PERMISSION_ERROR:
        warnings.append("Permission issue detected - verify file permissions")
    elif category == FailureCategory.TEXT_INTEGRITY_FAILURE:
        warnings.append(" integrity check failed - do not lower thresholds")
    elif category == FailureCategory.REMOTE_RAW_FAILURE:
        warnings.append("Remote raw integrity failed - verify file format")

    return warnings


def _recommended_action(category: FailureCategory) -> str:
    """Generate recommended next action based on category."""
    actions = {
        FailureCategory.TEST_FAILURE: "create_recovery_plan -> retry with targeted test",
        FailureCategory.SYNTAX_ERROR: "create_recovery_plan -> run compileall, fix syntax",
        FailureCategory.IMPORT_ERROR: "create_recovery_plan -> install missing dependency",
        FailureCategory.MISSING_ARTIFACT: "create_recovery_plan -> regenerate artifact or fix upstream",
        FailureCategory.YAML_PARSE_FAILURE: "create_recovery_plan -> fix YAML syntax, validate",
        FailureCategory.TEXT_INTEGRITY_FAILURE: "create_recovery_plan -> fix file format, verify line counts",
        FailureCategory.REMOTE_RAW_FAILURE: "create_recovery_plan -> fix file format, push changes",
        FailureCategory.TIMEOUT: "create_recovery_plan -> increase timeout or optimize command",
        FailureCategory.SECRET_LEAK_RISK: "STOP - human_review required, redact secrets",
        FailureCategory.CONTEXT_MISSING: "create_recovery_plan -> regenerate context pack",
        FailureCategory.CONTEXT_BUDGET_EXCEEDED: "create_recovery_plan -> reduce context size",
        FailureCategory.PERMISSION_ERROR: "STOP - human_review required, fix permissions",
        FailureCategory.NETWORK_DISABLED_OR_UNAVAILABLE: "create_recovery_plan -> enable network or use mock",
        FailureCategory.UNKNOWN: "create_recovery_plan -> manual investigation required",
    }
    return actions.get(category, "create_recovery_plan -> manual investigation")
