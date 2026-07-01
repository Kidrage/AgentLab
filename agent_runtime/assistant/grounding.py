"""M3-8 Assistant grounding — answers cite concrete records from Operator State."""

from __future__ import annotations

from pathlib import Path

from agent_runtime.assistant.models import (
    AssistantAnswer,
    AssistantGroundingSource,
    AssistantQuestion,
)
from agent_runtime.assistant.state_reader import read_project_state
from agent_runtime.assistant.modes import get_mode


def answer_question(question: AssistantQuestion, root: Path | None = None) -> AssistantAnswer:
    """Answer an operator question using M3 Operator State as the single data source.

    Every answer must cite concrete source files from acceptance_history,
    next_actions, fact_snapshot, artifact_index, cost ledger, timeline, or
    config records. If the relevant record is missing, confidence is "none"
    and the answer points to the required evidence or command.
    """
    if root is None:
        root = Path.cwd()

    mode = get_mode(question.mode)
    snapshot = read_project_state(question.project, root)

    if not snapshot.known:
        return AssistantAnswer(
            mode=question.mode,
            question=question.question,
            answer=f"Project '{question.project}' is unavailable/not known. "
                   f"Project Brain files may be missing. Run 'agentlab.sh project-status --project {question.project}' to check.",
            grounding_sources=[],
            warnings=["project directory not found"],
            confidence="none",
            next_safe_action="Run project-status to diagnose.",
        )

    # route to appropriate answer strategy
    q_lower = question.question.lower()
    if "blocked" in q_lower or "why" in q_lower and "blocked" in q_lower:
        answer, sources, next_safe = _answer_why_blocked(snapshot, question)
    elif "evidence" in q_lower and "missing" in q_lower:
        answer, sources, next_safe = _answer_evidence_missing(snapshot, question)
    elif "failed" in q_lower or "fail" in q_lower:
        answer, sources, next_safe = _answer_executor_failed(snapshot, question)
    elif "approve" in q_lower or "reject" in q_lower:
        answer, sources, next_safe = _answer_approval_guidance(snapshot, question)
    elif "fact" in q_lower and ("changed" in q_lower or "snapshot" in q_lower):
        answer, sources, next_safe = _answer_fact_changes(snapshot, question)
    elif "cost" in q_lower or "spend" in q_lower or "spent" in q_lower:
        answer, sources, next_safe = _answer_cost(snapshot, question)
    elif "next" in q_lower or "safe" in q_lower:
        answer, sources, next_safe = _answer_next_safe_action(snapshot, question)
    else:
        answer, sources, next_safe = _answer_general(snapshot, question)

    return AssistantAnswer(
        mode=question.mode,
        question=question.question,
        answer=answer,
        grounding_sources=sources,
        warnings=snapshot.warnings if answer else [],
        confidence="high" if sources else "low",
        next_safe_action=next_safe,
    )


def _get_next_safe_action(snapshot) -> str:
    """Extract next safe action from snapshot if the field exists."""
    return getattr(snapshot, 'next_safe_action', '') or ""


def _source(path: str, reason: str) -> AssistantGroundingSource:
    return AssistantGroundingSource(path=path, reason=reason)


# ── answer strategies ──────────────────────────────────────────────────────

def _answer_why_blocked(snapshot, question: AssistantQuestion):
    project = question.project
    if not snapshot.blocked_items:
        answer = (
            f"Project '{project}' has no blocked items. "
            f"All phases are proceeding. Check acceptance history for details."
        )
        sources = [
            _source(f"projects/{project}/project_brain/acceptance_history.yml",
                    "phase acceptance status"),
        ]
        next_safe = _get_next_safe_action(snapshot)
        return answer, sources, next_safe

    items = "\n".join(f"  - {item}" for item in snapshot.blocked_items)
    answer = (
        f"Project '{project}' has {len(snapshot.blocked_items)} blocked item(s):\n{items}\n\n"
        f"Check acceptance_history.yml and next_actions.yml for resolution steps."
    )
    sources = [
        _source(f"projects/{project}/project_brain/acceptance_history.yml",
                "blocked phase identification"),
        _source(f"projects/{project}/project_brain/next_actions.yml",
                "recommended next action"),
    ]
    next_safe = _get_next_safe_action(snapshot)
    return answer, sources, next_safe


def _answer_evidence_missing(snapshot, question: AssistantQuestion):
    project = question.project
    # find needs_evidence phases
    needs_ev = [
        f"{pid}: {status}"
        for pid, status in snapshot.phase_statuses.items()
        if status == "needs_evidence"
    ]
    if not needs_ev:
        answer = (
            f"Project '{project}' has no phases reporting missing evidence. "
            f"All evidence gates appear satisfied."
        )
        sources = [
            _source(f"projects/{project}/project_brain/acceptance_history.yml",
                    "evidence requirement check"),
        ]
        next_safe = _get_next_safe_action(snapshot)
        return answer, sources, next_safe

    details = "\n".join(f"  - {item}" for item in needs_ev)
    answer = (
        f"The following phases need additional evidence:\n{details}\n\n"
        f"Run 'agentlab.sh run-agent TesterAuditor --project {project}' "
        f"to generate missing evidence, or request external evidence via the operator console."
    )
    sources = [
        _source(f"projects/{project}/project_brain/acceptance_history.yml",
                "missing evidence enumeration"),
        _source(f"projects/{project}/runs/*/evidence_ledger.yml",
                "available evidence ledgers"),
    ]
    next_safe = "Collect missing evidence for the listed phases."
    return answer, sources, next_safe


def _answer_executor_failed(snapshot, question: AssistantQuestion):
    project = question.project
    answer = (
        f"Project '{project}' executor status: check the observability timeline "
        f"and recovery plans for failure details. "
        f"Recovery events recorded: {len(snapshot.recovery_events)}."
    )
    sources = [
        _source(f"projects/{project}/project_brain/acceptance_history.yml",
                "executor result verdicts"),
        _source(f"projects/{project}/runs/*/recovery/recovery_plan.yml",
                "recovery plans"),
    ]
    next_safe = _get_next_safe_action(snapshot) or "Review executor failures and recovery plans."
    return answer, sources, next_safe


def _answer_approval_guidance(snapshot, question: AssistantQuestion):
    project = question.project
    pending = snapshot.pending_approvals
    if not pending:
        answer = f"Project '{project}' has no pending approvals. All gates are cleared."
        sources = [
            _source(f"projects/{project}/project_brain/acceptance_history.yml",
                    "approval status"),
        ]
        next_safe = _get_next_safe_action(snapshot)
        return answer, sources, next_safe

    items = "\n".join(f"  - {item}" for item in pending)
    answer = (
        f"The following items await operator approval:\n{items}\n\n"
        f"Use the TUI or WebUI to approve or reject each item with actor and reason."
    )
    sources = [
        _source(f"projects/{project}/project_brain/acceptance_history.yml",
                "pending approval enumeration"),
        _source(f"projects/{project}/runs/*/decision_cards/",
                "decision card details"),
    ]
    next_safe = "Approve or reject pending items via operator console."
    return answer, sources, next_safe


def _answer_fact_changes(snapshot, question: AssistantQuestion):
    project = question.project
    answer = (
        f"Project '{project}' fact state: check project_fact_snapshot.yml "
        f"and acceptance_history.yml for recent state transitions."
    )
    sources = [
        _source(f"projects/{project}/project_brain/project_fact_snapshot.yml",
                "current fact snapshot"),
        _source(f"projects/{project}/project_brain/acceptance_history.yml",
                "state transition history"),
    ]
    next_safe = _get_next_safe_action(snapshot)
    return answer, sources, next_safe


def _answer_cost(snapshot, question: AssistantQuestion):
    project = question.project
    cost = snapshot.cost_summary
    if cost == 0.0:
        answer = (
            f"Project '{project}': no cost data available. "
            f"Run cost ledger generation to populate cost records."
        )
        sources = []
        next_safe = "Generate cost ledger."
        return answer, sources, next_safe

    answer = (
        f"Project '{project}' total estimated cost: ${cost:.4f}. "
        f"Check per-task cost ledgers for detailed attribution."
    )
    sources = [
        _source(f"projects/{project}/runs/*/cost_ledger.yml",
                "per-task cost ledger"),
        _source(f"costs/cost_ledger.jsonl",
                "global cost ledger"),
    ]
    next_safe = _get_next_safe_action(snapshot)
    return answer, sources, next_safe


def _answer_next_safe_action(snapshot, question: AssistantQuestion):
    project = question.project
    next_safe = _get_next_safe_action(snapshot)
    answer = (
        f"Next safe action for '{project}' comes from acceptance_history.yml "
        f"and next_actions.yml: {next_safe or 'no action recorded'}. "
        f"Never infer progress from directory layout or loose artifacts."
    )
    sources = [
        _source(f"projects/{project}/project_brain/acceptance_history.yml",
                "acceptance history (progress truth source)"),
        _source(f"projects/{project}/project_brain/next_actions.yml",
                "next actions (derived from acceptance history)"),
    ]
    return answer, sources, next_safe or ""


def _answer_general(snapshot, question: AssistantQuestion):
    project = question.project
    answer = (
        f"Project '{project}' status: {snapshot.current_phase or 'unknown'}. "
        f"Blocked items: {len(snapshot.blocked_items)}. "
        f"Pending approvals: {len(snapshot.pending_approvals)}. "
        f"Estimated cost: ${snapshot.cost_summary:.4f}. "
        f"For specific questions, ask about blocked items, missing evidence, "
        f"executor failures, approvals, fact changes, costs, or next actions."
    )
    sources = [
        _source(f"projects/{project}/project_brain/acceptance_history.yml",
                "project status overview"),
    ]
    next_safe = _get_next_safe_action(snapshot)
    return answer, sources, next_safe
