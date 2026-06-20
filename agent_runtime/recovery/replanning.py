from __future__ import annotations

from pathlib import Path
from typing import Any
import yaml

from agent_runtime.atomic_io import atomic_write_yaml, atomic_write_text


def replan_phase(
    acceptance_result: dict[str, Any],
    project_brain_dir: Path | None = None,
    out_dir: Path | None = None,
    retry_limit: int = 3,
) -> dict[str, Any]:
    """Execute phase-level replanning based on acceptance failure."""
    phase_id = acceptance_result.get("phase_id", "unknown")
    verdict = acceptance_result.get("verdict", "RETRY")
    
    # 1. Determine retry count from acceptance history in project brain
    retry_count = 0
    history = {"entries": []}
    if project_brain_dir and project_brain_dir.is_dir():
        history_path = project_brain_dir / "acceptance_history.yml"
        if history_path.exists():
            try:
                history = yaml.safe_load(history_path.read_text(encoding="utf-8")) or {"entries": []}
                for entry in history.get("entries") or []:
                    if entry.get("phase_id") == phase_id and not entry.get("accepted"):
                        retry_count += 1
            except Exception:
                pass

    # 2. Map failure reason (Failure Taxonomy)
    failure_reason = "unknown"
    missing_evidence = acceptance_result.get("missing_evidence") or []
    scope_status = acceptance_result.get("scope_status") or {}
    test_results = acceptance_result.get("test_results") or {}
    
    if missing_evidence:
        failure_reason = "evidence_missing"
    elif scope_status.get("has_violations"):
        failure_reason = "scope_drift"
    elif test_results and not test_results.get("passed", True):
        failure_reason = "artifact_failed_validation"
    elif acceptance_result.get("verdict_details") == "blocked":
        failure_reason = "capability_gap"
    
    # Check if budget was exceeded (can be flagged in test_results or a custom field)
    if test_results.get("budget_exceeded") or acceptance_result.get("budget_exceeded"):
        failure_reason = "budget_exceeded"

    # 3. Determine next action (Next Actions)
    next_action = "retry_same"
    rationale = []

    if failure_reason == "evidence_missing":
        next_action = "ask_user"
        rationale.append("Evidence is missing and phase cannot pass automatically.")
    
    elif failure_reason == "capability_gap":
        next_action = "ask_user"  # Generates decision card
        rationale.append("Capability gap detected; user intervention required to install or mock the capability.")
        # Create capability gap decision card
        if out_dir:
            card = {
                "required_capability": acceptance_result.get("required_capability", "unknown"),
                "reason": "Missing required backend capability for execution",
                "available_backends": [],
                "missing_backend_reason": "No supported provider configured",
                "approval_options": ["install_capability", "mock_capability", "skip_phase"],
                "recommended_next_action": "install_capability",
                "risk_notes": "Execution will fail until a suitable backend is provided.",
            }
            atomic_write_yaml(out_dir / "capability_gap_decision_card.yml", card)

    elif failure_reason == "budget_exceeded":
        next_action = "stop_safely"
        rationale.append("Budget limit reached; execution stopped safely to prevent cost overrun.")
        
    elif failure_reason == "scope_drift":
        next_action = "rollback_phase"
        rationale.append("Scope violations detected; rolling back phase changes to restore workspace hygiene.")

    else:
        # Capped retry logic
        if retry_count >= retry_limit:
            next_action = "ask_user"
            rationale.append(f"Retry limit of {retry_limit} reached. Escalating to user review.")
        else:
            next_action = "retry_same"
            rationale.append(f"Phase failed validation tests. Triggering retry {retry_count + 1} of {retry_limit}.")

    replan_report = {
        "phase_id": phase_id,
        "verdict": verdict,
        "failure_reason": failure_reason,
        "retry_count": retry_count,
        "recommended_next_action": next_action,
        "rationale": " ".join(rationale),
        "policy": {
            "retry_limit": retry_limit,
            "escalate_on_limit": True,
        }
    }

    # 4. Write replanning plan
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_yaml(out_dir / "replan_plan.yml", replan_report)
        atomic_write_text(out_dir / "replan_plan.md", _render_replan_md(replan_report))

    # 5. Update project brain files if available
    if project_brain_dir and project_brain_dir.is_dir():
        # Update next_actions.yml
        next_actions_path = project_brain_dir / "next_actions.yml"
        next_actions = {
            "next_phase_id": phase_id,
            "next_action": next_action,
            "reason": f"replan verdict: {failure_reason}",
        }
        atomic_write_yaml(next_actions_path, next_actions)

        # Update acceptance_history.yml
        history_path = project_brain_dir / "acceptance_history.yml"
        entries = history.get("entries") or []
        entries.append({
            "phase_id": phase_id,
            "accepted": False,
            "verdict": verdict,
            "reason": failure_reason,
        })
        atomic_write_yaml(history_path, {"entries": entries})

    return replan_report


def _render_replan_md(report: dict[str, Any]) -> str:
    """Generate Markdown for the replanning plan."""
    return "\n".join([
        f"# AgentLab Phase Replanning Report: {report.get('phase_id')}",
        "",
        "## Verdict & Next Action",
        f"- **Verdict**: `{report.get('verdict')}`",
        f"- **Failure Reason**: `{report.get('failure_reason')}`",
        f"- **Retry Count**: {report.get('retry_count')}",
        f"- **Recommended Next Action**: `{report.get('recommended_next_action')}`",
        f"- **Rationale**: {report.get('rationale')}",
        "",
        "---",
        "*Report generated by AgentLab Phase Recovery Engine.*"
    ]) + "\n"
