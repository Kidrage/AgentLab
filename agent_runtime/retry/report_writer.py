from __future__ import annotations

from pathlib import Path

from agent_runtime.atomic_io import atomic_write_text, atomic_write_yaml
from agent_runtime.retry.models import RetryLoopState, to_plain_data
from agent_runtime.retry.scorecard import load_provider_scorecard


def write_retry_loop_artifacts(output_dir: Path, state: RetryLoopState) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_yaml(output_dir / "retry_loop_state.yml", to_plain_data(state))
    atomic_write_text(output_dir / "retry_loop_report.md", render_retry_loop_report(output_dir, state))
    if state.accepted:
        accepted = next((attempt for attempt in reversed(state.attempts) if attempt.review_verdict), None)
        atomic_write_yaml(
            output_dir / "final_acceptance_receipt.yml",
            {
                "task_id": state.task_id,
                "accepted": True,
                "final_verdict": state.final_verdict,
                "accepted_attempt_id": accepted.attempt_id if accepted else None,
                "review_required": True,
                "review_completed": bool(accepted and accepted.review_verdict),
                "review_verdict_path": accepted.review_verdict if accepted else None,
                "unreviewed_result_accepted": False,
            },
        )
    else:
        atomic_write_yaml(
            output_dir / "final_rejection_receipt.yml",
            {
                "task_id": state.task_id,
                "accepted": False,
                "final_verdict": state.final_verdict,
                "status": state.status,
                "attempts": len(state.attempts),
                "unreviewed_result_accepted": False,
            },
        )


def render_retry_loop_report(output_dir: Path, state: RetryLoopState) -> str:
    scorecard = load_provider_scorecard(output_dir / "provider_scorecard.yml")
    attempt_lines = [
        f"- {item.attempt_id}: provider={item.provider_id}, mode={item.execution_mode}, status={item.status}, review={item.review_verdict or 'none'}"
        for item in state.attempts
    ] or ["- No attempts recorded."]
    decision_lines = [
        f"- {item.status}: {', '.join(item.reason) or item.next_action}"
        for item in state.decisions
    ] or ["- No retry decisions recorded."]
    provider_lines = [
        f"- {item.get('provider_id')}: attempts={item.get('attempts')}, last={item.get('last_verdict')}, avg={item.get('average_quality_score')}"
        for item in scorecard.get("providers", [])
    ] or ["- No provider scorecard entries."]
    return "\n".join(
        [
            "# AgentLab Acceptance-to-Retry Loop Report",
            "",
            "## Summary",
            f"- accepted: {state.accepted}",
            f"- status: {state.status}",
            "",
            "## Task",
            f"- task_id: {state.task_id}",
            f"- task_type: {state.task_type}",
            "",
            "## Attempts",
            *attempt_lines,
            "",
            "## Review Verdicts",
            *[f"- {item.attempt_id}: {item.review_verdict or 'unreviewed'}" for item in state.attempts],
            "",
            "## Retry Decisions",
            *decision_lines,
            "",
            "## Provider Scorecard",
            *provider_lines,
            "",
            "## Final Verdict",
            f"- {state.final_verdict or state.status}",
            "",
            "## Safety Notes",
            "- No real Codex, Cline, ECC, API model, network, clone, MCP, or shell execution is performed by the retry loop.",
            "- Unreviewed results are never accepted.",
            "",
            "## Known Limitations",
            "- Mock retry artifacts are deterministic and local.",
            "- Budget accounting is policy-level until connected to CostLedger v2.",
            "",
        ]
    )
