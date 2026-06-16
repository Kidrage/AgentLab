"""Recovery plan: generates human-readable recovery plan Markdown."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from agent_runtime.recovery.failure_event import FailureEvent
from agent_runtime.recovery.failure_classifier import FailureCategory
from agent_runtime.recovery.diagnosis import FailureDiagnosis
from agent_runtime.recovery.retry_policy import RetryPolicyConfig


@dataclass
class RecoveryPlan:
    """Complete recovery plan for a failure."""

    task_id: str
    project: str
    summary: str
    failure_category: str
    secondary_categories: list[str]
    confidence: float
    evidence: list[str]
    likely_root_cause: list[str]
    recommended_action: str
    safe_commands: list[str]
    unsafe_commands: list[str]
    validation_plan: list[str]
    stop_conditions: list[str]
    created_at: str

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "task_id": self.task_id,
            "project": self.project,
            "summary": self.summary,
            "failure_category": self.failure_category,
            "secondary_categories": self.secondary_categories,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "likely_root_cause": self.likely_root_cause,
            "recommended_action": self.recommended_action,
            "safe_commands": self.safe_commands,
            "unsafe_commands": self.unsafe_commands,
            "validation_plan": self.validation_plan,
            "stop_conditions": self.stop_conditions,
            "created_at": self.created_at,
        }

    def to_markdown(self) -> str:
        """Convert to Markdown format."""
        lines = [
            f"# Recovery Plan",
            "",
            f"## Summary",
            "",
            self.summary,
            "",
            f"## Failure Category",
            "",
            f"Primary: **{self.failure_category}**",
            f"Confidence: **{self.confidence}**",
        ]

        if self.secondary_categories:
            lines.append(f"Secondary: {', '.join(self.secondary_categories)}")

        lines.extend([
            "",
            f"## Evidence",
            "",
        ])

        for item in self.evidence:
            lines.append(f"- {item}")

        lines.extend([
            "",
            f"## Likely Root Cause",
            "",
        ])

        for item in self.likely_root_cause:
            lines.append(f"- {item}")

        lines.extend([
            "",
            f"## Recommended Action",
            "",
            f"**{self.recommended_action}**",
            "",
            f"## Safe Commands",
            "",
        ])

        if self.safe_commands:
            for cmd in self.safe_commands:
                lines.append(f"```bash\n{cmd}\n```")
        else:
            lines.append("No safe commands recommended.")

        lines.extend([
            "",
            f"## Unsafe Commands Requiring Approval",
            "",
        ])

        if self.unsafe_commands:
            for cmd in self.unsafe_commands:
                lines.append(f"- {cmd}")
        else:
            lines.append("No dangerous commands detected.")

        lines.extend([
            "",
            f"## Validation Plan",
            "",
        ])

        for item in self.validation_plan:
            lines.append(f"- {item}")

        lines.extend([
            "",
            f"## Stop Conditions",
            "",
        ])

        for item in self.stop_conditions:
            lines.append(f"- {item}")

        lines.append("")
        return "\n".join(lines)

    def to_json_path(self, run_dir: Path) -> Path:
        """Return path for recovery_plan.md within run directory."""
        from pathlib import Path
        recovery_dir = run_dir / "recovery"
        recovery_dir.mkdir(parents=True, exist_ok=True)
        return recovery_dir / "recovery_plan.md"


def build_recovery_plan(
    failure_event: FailureEvent,
    diagnosis: FailureDiagnosis,
    policy: RetryPolicyConfig,
) -> RecoveryPlan:
    """Build a recovery plan based on failure event and diagnosis.

    Args:
        failure_event: The captured failure event
        diagnosis: The failure diagnosis with root cause hypothesis
        policy: The retry policy configuration

    Returns:
        RecoveryPlan with recommended actions and commands
    """
    # Build evidence list from diagnosis
    evidence = [e.summary for e in diagnosis.evidence]

    # Build root cause list from diagnosis
    root_cause = [h.description for h in diagnosis.root_cause_hypothesis]

    # Generate recommended action
    recommended = _recommended_action(diagnosis.primary_category)

    # Generate safe commands based on category
    safe_commands = _safe_commands(diagnosis.primary_category, policy)

    # Generate unsafe commands
    unsafe_commands = _unsafe_commands(diagnosis.primary_category, policy)

    # Generate validation plan
    validation = _validation_plan(diagnosis.primary_category, policy)

    # Generate stop conditions
    stop_conditions = _stop_conditions(diagnosis.primary_category, diagnosis.requires_human_review)

    return RecoveryPlan(
        task_id=failure_event.task_id,
        project=failure_event.project,
        summary=_build_summary(failure_event, diagnosis),
        failure_category=diagnosis.primary_category.value,
        secondary_categories=[c.value for c in diagnosis.secondary_categories],
        confidence=diagnosis.confidence,
        evidence=evidence,
        likely_root_cause=root_cause,
        recommended_action=recommended,
        safe_commands=safe_commands,
        unsafe_commands=unsafe_commands,
        validation_plan=validation,
        stop_conditions=stop_conditions,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def _build_summary(event: FailureEvent, diagnosis: FailureDiagnosis) -> str:
    """Build a one-sentence summary of the failure and recovery."""
    if diagnosis.requires_human_review:
        return (
            f"Failure in {event.stage} stage requires immediate human review. "
            f"Category: {diagnosis.primary_category.value}. "
            f"Confidence: {diagnosis.confidence}."
        )
    return (
        f"Failure in {event.stage} stage classified as {diagnosis.primary_category.value}. "
        f"Recovery plan generated with {len(diagnosis.root_cause_hypothesis)} hypothesis(es)."
    )


def _recommended_action(category: FailureCategory) -> str:
    """Generate recommended action based on category."""
    actions = {
        FailureCategory.TEST_FAILURE: "retry -> fix and rerun relevant tests",
        FailureCategory.SYNTAX_ERROR: "fix -> run compileall, identify and fix syntax error",
        FailureCategory.IMPORT_ERROR: "fix -> install missing dependency or fix import path",
        FailureCategory.MISSING_ARTIFACT: "continue -> regenerate artifact from upstream",
        FailureCategory.YAML_PARSE_FAILURE: "fix -> correct YAML syntax, validate with YAML parser",
        FailureCategory.TEXT_INTEGRITY_FAILURE: "fix -> restore proper line format, do not lower thresholds",
        FailureCategory.REMOTE_RAW_FAILURE: "fix -> correct file format, push to remote",
        FailureCategory.TIMEOUT: "retry -> increase timeout or optimize command execution",
        FailureCategory.SECRET_LEAK_RISK: "STOP - human_review required",
        FailureCategory.CONTEXT_MISSING: "retry -> regenerate context pack",
        FailureCategory.CONTEXT_BUDGET_EXCEEDED: "fix -> reduce source count, adjust compression",
        FailureCategory.PERMISSION_ERROR: "STOP - human_review required",
        FailureCategory.NETWORK_DISABLED_OR_UNAVAILABLE: "retry -> enable network or use mock/dry-run",
        FailureCategory.UNKNOWN: "human_review -> manual investigation required",
    }
    return actions.get(category, "human_review -> manual investigation needed")


def _safe_commands(category: FailureCategory, policy: RetryPolicyConfig) -> list[str]:
    """Generate list of safe commands for this category."""
    safe = []

    # Always include these basic safe commands
    safe.extend([
        "./agentlab.sh check",
        "python -m compileall agent_runtime agentlab_app.py",
        "./agentlab.sh context-smoke --project AgentLab",
    ])

    # Category-specific safe commands
    if category == FailureCategory.TEST_FAILURE:
        safe.append("python -m pytest -q tests/ -v --tb=short")
    elif category == FailureCategory.SYNTAX_ERROR:
        safe.append("python -m compileall agent_runtime agentlab_app.py -q")
    elif category == FailureCategory.MISSING_ARTIFACT:
        safe.append("./agentlab.sh check")
    elif category == FailureCategory.YAML_PARSE_FAILURE:
        safe.append("python -c 'import yaml; yaml.safe_load(open(file))'")
    elif category == FailureCategory.TEXT_INTEGRITY_FAILURE:
        safe.append("./agentlab.sh check")
        safe.append("python scripts/audit_text_integrity.py")
    elif category == FailureCategory.CONTEXT_MISSING:
        safe.append("./agentlab.sh context-build --project AgentLab")
    elif category == FailureCategory.TIMEOUT:
        safe.append("bash -n agentlab.sh")

    # Add policy-defined safe commands
    if policy.safe_commands:
        safe.extend(policy.safe_commands[:3])

    return safe[:10]  # Limit to top 10


def _unsafe_commands(category: FailureCategory, policy: RetryPolicyConfig) -> list[str]:
    """Generate list of unsafe commands that require approval."""
    unsafe = []

    # Category-specific unsafe commands
    if category == FailureCategory.SECRET_LEAK_RISK:
        unsafe.append("DO NOT output or log secrets")
        unsafe.append("DO NOT commit files containing credentials")
    elif category == FailureCategory.REMOTE_RAW_FAILURE:
        unsafe.append("DO NOT force push to remote")
    elif category == FailureCategory.TEXT_INTEGRITY_FAILURE:
        unsafe.append("DO NOT lower integrity thresholds")

    # Add forbidden commands from policy
    if policy.forbidden_auto_commands:
        unsafe.extend(policy.forbidden_auto_commands[:5])

    return list(set(unsafe))  # Remove duplicates


def _validation_plan(category: FailureCategory, policy: RetryPolicyConfig) -> list[str]:
    """Generate validation steps after recovery."""
    validation = []

    # Core validation steps
    validation.append("Run full pytest suite")
    validation.append("Run text integrity checker")
    validation.append("Run context-smoke")
    validation.append("Run agentlab.sh check")

    # Category-specific validation
    if category == FailureCategory.TEST_FAILURE:
        validation.append("Verify specific test file passes")
    elif category == FailureCategory.SYNTAX_ERROR:
        validation.append("Verify compileall passes on all modules")
    elif category == FailureCategory.YAML_PARSE_FAILURE:
        validation.append("Validate all YAML files with yaml.safe_load()")
    elif category == FailureCategory.TEXT_INTEGRITY_FAILURE:
        validation.append("Verify file format matches requirements")
        validation.append("Check line count thresholds")

    return validation


def _stop_conditions(category: FailureCategory, requires_human_review: bool) -> list[str]:
    """Generate stop conditions for recovery process."""
    stop = []

    if requires_human_review:
        stop.append("If secret leak is confirmed - STOP immediately")
    if category == FailureCategory.PERMISSION_ERROR:
        stop.append("If permission issue persists - STOP and involve sysadmin")
    if category == FailureCategory.SYNTAX_ERROR:
        stop.append("If syntax error cannot be found - STOP and review file manually")

    # Always add these general stop conditions
    stop.append("If new errors are introduced - STOP")
    stop.append("If recovery takes longer than expected - STOP and review")
    stop.append("If destructive recovery action is required - STOP and get approval")

    return stop
