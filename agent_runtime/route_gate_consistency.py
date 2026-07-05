"""Route–gate consistency validation.

Ensures the selected agent route and the required validation gates are
consistent before the task packet is finalised.  Contradictions such as
"implementation_report required but Coder skipped" are caught here
rather than silently producing broken task packets.
"""

from __future__ import annotations

import dataclasses
from typing import Any


# ── Implementation executor agent names ──────────────────────────────────
# These agents are the ones that can produce implementation artifacts
# (patches, diffs, test files, code changes).
IMPLEMENTATION_EXECUTORS: frozenset[str] = frozenset({
    "Coder",
    "external_ide_ai",
    "manual_patch_submitter",
    "claude_code",
})


# ── Artifacts that signal implementation work ────────────────────────────
IMPLEMENTATION_ARTIFACTS: frozenset[str] = frozenset({
    "implementation_report",
    "06_implementation_report.md",
    "implementation_report.md",
    "patch",
    "diff",
    "changed_files",
})


# ── Canonical owner for implementation artifacts ─────────────────────────
ARTIFACT_OWNER_MAP: dict[str, frozenset[str]] = {
    "implementation_report": IMPLEMENTATION_EXECUTORS,
    "06_implementation_report.md": IMPLEMENTATION_EXECUTORS,
    "implementation_report.md": IMPLEMENTATION_EXECUTORS,
    "patch": IMPLEMENTATION_EXECUTORS,
    "diff": IMPLEMENTATION_EXECUTORS,
    "changed_files": IMPLEMENTATION_EXECUTORS,
    "validation_report": frozenset({"TesterAuditor", "Verifier"}),
    "audit_report": frozenset({"TesterAuditor", "Verifier"}),
    "supervisor_plan": frozenset({"Supervisor"}),
    "design_report": frozenset({"Supervisor", "Researcher", "RepoScout"}),
    "analysis_report": frozenset({"Supervisor", "Researcher", "RepoScout", "InterfaceMapper"}),
    "routing_report": frozenset({"Supervisor"}),
    "archive_update": frozenset({"Archivist"}),
}


@dataclasses.dataclass
class RouteGateConsistencyError:
    """A single contradiction between route and gates."""

    code: str
    """Machine-readable error code, e.g. ``implementation_report_requires_missing_executor``."""

    message: str
    """Human-readable description."""


def validate_route_gate_consistency(
    route_agents: list[str],
    validation_gates: list[dict[str, Any]],
    *,
    intent: str = "unknown",
) -> list[RouteGateConsistencyError]:
    """Check that *route_agents* can satisfy every required gate in *validation_gates*.

    Args:
        route_agents: Selected agent names, e.g. ``["Supervisor", "Coder"]``.
        validation_gates: List of gate dicts.  Each gate may have ``id``,
            ``owner``, ``required``, ``evidence``, and
            ``required_artifacts`` fields.
        intent: The classified task intent — ``"implementation_required"``,
            ``"analysis_only"``, or ``"unknown"``.

    Returns:
        A list of :class:`RouteGateConsistencyError` (empty = consistent).
    """
    errors: list[RouteGateConsistencyError] = []
    route_set = set(route_agents)

    for gate in validation_gates:
        if not isinstance(gate, dict):
            continue

        gate_id: str = gate.get("id", "")
        owner: str = gate.get("owner", "")
        required: bool = gate.get("required", False)
        evidence: list[str] = gate.get("evidence", []) or []
        required_artifacts: list[str] = gate.get("required_artifacts", []) or []

        # ── Rule 1: implementation_report gate requires an impl executor ─
        if gate_id in {"implementation_report"} and required:
            if owner in IMPLEMENTATION_EXECUTORS and not (route_set & IMPLEMENTATION_EXECUTORS):
                errors.append(RouteGateConsistencyError(
                    code="implementation_report_requires_missing_executor",
                    message=(
                        f"Gate '{gate_id}' requires implementation owner '{owner}' but "
                        f"no implementation executor is in the selected route. "
                        f"Route agents: {route_agents}. "
                        f"Either add an implementation executor or downgrade "
                        f"the gate to analysis-only."
                    ),
                ))
            # Owner is a non-impl executor (shouldn't happen but guard)
            if owner not in IMPLEMENTATION_EXECUTORS and required:
                if not (route_set & IMPLEMENTATION_EXECUTORS):
                    errors.append(RouteGateConsistencyError(
                        code="implementation_report_no_executor",
                        message=(
                            f"Gate '{gate_id}' requires an implementation "
                            f"report but no implementation executor "
                            f"(Coder / external_ide_ai / manual_patch_submitter) "
                            f"is in the route. Route agents: {route_agents}."
                        ),
                    ))

        # ── Rule 2: evidence artifacts must be producible ────────────────
        for artifact in evidence + required_artifacts:
            # Strip directory prefix for matching
            base = artifact.rsplit("/", 1)[-1] if "/" in artifact else artifact
            # Map to canonical artifact id
            artifact_id = (
                "implementation_report" if base in IMPLEMENTATION_ARTIFACTS
                else base.replace(".md", "").replace("_", " ")
            )

            allowed_owners = ARTIFACT_OWNER_MAP.get(
                artifact, ARTIFACT_OWNER_MAP.get(base, None)
            )
            if allowed_owners is not None:
                if not (route_set & allowed_owners):
                    errors.append(RouteGateConsistencyError(
                        code="artifact_requires_missing_executor",
                        message=(
                            f"Gate '{gate_id}' requires artifact '{artifact}' "
                            f"which can only be produced by {sorted(allowed_owners)}. "
                            f"None of these are in the route. "
                            f"Route agents: {route_agents}."
                        ),
                    ))

        # ── Rule 3: analysis-only intent with implementation gates ───────
        if intent == "analysis_only":
            # Check gate id itself
            if gate_id in IMPLEMENTATION_ARTIFACTS:
                errors.append(RouteGateConsistencyError(
                    code="analysis_only_requires_implementation_artifact",
                    message=(
                        f"Intent is 'analysis_only' but gate '{gate_id}' "
                        f"is an implementation artifact gate. "
                        f"Remove the gate or change the intent."
                    ),
                ))
            # Check evidence and required_artifacts
            for artifact in evidence + required_artifacts:
                base = artifact.rsplit("/", 1)[-1] if "/" in artifact else artifact
                if base in IMPLEMENTATION_ARTIFACTS:
                    errors.append(RouteGateConsistencyError(
                        code="analysis_only_requires_implementation_artifact",
                        message=(
                            f"Intent is 'analysis_only' but gate '{gate_id}' "
                            f"requires implementation artifact '{artifact}'. "
                            f"Remove the gate or change the intent."
                        ),
                    ))

        # ── Rule 4: implementation intent with no executor available ─────
        if intent == "implementation_required":
            if not (route_set & IMPLEMENTATION_EXECUTORS):
                errors.append(RouteGateConsistencyError(
                    code="implementation_required_but_no_executor",
                    message=(
                        f"Intent is 'implementation_required' but no "
                        f"implementation executor (Coder / external_ide_ai / "
                        f"manual_patch_submitter) is in the route. "
                        f"Route agents: {route_agents}. "
                        f"Task must be blocked until an executor is available."
                    ),
                ))

    return errors


def format_consistency_errors(
    errors: list[RouteGateConsistencyError],
) -> str:
    """Format consistency errors as a human-readable block."""
    if not errors:
        return "✅ Route–gate consistency: OK"

    lines = ["❌ Route–gate consistency errors:"]
    for i, err in enumerate(errors, 1):
        lines.append(f"  [{i}] {err.code}")
        lines.append(f"      {err.message}")
    return "\n".join(lines)
