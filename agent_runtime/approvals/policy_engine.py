"""Policy-bounded approval decisions shared by AgentLab execution surfaces."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Any, Mapping

from agent_runtime.approvals.approval_policy import ApprovalPolicy


@dataclass(frozen=True, slots=True)
class ApprovalDecision:
    mode: str
    requires_human: bool
    reasons: tuple[str, ...]
    grant: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class GrantValidation:
    valid: bool
    reasons: tuple[str, ...]


def decide_approval(
    request: Mapping[str, Any],
    policy: ApprovalPolicy,
    *,
    now: str | None = None,
) -> ApprovalDecision:
    """Return one auditable approval decision for a bounded action request."""
    action = str(request.get("action") or "").strip()
    if not action:
        return ApprovalDecision(
            mode="human_required",
            requires_human=True,
            reasons=("missing_action",),
        )
    if action in policy.forbidden_actions:
        return ApprovalDecision(
            mode="forbidden",
            requires_human=False,
            reasons=(f"forbidden_action:{action}",),
        )
    if action in policy.human_required_actions:
        return ApprovalDecision(
            mode="human_required",
            requires_human=True,
            reasons=(f"hard_human_action:{action}",),
        )
    if policy.default_mode != "auto":
        return ApprovalDecision(
            mode="human_required",
            requires_human=True,
            reasons=(f"policy_default_mode:{policy.default_mode}",),
        )

    cost_visibility = str(request.get("cost_visibility") or "known")
    if cost_visibility.startswith("unknown") and policy.require_approval_for_unknown_cli_cost:
        return ApprovalDecision(
            mode="human_required",
            requires_human=True,
            reasons=("unknown_cost",),
        )
    try:
        estimated_cost = float(request.get("estimated_cost_usd") or 0.0)
    except (TypeError, ValueError):
        return ApprovalDecision(
            mode="human_required",
            requires_human=True,
            reasons=("invalid_cost",),
        )
    if estimated_cost > policy.require_approval_above_usd:
        return ApprovalDecision(
            mode="human_required",
            requires_human=True,
            reasons=(
                "cost_exceeds_auto_limit:"
                f"{estimated_cost:.2f}>{policy.require_approval_above_usd:.2f}",
            ),
        )

    capabilities = {str(item) for item in request.get("capabilities", [])}
    critical = sorted(capabilities.intersection(policy.critical_capabilities))
    if critical:
        return ApprovalDecision(
            mode="human_required",
            requires_human=True,
            reasons=(f"critical_capabilities:{','.join(critical)}",),
        )
    mutating_capabilities = {
        "filesystem_write",
        "shell_execution",
        "external_write",
        "git_ops",
    }
    if capabilities.intersection(mutating_capabilities) and request.get("bounded_scope") is not True:
        return ApprovalDecision(
            mode="human_required",
            requires_human=True,
            reasons=("unbounded_mutation",),
        )

    scope_payload = _canonical_json(dict(request))
    scope_hash = hashlib.sha256(scope_payload.encode("utf-8")).hexdigest()
    policy_hash = _approval_policy_hash(policy)
    issued_at = _parse_timestamp(now) if now else datetime.now(timezone.utc)
    expires_at = issued_at + timedelta(minutes=policy.default_expiry_minutes)
    issued_at_text = _format_timestamp(issued_at)
    grant = {
        "actor": f"policy:{policy.policy_id}",
        "policy_id": policy.policy_id,
        "decision_mode": "policy_auto_approved",
        "grant_id": _grant_id(policy_hash, scope_hash, issued_at_text),
        "issued_at": issued_at_text,
        "expires_at": _format_timestamp(expires_at),
        "policy_hash": policy_hash,
        "scope_hash": scope_hash,
        "scope": json.loads(scope_payload),
    }
    return ApprovalDecision(
        mode="auto_approved",
        requires_human=False,
        reasons=("within_default_auto_policy",),
        grant=grant,
    )


def verify_approval_grant(
    grant: Mapping[str, Any],
    request: Mapping[str, Any],
    policy: ApprovalPolicy,
    *,
    now: str | None = None,
) -> GrantValidation:
    """Validate that a policy grant still matches policy, scope, and time."""
    reasons: list[str] = []
    if grant.get("decision_mode") != "policy_auto_approved":
        reasons.append("invalid_decision_mode")
    expected_actor = f"policy:{policy.policy_id}"
    if grant.get("actor") != expected_actor or grant.get("policy_id") != policy.policy_id:
        reasons.append("policy_identity_mismatch")
    if grant.get("policy_hash") != _approval_policy_hash(policy):
        reasons.append("policy_hash_mismatch")
    request_hash = hashlib.sha256(_canonical_json(dict(request)).encode("utf-8")).hexdigest()
    if grant.get("scope_hash") != request_hash:
        reasons.append("scope_hash_mismatch")
    embedded_scope_hash = hashlib.sha256(
        _canonical_json(grant.get("scope")).encode("utf-8")
    ).hexdigest()
    if grant.get("scope_hash") != embedded_scope_hash:
        reasons.append("embedded_scope_mismatch")
    try:
        issued_at_text = str(grant.get("issued_at") or "")
        issued_at = _parse_timestamp(issued_at_text)
        expires_at = _parse_timestamp(str(grant.get("expires_at") or ""))
        observed_at = _parse_timestamp(now) if now else datetime.now(timezone.utc)
        expected_expiry = issued_at + timedelta(minutes=policy.default_expiry_minutes)
        if expires_at != expected_expiry:
            reasons.append("invalid_grant_window")
        if observed_at < issued_at:
            reasons.append("grant_not_yet_valid")
        if observed_at >= expires_at:
            reasons.append("grant_expired")
        expected_grant_id = _grant_id(
            str(grant.get("policy_hash") or ""),
            str(grant.get("scope_hash") or ""),
            issued_at_text,
        )
        if grant.get("grant_id") != expected_grant_id:
            reasons.append("grant_id_mismatch")
    except ValueError:
        reasons.append("invalid_grant_timestamp")
    return GrantValidation(valid=not reasons, reasons=tuple(reasons))


def _approval_policy_hash(policy: ApprovalPolicy) -> str:
    return hashlib.sha256(_canonical_json(asdict(policy)).encode("utf-8")).hexdigest()


def _grant_id(policy_hash: str, scope_hash: str, issued_at: str) -> str:
    digest = hashlib.sha256(f"{policy_hash}:{scope_hash}:{issued_at}".encode()).hexdigest()
    return f"grant-{digest[:16]}"


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
