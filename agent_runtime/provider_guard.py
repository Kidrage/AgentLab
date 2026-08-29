"""Provider guard — error classification, fallback decisions, and user decision files.

Centralises provider failure handling so that every API-backed agent stage
gets the same protection: classify error, decide fallback or pause, write
decision artifacts, and leave the task in a resumable state.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from agent_runtime.atomic_io import atomic_write_text, atomic_write_yaml, safe_read_yaml
from agent_runtime.incident_manager import record_incident
from agent_runtime.progress_tracker import mark_agent_paused


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── error classification ──────────────────────────────────────────────────


def classify_provider_error(exc: Exception) -> str:
    """Classify a provider exception into a standard error class."""
    text = str(exc).lower()
    status_code = getattr(exc, "status_code", None)

    if status_code in {401, 403}:
        return "auth_error"
    if status_code == 402:
        return "quota_exceeded"
    if status_code == 429:
        # 429 may be rate-limit or quota — check message text
        if any(kw in text for kw in ("quota", "balance", "credit", "insufficient", "payment")):
            return "quota_exceeded"
        return "rate_limited"
    if status_code in {500, 502, 503, 504}:
        return "provider_unavailable"

    if any(kw in text for kw in ("quota", "balance", "credit", "insufficient", "payment")):
        return "quota_exceeded"
    if "rate limit" in text or "too many requests" in text:
        return "rate_limited"
    if "context length" in text or "maximum context" in text or "too many tokens" in text:
        return "context_length_exceeded"
    if any(kw in text for kw in ("timeout", "timed out", "connection", "network")):
        return "network_error"
    if "invalid request" in text or "bad request" in text:
        return "invalid_request"
    if "content filter" in text or "safety" in text:
        return "content_filter"
    return "unknown_provider_error"


def is_recoverable_via_fallback(error_class: str) -> bool:
    """Check if fallback makes sense for this error class."""
    return error_class in (
        "quota_exceeded",
        "rate_limited",
        "provider_unavailable",
        "network_error",
        "timeout",
    )


def is_retryable(error_class: str) -> bool:
    """Check if the error might resolve with retry."""
    return error_class in ("rate_limited", "network_error", "timeout", "provider_unavailable")


# ── fallback decision ─────────────────────────────────────────────────────


def build_fallback_decision(
    agent_name: str,
    provider_key: str,
    error_class: str,
    error_message: str,
    *,
    role_auto_fallback_allowed: bool = False,
    risk_level: str = "R1",
    fallback_providers: Optional[list[dict]] = None,
) -> dict:
    """Decide how to handle a provider failure.

    Returns a decision dict with action and metadata.
    """
    decision = {
        "action": "pause_for_user",
        "reason": error_class,
        "from_provider": provider_key,
        "to_provider": None,
        "requires_user_approval": True,
        "checkpoint_id": None,
        "message": "",
    }

    # Context length exceeded → replan, not fallback
    if error_class == "context_length_exceeded":
        decision["action"] = "replan_required"
        decision["message"] = "Context length exceeded. Task needs chunking, summarization, or route replanning. Fallback to another provider will not help."
        return decision

    # Auth / key errors → check if another provider exists
    if error_class in ("auth_error", "missing_api_key"):
        if not fallback_providers:
            decision["action"] = "fail_terminal"
            decision["message"] = f"Auth error on {provider_key} and no fallback providers configured."
        else:
            decision["action"] = "pause_for_user"
            decision["message"] = f"Auth error on {provider_key}. User must verify credentials."
        return decision

    # Fatal errors → fail terminal
    if error_class in ("invalid_request", "content_filter"):
        decision["action"] = "fail_terminal"
        decision["message"] = f"Non-recoverable error: {error_class}. {error_message}"
        return decision

    # Recoverable errors
    if not is_recoverable_via_fallback(error_class):
        decision["action"] = "pause_for_user"
        decision["message"] = f"Unrecoverable error: {error_class}. Task paused for user review."
        return decision

    # Recoverable — check fallback chain
    if fallback_providers:
        next_provider = fallback_providers[0]
        decision["to_provider"] = next_provider.get("key", "")
        decision["to_model"] = next_provider.get("model", "")

        high_risk = risk_level in ("R2", "R3")
        if role_auto_fallback_allowed and not high_risk:
            decision["action"] = "switch_provider"
            decision["requires_user_approval"] = False
            decision["message"] = (
                f"Auto-switching from {provider_key} to {decision['to_provider']} "
                f"({error_class}). Risk={risk_level}, auto-fallback allowed."
            )
        else:
            decision["action"] = "pause_for_user"
            decision["requires_user_approval"] = True
            decision["message"] = (
                f"Provider {provider_key} failed ({error_class}). "
                f"Fallback {decision['to_provider']} is available but requires user approval "
                f"{'(high risk)' if high_risk else '(brain/execution stage)'}."
            )
    else:
        decision["action"] = "pause_for_user"
        decision["message"] = f"Provider {provider_key} failed ({error_class}). No fallback providers configured."

    return decision


# ── user decision file ────────────────────────────────────────────────────


def write_user_decision_file(
    run_dir: Path,
    project: str,
    task_id: str,
    agent_name: str,
    role: str,
    failed_provider: str,
    error_class: str,
    error_message: str,
    completed_agents: list[str],
    pending_agents: list[str],
    fallback_providers: Optional[list[dict]] = None,
) -> Path:
    """Write USER_DECISION_REQUIRED.md and the matching resume_plan.yml."""
    decision_path = run_dir / "USER_DECISION_REQUIRED.md"

    fallback_lines = ""
    resume_commands = ""
    if fallback_providers:
        for fb in fallback_providers:
            fallback_lines += (
                f"- `{fb.get('key')}` ({fb.get('model', '')}) — {fb.get('note', '')}\n"
            )

    markdown = f"""# User Decision Required

## Status
Task paused safely. No completed work was lost.

## Reason
Provider **{failed_provider}** failed during `{agent_name}` ({role}).

## Current Stage
- Project: `{project}`
- Task: `{task_id}`
- Agent: `{agent_name}`
- Role: `{role}`
- Failed provider: `{failed_provider}`
- Error class: `{error_class}`
- Error: {error_message}
- Completed agents: {', '.join(completed_agents) if completed_agents else '(none)'}
- Pending agents: {', '.join(pending_agents)}

## Available Options

### Option A — Recharge and resume same provider
Recharge the API balance for `{failed_provider}`, then resume.

```bash
./agentlab.sh resume --project {project} --task-id {task_id}
```

### Option B — Switch to fallback provider
{fallback_lines or '(No fallback providers configured)'}

### Option C — Stop this task
Task remains archived with all reports and checkpoints.

```bash
./agentlab.sh task-clear {task_id} --project {project} --reason "stopped after provider incident"
```

## Safety Note
AgentLab will not rerun completed agents. It will resume from the blocked agent
using the stored context and checkpoint.
"""
    atomic_write_text(decision_path, markdown)

    # Also write machine-readable resume plan
    resume_data = {
        "version": 1,
        "project": project,
        "task_id": task_id,
        "status": "paused_resumable",
        "paused_at": utc_now(),
        "paused_reason": error_class,
        "current_agent": agent_name,
        "current_role": role,
        "failed_provider": failed_provider,
        "completed_agents": completed_agents,
        "pending_agents": pending_agents,
        "resume_mode": "same_provider_or_approved_fallback",
        "allowed_resume_providers": (
            [failed_provider] + [fb["key"] for fb in (fallback_providers or [])]
        ),
        "must_reuse_prompt_package": True,
        "must_not_repeat_completed_agents": True,
        "must_validate_reports_before_continue": True,
    }
    atomic_write_yaml(run_dir / "resume_plan.yml", resume_data)

    return decision_path
