"""M3-3 TUI command handlers — wired to Operator Action contracts."""

from __future__ import annotations

from .models import TUICommandResult, TUIWarning
from typing import Optional

try:
    from agent_runtime.operator_os.action_contract import validate_operator_action
except ImportError:
    def validate_operator_action(request):
        return {"status": "blocked", "errors": ["operator_os_unavailable"]}


def _require_auth(actor: Optional[str], reason: Optional[str]) -> Optional[TUICommandResult]:
    if not actor or not reason:
        return TUICommandResult(
            action="unknown",
            status="error",
            message="Missing actor or reason for mutation.",
            warnings=[TUIWarning("Action denied: Missing authentication or audit reason.")],
        )
    return None


def _validate_and_log(
    action: str,
    target_type: str,
    target_id: str,
    actor: Optional[str],
    reason: Optional[str],
    requested_effects: Optional[list[str]] = None,
) -> dict:
    """Run operator action validation and return result dict."""
    validation = validate_operator_action({
        "action": action,
        "target_type": target_type,
        "target_id": target_id,
        "actor": actor,
        "reason": reason,
        "requested_effects": requested_effects or [],
    })
    return validation


# ── M3 operator actions (wired to contract) ───────────────────────────────

def handle_approve(card_id: str, actor: Optional[str], reason: Optional[str], project: Optional[str] = None) -> TUICommandResult:
    err = _require_auth(actor, reason)
    if err:
        return err
    validation = _validate_and_log("approve", "phase_acceptance", card_id, actor, reason)
    if validation["status"] == "blocked":
        return TUICommandResult(
            action="approve",
            status="error",
            message=f"Approval blocked for {card_id}: {'; '.join(validation['errors'])}",
            requires_approval=True,
            mutated_state=False,
            warnings=[TUIWarning(e) for e in validation["errors"]],
        )
    return TUICommandResult(
        action="approve",
        status="ok",
        message=f"Approval recorded for {card_id} by {actor}.",
        requires_approval=True,
        mutated_state=True,
        evidence_path=f"projects/{project}/project_brain/acceptance_history.yml" if project else None,
        warnings=[],
    )


def handle_reject(card_id: str, actor: Optional[str], reason: Optional[str], project: Optional[str] = None) -> TUICommandResult:
    err = _require_auth(actor, reason)
    if err:
        return err
    validation = _validate_and_log("reject", "phase_acceptance", card_id, actor, reason)
    if validation["status"] == "blocked":
        return TUICommandResult(
            action="reject",
            status="error",
            message=f"Rejection blocked for {card_id}: {'; '.join(validation['errors'])}",
            requires_approval=True,
            mutated_state=False,
            warnings=[TUIWarning(e) for e in validation["errors"]],
        )
    return TUICommandResult(
        action="reject",
        status="ok",
        message=f"Rejection recorded for {card_id} by {actor}.",
        requires_approval=True,
        mutated_state=True,
        evidence_path=f"projects/{project}/project_brain/acceptance_history.yml" if project else None,
        warnings=[],
    )


def handle_pause(project: str, actor: Optional[str], reason: Optional[str]) -> TUICommandResult:
    err = _require_auth(actor, reason)
    if err:
        return err
    validation = _validate_and_log("pause", "project", project, actor, reason)
    if validation["status"] == "blocked":
        return TUICommandResult(
            action="pause",
            status="error",
            message=f"Pause blocked for {project}: {'; '.join(validation['errors'])}",
            requires_approval=True,
            mutated_state=False,
            warnings=[TUIWarning(e) for e in validation["errors"]],
        )
    return TUICommandResult(
        action="pause",
        status="ok",
        message=f"Pause requested for {project} by {actor}.",
        requires_approval=True,
        mutated_state=True,
        warnings=[],
    )


def handle_resume(project: str, actor: Optional[str], reason: Optional[str]) -> TUICommandResult:
    err = _require_auth(actor, reason)
    if err:
        return err
    validation = _validate_and_log("resume", "project", project, actor, reason)
    if validation["status"] == "blocked":
        return TUICommandResult(
            action="resume",
            status="error",
            message=f"Resume blocked for {project}: {'; '.join(validation['errors'])}",
            requires_approval=True,
            mutated_state=False,
            warnings=[TUIWarning(e) for e in validation["errors"]],
        )
    return TUICommandResult(
        action="resume",
        status="ok",
        message=f"Resume requested for {project} by {actor}.",
        requires_approval=True,
        mutated_state=True,
        warnings=[],
    )


def handle_retry(task_id: str, actor: Optional[str], reason: Optional[str]) -> TUICommandResult:
    err = _require_auth(actor, reason)
    if err:
        return err
    validation = _validate_and_log("retry", "task", task_id, actor, reason)
    if validation["status"] == "blocked":
        return TUICommandResult(
            action="retry",
            status="error",
            message=f"Retry blocked for {task_id}: {'; '.join(validation['errors'])}",
            requires_approval=True,
            mutated_state=False,
            warnings=[TUIWarning(e) for e in validation["errors"]],
        )
    return TUICommandResult(
        action="retry",
        status="ok",
        message=f"Retry requested for {task_id} by {actor}.",
        requires_approval=True,
        mutated_state=True,
        warnings=[],
    )


# ── read-only operator actions ────────────────────────────────────────────

def handle_inspect_evidence(task_id: str, project: Optional[str] = None) -> TUICommandResult:
    validation = _validate_and_log("inspect_evidence", "executor_result", task_id, None, None)
    if validation["status"] == "blocked":
        return TUICommandResult(
            action="inspect_evidence",
            status="error",
            message=f"Inspect blocked: {'; '.join(validation['errors'])}",
            mutated_state=False,
            warnings=[TUIWarning(e) for e in validation["errors"]],
        )
    return TUICommandResult(
        action="inspect_evidence",
        status="ok",
        message=f"Evidence inspection for {task_id}.",
        mutated_state=False,
        evidence_path=f"projects/{project}/runs/{task_id}/evidence_ledger.yml" if project else None,
        warnings=[],
    )


def handle_open_artifact(artifact_path: str) -> TUICommandResult:
    validation = _validate_and_log("open_artifact", "artifact", artifact_path, None, None)
    if validation["status"] == "blocked":
        return TUICommandResult(
            action="open_artifact",
            status="error",
            message=f"Open blocked: {'; '.join(validation['errors'])}",
            mutated_state=False,
            warnings=[TUIWarning(e) for e in validation["errors"]],
        )
    return TUICommandResult(
        action="open_artifact",
        status="ok",
        message=f"Opening artifact: {artifact_path}.",
        mutated_state=False,
        evidence_path=artifact_path,
        warnings=[],
    )


def handle_export_handoff(project: str) -> TUICommandResult:
    validation = _validate_and_log("export_handoff", "project", project, None, None)
    if validation["status"] == "blocked":
        return TUICommandResult(
            action="export_handoff",
            status="error",
            message=f"Export blocked: {'; '.join(validation['errors'])}",
            mutated_state=False,
            warnings=[TUIWarning(e) for e in validation["errors"]],
        )
    return TUICommandResult(
        action="export_handoff",
        status="ok",
        message=f"Handoff exported for {project}.",
        mutated_state=False,
        warnings=[],
    )
