"""Resume recovery policy: deterministic next-action derivation.

Pure function that decides whether a task can resume based on the
recovery verdict, human review decisions, and optional force flag.

This is the single source of truth for resume/recovery gating logic.
"""

from __future__ import annotations

from typing import Optional


def derive_recovery_next_action(
    verdict: dict | None,
    human_decision=None,  # HumanReviewDecision | None
    retry_attempts: list | None = None,
    force: bool = False,
) -> dict:
    """Derive the next allowed action from a recovery verdict and human decisions.

    Args:
        verdict: The recovery verdict dict (from recovery_verdict.json).
        human_decision: A HumanReviewDecision or None.
        retry_attempts: Optional list of prior retry attempt records.
        force: Whether the caller passed --force.

    Returns:
        A dict with keys:
        - allowed (bool): whether the action is permitted
        - action (str): "retry" | "continue" | "block" | "stop"
        - reason (str): human-readable explanation
        - requires_force (bool): action is blocked unless --force is used
        - auditable_force_required (bool): force was used and should be audited
    """
    if verdict is None:
        return {
            "allowed": False,
            "action": "block",
            "reason": "No recovery verdict — inspect manually",
            "requires_force": False,
            "auditable_force_required": False,
        }

    v = verdict.get("verdict", "")
    safe_to_auto_retry = verdict.get("safe_to_auto_retry", True)

    # ── retry verdict ──
    if v == "retry":
        if human_decision is not None and human_decision.decision == "reject_retry":
            return {
                "allowed": False,
                "action": "stop",
                "reason": "Retry was rejected after verdict",
                "requires_force": False,
                "auditable_force_required": False,
            }
        return {
            "allowed": True,
            "action": "retry",
            "reason": "Retry allowed per policy",
            "requires_force": False,
            "auditable_force_required": False,
        }

    # ── human_review verdict ──
    if v == "human_review":
        if human_decision is None:
            return {
                "allowed": False,
                "action": "block",
                "reason": "Awaiting human review — use recovery-approve or recovery-reject",
                "requires_force": False,
                "auditable_force_required": False,
            }
        d = human_decision.decision
        if d == "approve_retry":
            # Dangerous categories (safe_to_auto_retry=False) are still
            # allowed after explicit human approval, but the override is
            # flagged as auditable.
            auditable = not safe_to_auto_retry
            return {
                "allowed": True,
                "action": "retry",
                "reason": "Retry allowed (human approved)",
                "requires_force": False,
                "auditable_force_required": auditable,
            }
        if d == "reject_retry":
            return {
                "allowed": False,
                "action": "stop",
                "reason": "Retry was rejected by human decision",
                "requires_force": False,
                "auditable_force_required": False,
            }
        if d == "stop":
            return {
                "allowed": False,
                "action": "stop",
                "reason": "Task was stopped by human decision",
                "requires_force": False,
                "auditable_force_required": False,
            }
        return {
            "allowed": False,
            "action": "block",
            "reason": f"Unknown human decision '{d}' — inspect manually",
            "requires_force": False,
            "auditable_force_required": False,
        }

    # ── stop verdict ──
    if v == "stop":
        if human_decision is not None and human_decision.decision == "approve_retry":
            if force or human_decision.force_used:
                return {
                    "allowed": True,
                    "action": "retry",
                    "reason": "Retry allowed (--force override of stop verdict)",
                    "requires_force": False,
                    "auditable_force_required": True,
                }
            return {
                "allowed": False,
                "action": "stop",
                "reason": "Stop verdict requires --force to override",
                "requires_force": True,
                "auditable_force_required": False,
            }
        return {
            "allowed": False,
            "action": "stop",
            "reason": "Task permanently failed (stop verdict)",
            "requires_force": False,
            "auditable_force_required": False,
        }

    # ── continue verdict ──
    if v == "continue":
        return {
            "allowed": True,
            "action": "continue",
            "reason": "Continue allowed (retries exhausted, manual next step)",
            "requires_force": False,
            "auditable_force_required": False,
        }

    # ── unknown verdict ──
    return {
        "allowed": False,
        "action": "block",
        "reason": f"Unknown verdict '{v}' — inspect manually",
        "requires_force": False,
        "auditable_force_required": False,
    }