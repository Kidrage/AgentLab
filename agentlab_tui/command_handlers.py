from .models import TUICommandResult, TUIWarning
from typing import Optional

def _require_auth(actor: Optional[str], reason: Optional[str]) -> Optional[TUICommandResult]:
    if not actor or not reason:
        return TUICommandResult(
            action="unknown",
            status="error",
            message="Missing actor or reason for mutation.",
            warnings=[TUIWarning("Action denied: Missing authentication or audit reason.")]
        )
    return None

def handle_approve(card_id: str, actor: Optional[str], reason: Optional[str], project: Optional[str] = None) -> TUICommandResult:
    err = _require_auth(actor, reason)
    if err: return err
    return TUICommandResult(
        action="approve",
        status="dry_run",
        message=f"Approval recorded for {card_id} by {actor}.",
        requires_approval=True,
        mutated_state=False,
        warnings=[TUIWarning("TUI skeleton dry run. Real ledger integration unavailable.")]
    )

def handle_reject(card_id: str, actor: Optional[str], reason: Optional[str], project: Optional[str] = None) -> TUICommandResult:
    err = _require_auth(actor, reason)
    if err: return err
    return TUICommandResult(
        action="reject",
        status="dry_run",
        message=f"Rejection recorded for {card_id} by {actor}.",
        requires_approval=True,
        mutated_state=False,
        warnings=[TUIWarning("TUI skeleton dry run. Real ledger integration unavailable.")]
    )

def handle_pause(project: str, actor: Optional[str], reason: Optional[str]) -> TUICommandResult:
    err = _require_auth(actor, reason)
    if err: return err
    return TUICommandResult(
        action="pause",
        status="dry_run",
        message=f"Pause requested for {project} by {actor}.",
        requires_approval=True,
        mutated_state=False,
        warnings=[TUIWarning("TUI skeleton dry run. Real ledger integration unavailable.")]
    )

def handle_resume(project: str, actor: Optional[str], reason: Optional[str]) -> TUICommandResult:
    err = _require_auth(actor, reason)
    if err: return err
    return TUICommandResult(
        action="resume",
        status="dry_run",
        message=f"Resume requested for {project} by {actor}.",
        requires_approval=True,
        mutated_state=False,
        warnings=[TUIWarning("TUI skeleton dry run. Real ledger integration unavailable.")]
    )

def handle_retry(task_id: str, actor: Optional[str], reason: Optional[str]) -> TUICommandResult:
    err = _require_auth(actor, reason)
    if err: return err
    return TUICommandResult(
        action="retry",
        status="dry_run",
        message=f"Retry requested for {task_id} by {actor}.",
        requires_approval=True,
        mutated_state=False,
        warnings=[TUIWarning("TUI skeleton dry run. Real ledger integration unavailable.")]
    )

def handle_rollback(task_id: str, actor: Optional[str], reason: Optional[str]) -> TUICommandResult:
    err = _require_auth(actor, reason)
    if err: return err
    return TUICommandResult(
        action="rollback",
        status="dry_run",
        message=f"Rollback requested for {task_id} by {actor}.",
        requires_approval=True,
        mutated_state=False,
        warnings=[TUIWarning("TUI skeleton dry run. Real ledger integration unavailable.")]
    )

def handle_enable_worker(worker_id: str, actor: Optional[str], reason: Optional[str]) -> TUICommandResult:
    err = _require_auth(actor, reason)
    if err: return err
    return TUICommandResult(
        action="enable_worker",
        status="dry_run",
        message=f"Enable requested for {worker_id} by {actor}.",
        requires_approval=True,
        mutated_state=False,
        warnings=[TUIWarning("TUI skeleton dry run. Real ledger integration unavailable.")]
    )

def handle_disable_worker(worker_id: str, actor: Optional[str], reason: Optional[str]) -> TUICommandResult:
    err = _require_auth(actor, reason)
    if err: return err
    return TUICommandResult(
        action="disable_worker",
        status="dry_run",
        message=f"Disable requested for {worker_id} by {actor}.",
        requires_approval=True,
        mutated_state=False,
        warnings=[TUIWarning("TUI skeleton dry run. Real ledger integration unavailable.")]
    )
