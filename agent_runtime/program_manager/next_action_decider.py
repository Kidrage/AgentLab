from __future__ import annotations

from typing import Any


def decide_verdict(
    scope_status: dict[str, Any],
    evidence_status: dict[str, Any],
    test_results: dict[str, Any] | None,
    human_approval_required: bool,
) -> dict[str, Any]:
    """Decide the verdict and recommended next action for phase acceptance."""
    verdict = "accept"
    recommended_next_action = "next_phase"
    rationale = []

    # 1. Check unauthorized edits (violations)
    if scope_status.get("has_violations"):
        verdict = "rollback"
        recommended_next_action = "rollback_phase"
        violations = scope_status.get("unauthorized_edits", [])
        rationale.append(f"Unauthorized edits detected in forbidden files: {violations}")

    # 2. Check test failures
    elif test_results and not test_results.get("passed", True):
        verdict = "retry"
        recommended_next_action = "retry_same"
        failed_count = test_results.get("failed_count", 0)
        rationale.append(f"Test suite failed with {failed_count} failures.")

    # 3. Check missing evidence
    elif evidence_status.get("has_missing"):
        verdict = "blocked"
        recommended_next_action = "ask_user"
        missing = evidence_status.get("missing_evidence", [])
        rationale.append(f"Missing required evidence files: {missing}")

    # 4. Check scope drift
    elif scope_status.get("has_drift"):
        # Drift is warnings only unless human decides otherwise, default to ask_user if severe
        verdict = "ask_user"
        recommended_next_action = "ask_user"
        drift = scope_status.get("scope_drift", [])
        rationale.append(f"Scope drift detected in files: {drift}")

    # 5. Check human approval required
    elif human_approval_required:
        verdict = "ask_user"
        recommended_next_action = "ask_user"
        rationale.append("Human approval gate is explicitly required for this phase.")

    # 6. Default PASS
    else:
        verdict = "accept"
        recommended_next_action = "next_phase"
        rationale.append("All scope checks, evidence requirements, and validations passed successfully.")

    return {
        "verdict": verdict,
        "recommended_next_action": recommended_next_action,
        "rationale": " ".join(rationale),
    }
