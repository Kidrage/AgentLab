"""Policy-bounded approval decisions shared by AgentLab execution surfaces."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
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
    action = str(request.get("action") or "").strip().lower()
    if not action:
        return ApprovalDecision(
            mode="human_required",
            requires_human=True,
            reasons=("missing_action",),
        )
    forbidden_actions = {item.strip().lower() for item in policy.forbidden_actions}
    human_required_actions = {item.strip().lower() for item in policy.human_required_actions}
    if action in forbidden_actions:
        return ApprovalDecision(
            mode="forbidden",
            requires_human=False,
            reasons=(f"forbidden_action:{action}",),
        )
    if action in human_required_actions:
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

    cost_visibility_raw = request.get("cost_visibility")
    cost_visibility_present = (
        "cost_visibility" in request
        and cost_visibility_raw is not None
        and str(cost_visibility_raw).strip() != ""
    )
    cost_visibility = (
        str(cost_visibility_raw).strip().lower()
        if cost_visibility_present
        else ""
    )
    capability_hints_raw = request.get("capabilities", [])
    if isinstance(capability_hints_raw, str):
        capability_hints_raw = [capability_hints_raw]
    capability_hints = (
        {
            str(item).strip().lower()
            for item in capability_hints_raw
            if str(item).strip()
        }
        if isinstance(capability_hints_raw, (list, tuple, set, frozenset))
        else set()
    )
    cost_sensitive_action = action in {
        "api_call",
        "external_execution",
        "model_call",
        "model_inference",
    } or bool(
        capability_hints.intersection(
            {"api_call", "external_execution", "model_call", "model_inference", "network_access"}
        )
    )
    execution_level_request = (
        request.get("bounded_scope") is True
        and request.get("output_dir") not in {None, ""}
        and request.get("runtime_recheck_required") is not True
        and request.get("scope_binding") != "runtime_recheck"
    )
    cost_evaluation_required = cost_sensitive_action or execution_level_request
    if cost_evaluation_required and not cost_visibility_present:
        return ApprovalDecision(
            mode="human_required",
            requires_human=True,
            reasons=("missing_cost_visibility",),
        )
    known_cost_visibility = {"known", "known_api_cost"}
    unknown_cost_visibility = {
        "unknown",
        "unknown_external_cli_cost",
        "unknown_external_provider_cost",
        "unavailable",
    }
    no_cost_visibility = {"free", "not_applicable"}
    allowed_cost_visibility = (
        known_cost_visibility | unknown_cost_visibility | no_cost_visibility
    )
    if cost_visibility_present and cost_visibility not in allowed_cost_visibility:
        return ApprovalDecision(
            mode="human_required",
            requires_human=True,
            reasons=("invalid_cost_visibility",),
        )
    if (
        cost_visibility in unknown_cost_visibility
        and policy.require_approval_for_unknown_cli_cost
    ):
        return ApprovalDecision(
            mode="human_required",
            requires_human=True,
            reasons=("unknown_cost",),
        )
    estimated_cost_raw = request.get("estimated_cost_usd")
    estimated_cost_present = (
        "estimated_cost_usd" in request
        and estimated_cost_raw is not None
        and not (
            isinstance(estimated_cost_raw, str)
            and estimated_cost_raw.strip() == ""
        )
    )
    requires_cost_estimate = cost_visibility in (
        known_cost_visibility | unknown_cost_visibility
    )
    if requires_cost_estimate and not estimated_cost_present:
        return ApprovalDecision(
            mode="human_required",
            requires_human=True,
            reasons=("missing_cost_estimate",),
        )
    if isinstance(estimated_cost_raw, bool):
        return ApprovalDecision(
            mode="human_required",
            requires_human=True,
            reasons=("invalid_cost",),
        )
    try:
        estimated_cost = float(estimated_cost_raw) if estimated_cost_present else 0.0
    except (TypeError, ValueError):
        return ApprovalDecision(
            mode="human_required",
            requires_human=True,
            reasons=("invalid_cost",),
        )
    if not math.isfinite(estimated_cost) or estimated_cost < 0:
        return ApprovalDecision(
            mode="human_required",
            requires_human=True,
            reasons=("invalid_cost",),
        )
    if cost_visibility in no_cost_visibility and estimated_cost != 0.0:
        return ApprovalDecision(
            mode="human_required",
            requires_human=True,
            reasons=("invalid_cost",),
        )
    request_limit_raw = request.get("max_cost_usd")
    if request_limit_raw is not None:
        try:
            request_limit = float(request_limit_raw)
        except (TypeError, ValueError):
            request_limit = float("nan")
        if not math.isfinite(request_limit) or request_limit < 0:
            return ApprovalDecision(
                mode="human_required",
                requires_human=True,
                reasons=("invalid_request_cost_limit",),
            )
        if estimated_cost > request_limit:
            return ApprovalDecision(
                mode="human_required",
                requires_human=True,
                reasons=(
                    "estimated_cost_exceeds_request_limit:"
                    f"{estimated_cost:.2f}>{request_limit:.2f}",
                ),
            )
    router_limit_raw = request.get("router_max_cost_usd")
    if router_limit_raw is not None:
        try:
            router_limit = float(router_limit_raw)
        except (TypeError, ValueError):
            router_limit = float("nan")
        if not math.isfinite(router_limit) or router_limit < 0:
            return ApprovalDecision(
                mode="human_required",
                requires_human=True,
                reasons=("invalid_router_cost_limit",),
            )
        if estimated_cost > router_limit:
            return ApprovalDecision(
                mode="human_required",
                requires_human=True,
                reasons=(
                    "estimated_cost_exceeds_router_limit:"
                    f"{estimated_cost:.2f}>{router_limit:.2f}",
                ),
            )
    try:
        approval_limit = float(policy.require_approval_above_usd)
    except (TypeError, ValueError):
        return ApprovalDecision(
            mode="human_required",
            requires_human=True,
            reasons=("invalid_policy_cost_limit",),
        )
    if not math.isfinite(approval_limit) or approval_limit < 0:
        return ApprovalDecision(
            mode="human_required",
            requires_human=True,
            reasons=("invalid_policy_cost_limit",),
        )
    if estimated_cost > approval_limit:
        return ApprovalDecision(
            mode="human_required",
            requires_human=True,
            reasons=(
                "cost_exceeds_auto_limit:"
                f"{estimated_cost:.2f}>{approval_limit:.2f}",
            ),
        )

    raw_capabilities = request.get("capabilities", [])
    if isinstance(raw_capabilities, str):
        raw_capabilities = [raw_capabilities]
    if not isinstance(raw_capabilities, (list, tuple, set, frozenset)):
        return ApprovalDecision(
            mode="human_required",
            requires_human=True,
            reasons=("invalid_capabilities",),
        )
    capabilities = {
        str(item).strip().lower()
        for item in raw_capabilities
        if str(item).strip()
    }
    critical_capabilities = {
        item.strip().lower() for item in policy.critical_capabilities
    }
    critical = sorted(capabilities.intersection(critical_capabilities))
    if critical:
        return ApprovalDecision(
            mode="human_required",
            requires_human=True,
            reasons=(f"critical_capabilities:{','.join(critical)}",),
        )
    mutating_capabilities = {
        "filesystem_write",
        "shell_execution",
        "shell_command",
        "shell",
        "write",
        "external_write",
        "git_ops",
    }
    if capabilities.intersection(mutating_capabilities) and request.get("bounded_scope") is not True:
        return ApprovalDecision(
            mode="human_required",
            requires_human=True,
            reasons=("unbounded_mutation",),
        )
    if capabilities.intersection(mutating_capabilities) and request.get("reversible") is not True:
        return ApprovalDecision(
            mode="human_required",
            requires_human=True,
            reasons=(
                "irreversible_mutation"
                if request.get("reversible") is False
                else "unknown_mutation_reversibility",
            ),
        )
    read_only_actions = {"filesystem_read", "inspect", "local_read", "read"}
    if (
        execution_level_request
        and action not in read_only_actions
        and request.get("reversible") is not True
    ):
        return ApprovalDecision(
            mode="human_required",
            requires_human=True,
            reasons=(
                "irreversible_action"
                if request.get("reversible") is False
                else "unknown_action_reversibility",
            ),
        )
    if request.get("reversible") is False and action not in read_only_actions:
        return ApprovalDecision(
            mode="human_required",
            requires_human=True,
            reasons=("irreversible_action",),
        )
    risky_capabilities = {
        item.strip().lower() for item in policy.risky_capabilities
    }
    unbounded_risky = sorted(capabilities.intersection(risky_capabilities))
    if (
        policy.require_approval_for_risky_capabilities
        and unbounded_risky
        and request.get("bounded_scope") is not True
    ):
        return ApprovalDecision(
            mode="human_required",
            requires_human=True,
            reasons=(f"unbounded_risky_capability:{','.join(unbounded_risky)}",),
        )
    try:
        expiry_minutes = float(policy.default_expiry_minutes)
    except (TypeError, ValueError):
        expiry_minutes = 0.0
    if not math.isfinite(expiry_minutes) or expiry_minutes <= 0:
        return ApprovalDecision(
            mode="human_required",
            requires_human=True,
            reasons=("invalid_grant_expiry",),
        )

    scope_payload = _canonical_json(_normalize_request(request))
    scope_hash = hashlib.sha256(scope_payload.encode("utf-8")).hexdigest()
    policy_hash = _approval_policy_hash(policy)
    issued_at = _parse_timestamp(now) if now else datetime.now(timezone.utc)
    expires_at = issued_at + timedelta(minutes=expiry_minutes)
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
        "authorizes_execution": (
            request.get("bounded_scope") is True
            and request.get("output_dir") not in {None, ""}
            and request.get("runtime_recheck_required") is not True
            and request.get("scope_binding") != "runtime_recheck"
        ),
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
    expected_execution_authority = (
        request.get("bounded_scope") is True
        and request.get("output_dir") not in {None, ""}
        and request.get("runtime_recheck_required") is not True
        and request.get("scope_binding") != "runtime_recheck"
    )
    if grant.get("authorizes_execution") is not expected_execution_authority:
        reasons.append("execution_authority_mismatch")
    expected_actor = f"policy:{policy.policy_id}"
    if grant.get("actor") != expected_actor or grant.get("policy_id") != policy.policy_id:
        reasons.append("policy_identity_mismatch")
    if grant.get("policy_hash") != _approval_policy_hash(policy):
        reasons.append("policy_hash_mismatch")
    request_hash = hashlib.sha256(
        _canonical_json(_normalize_request(request)).encode("utf-8")
    ).hexdigest()
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
        expected_expiry = issued_at + timedelta(minutes=float(policy.default_expiry_minutes))
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
    except (TypeError, ValueError, OverflowError):
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


def _normalize_request(request: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(request)
    normalized["action"] = str(request.get("action") or "").strip().lower()
    raw_capabilities = request.get("capabilities", [])
    if isinstance(raw_capabilities, str):
        raw_capabilities = [raw_capabilities]
    if isinstance(raw_capabilities, (list, tuple, set, frozenset)):
        normalized["capabilities"] = sorted(
            {
                str(item).strip().lower()
                for item in raw_capabilities
                if str(item).strip()
            }
        )
    if "cost_visibility" in request:
        normalized["cost_visibility"] = str(
            request.get("cost_visibility") or "known"
        ).strip().lower()
    return normalized


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
