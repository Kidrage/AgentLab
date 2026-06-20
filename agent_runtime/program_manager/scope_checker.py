from __future__ import annotations

from typing import Any


def check_scope(phase_plan: dict[str, Any], changed_files: list[str]) -> dict[str, Any]:
    """Check changed files against allowed and forbidden file lists to detect drift/violations."""
    plan = phase_plan.get("task_packet") or phase_plan
    allowed_files = plan.get("allowed_files") or []
    forbidden_files = plan.get("forbidden_files") or []

    unauthorized_edits = []
    scope_drift = []

    for file in changed_files:
        # Check forbidden files
        if any(f == file or file.startswith(f + "/") for f in forbidden_files):
            unauthorized_edits.append(file)
        
        # Check allowed files if the list is non-empty
        if allowed_files:
            is_allowed = False
            for allowed in allowed_files:
                norm_allowed = allowed.rstrip("/")
                if file == norm_allowed or file.startswith(norm_allowed + "/"):
                    is_allowed = True
                    break
            if not is_allowed:
                scope_drift.append(file)

    has_drift = len(scope_drift) > 0
    has_violations = len(unauthorized_edits) > 0

    return {
        "allowed_files": allowed_files,
        "forbidden_files": forbidden_files,
        "changed_files": changed_files,
        "unauthorized_edits": unauthorized_edits,
        "scope_drift": scope_drift,
        "has_drift": has_drift,
        "has_violations": has_violations,
    }
