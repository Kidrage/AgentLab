"""Deployment hygiene checks for non-bare runtime repositories."""

from __future__ import annotations

from typing import Any


UNSAFE_DENY_CURRENT_BRANCH_VALUES = {"ignore", "warn", "updateinstead"}


def assess_checked_out_remote_push(
    *,
    remote_name: str,
    remote_url: str,
    receive_deny_current_branch: str | None,
) -> dict[str, Any]:
    """Return whether direct git push is safe for a runtime remote."""
    value = (receive_deny_current_branch or "").strip().lower()
    is_agentlab_runtime = remote_url.endswith(":/home/admin/AgentLab") or remote_url.endswith("/home/admin/AgentLab")
    unsafe = is_agentlab_runtime and value in UNSAFE_DENY_CURRENT_BRANCH_VALUES
    if unsafe:
        recommendation = (
            "Do not git push to this checked-out runtime repository. "
            "Deploy with ssh fetch/merge --ff-only, rsync, or a bare remote plus working copy."
        )
    else:
        recommendation = "No checked-out runtime push hazard detected."
    return {
        "remote": remote_name,
        "remote_url": remote_url,
        "receive_deny_current_branch": receive_deny_current_branch,
        "safe_to_push": not unsafe,
        "hazard": "checked_out_runtime_remote" if unsafe else "",
        "recommendation": recommendation,
    }
